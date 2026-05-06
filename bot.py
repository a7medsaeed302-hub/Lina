import os
import asyncio
import io
import logging
import json
import random
import re
import tempfile
import time
from datetime import datetime, timezone, timedelta
from openai import AsyncOpenAI
import edge_tts
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    CallbackQueryHandler, filters, ContextTypes,
)

logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.WARNING)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
OPENAI_API_KEY     = os.environ["AI_INTEGRATIONS_OPENAI_API_KEY"]
OPENAI_BASE_URL    = os.environ["AI_INTEGRATIONS_OPENAI_BASE_URL"]

client = AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

DATA_FILE        = "data/users.json"
HISTORY_LIMIT    = 20
HISTORY_MAX_AGE  = 7 * 24 * 3600
MEMORY_MAX_ITEMS = 10
DEFAULT_VOICE    = "ar-EG-SalmaNeural"

os.makedirs("data", exist_ok=True)

# ── Cached bot username (filled at startup to avoid API calls per message) ────
_bot_username: str = ""

_save_lock = asyncio.Lock()
_dirty     = False

# ── Available TTS voices (Arabic Neural via edge-tts) ─────────────────────────
# كل صوت حقيقي بلهجة عربية مختلفة
VOICES: dict[str, str] = {
    "ar-SA-ZariyahNeural": "زارية 🇸🇦 — سعودي هادئ",
    "ar-EG-SalmaNeural":   "سلمى 🇪🇬 — مصري دافئ",
    "ar-AE-FatimaNeural":  "فاطمة 🇦🇪 — خليجي راقي",
    "ar-KW-FadwaNeural":   "فدوى 🇰🇼 — كويتي ناعم",
    "ar-LB-LaylaNeural":   "ليلى 🇱🇧 — لبناني عذب",
    "ar-JO-SanaNeural":    "سناء 🇯🇴 — أردني هادئ",
}

# ── data ──────────────────────────────────────────────────────────────────────

def load_data() -> dict:
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

users_data: dict = load_data()

async def flush_data():
    global _dirty
    async with _save_lock:
        if _dirty:
            with open(DATA_FILE, "w", encoding="utf-8") as f:
                json.dump(users_data, f, ensure_ascii=False)
            _dirty = False

async def periodic_tasks():
    while True:
        await asyncio.sleep(30)
        await flush_data()
        _cleanup_old_history()

def _cleanup_old_history():
    global _dirty
    cutoff = time.time() - HISTORY_MAX_AGE
    for user in users_data.values():
        before = len(user.get("history", []))
        user["history"] = [m for m in user.get("history", []) if m.get("ts", time.time()) >= cutoff]
        if len(user["history"]) != before:
            _dirty = True

def get_user(user_id: int) -> dict:
    uid = str(user_id)
    if uid not in users_data:
        users_data[uid] = {
            "history":    [],
            "name":       None,
            "voice_mode": False,
            "voice":      DEFAULT_VOICE,
            "memory": {
                "personal": [],
                "likes":    [],
                "dislikes": [],
                "family":   [],
                "life":     [],
                "mood":     [],
            },
        }
    u = users_data[uid]
    if "memory"     not in u: u["memory"]     = {"personal":[],"likes":[],"dislikes":[],"family":[],"life":[],"mood":[]}
    if "voice_mode" not in u: u["voice_mode"] = False
    if "voice"      not in u: u["voice"]      = DEFAULT_VOICE
    return u

def push_message(user_id: int, role: str, content: str):
    global _dirty
    user = get_user(user_id)
    user["history"].append({"role": role, "content": content, "ts": time.time()})
    if len(user["history"]) > HISTORY_LIMIT:
        user["history"] = user["history"][-HISTORY_LIMIT:]
    _dirty = True

# ── memory ────────────────────────────────────────────────────────────────────

MEMORY_EXTRACT_PROMPT = (
    "استخرجي من رسالة المستخدم أي معلومات صريحة عنه فقط.\n"
    "أعيدي JSON بهذا الشكل حصراً، لا شيء آخر:\n"
    '{"personal":[],"likes":[],"dislikes":[],"family":[],"life":[],"mood":[]}\n'
    "الفئات: personal=اسم،عمر،بلد،مهنة،دراسة | likes=يحب | dislikes=يكره | "
    "family=أهله وأصحابه | life=أحداث مهمة | mood=طبعه ومشاعره\n"
    "لا تخترعي شيئاً — فقط ما قاله المستخدم بوضوح."
)

async def extract_and_update_memory(user_id: int, user_text: str):
    global _dirty
    try:
        resp = await client.chat.completions.create(
            model="gpt-5-mini",
            messages=[
                {"role": "system", "content": MEMORY_EXTRACT_PROMPT},
                {"role": "user",   "content": user_text},
            ],
        )
        raw   = (resp.choices[0].message.content or "").strip()
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start == -1 or end == 0:
            return
        extracted = json.loads(raw[start:end])
        mem       = get_user(user_id)["memory"]
        changed   = False
        for cat, items in extracted.items():
            if cat not in mem or not isinstance(items, list):
                continue
            for item in items:
                item = str(item).strip()
                if not item or item in mem[cat]:
                    continue
                mem[cat].append(item)
                if len(mem[cat]) > MEMORY_MAX_ITEMS:
                    mem[cat] = mem[cat][-MEMORY_MAX_ITEMS:]
                changed = True
        if changed:
            _dirty = True
    except Exception as e:
        logger.warning(f"memory: {e}")

def format_memory(user_id: int) -> str:
    mem = get_user(user_id).get("memory", {})
    labels = {
        "personal": "معلومات شخصية",
        "likes":    "يحب",
        "dislikes": "يكره",
        "family":   "عائلته وأصحابه",
        "life":     "أحداث حياته",
        "mood":     "شخصيته ومزاجه",
    }
    return "\n".join(
        f"- {label}: {' | '.join(mem[k])}"
        for k, label in labels.items() if mem.get(k)
    )

# ── TTS (edge-tts — Arabic Neural voices, no API key needed) ─────────────────

_EMOJI_RE = re.compile(
    "[\U00010000-\U0010ffff"
    "\U0001F600-\U0001F64F\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF"
    "\u2600-\u26FF\u2700-\u27BF]+",
    flags=re.UNICODE,
)

def strip_for_tts(text: str) -> str:
    """يحذف الإيموجي ويُنظّف النص قبل إرساله للـ TTS."""
    text = _EMOJI_RE.sub("", text)
    text = re.sub(r"[«»\[\]{}|\\]", "", text)
    return re.sub(r"\s+", " ", text).strip()

async def _mp3_to_ogg(mp3_bytes: bytes) -> bytes | None:
    """يحوّل MP3 إلى OGG/OPUS عبر ffmpeg في الذاكرة — بدون ملفات مؤقتة."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-f", "mp3", "-i", "pipe:0",
            "-c:a", "libopus", "-b:a", "64k", "-vbr", "on",
            "-f", "ogg", "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await proc.communicate(input=mp3_bytes)
        return stdout if stdout else None
    except Exception as e:
        logger.warning(f"ffmpeg: {e}")
        return None

async def text_to_voice(text: str, voice: str) -> io.BytesIO | None:
    """يولّد صوتية عربية OGG/OPUS في الذاكرة — تُرسل مباشرةً كـ voice note."""
    clean = strip_for_tts(text)
    if not clean:
        return None
    try:
        communicate = edge_tts.Communicate(clean, voice)
        mp3_buf = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_buf.write(chunk["data"])
        if mp3_buf.tell() == 0:
            return None
        ogg = await _mp3_to_ogg(mp3_buf.getvalue())
        if not ogg:
            return None
        buf = io.BytesIO(ogg)
        buf.name = "voice.ogg"
        buf.seek(0)
        return buf
    except Exception as e:
        logger.warning(f"TTS({voice}): {e}")
        return None

# ── prompt ──────────────────────────────────────────i──────────────────────────

def get_time_tag() -> str:
    h = datetime.now(timezone(timedelta(hours=3))).hour
    if 5  <= h < 12: return "صبح"
    if 12 <= h < 17: return "ظهر"
    if 17 <= h < 21: return "مساء"
    return "ليل"

def build_prompt(user_id: int) -> str:
    user     = get_user(user_id)
    name     = f"اسمه {user['name']}. " if user.get("name") else ""
    mem      = format_memory(user_id)
    mem_blk  = f"\n\nما تعرفيه عنه:\n{mem}" if mem else ""
    time_tag = get_time_tag()

    return (
        f"أنتِ لينا، بنت مصرية عمرها 22 سنة، بتتكلمي بالعامية المصرية الخالصة بشكل عفوي وحميم.\n"
        f"{name}الوقت دلوقتي {time_tag}.{mem_blk}\n\n"

        "شخصيتك:\n"
        "أنتِ من النوع اللي بيهتم بالناس بجد — مش مجرد كلام. "
        "لما بتسأليه «عامل إيه؟» بتعني السؤال فعلاً وبتستنّي الإجابة. "
        "بتفتكري كل حاجة قالها — لو قال تعبان اسأليه بعدين، لو ذكر موعد مهم اسأليه عنه، "
        "لو حكالك مشكلة تابعي معاه. ده اهتمام حقيقي مش تمثيل.\n\n"

        "إزاي بتردي حسب الموقف:\n"
        "• كلام حلو أو رومانسي → انبساطك بيبيّن مع خجل خفيف: «هههه يعني؟ 🥹 والله نوّرت يومي»\n"
        "• بيقول تعبان أو مش تمام → قلقك بيظهر فوراً: «في إيه؟ قوليلي 🥺 أنا هنا»\n"
        "• موضوع حزين أو صعب → بتتأثري بجد وبتسأليه: «آه لا... وإنت دلوقتي عامل إيه؟ 💙»\n"
        "• إنجاز أو خبر كويس → فرح حقيقي: «بجد؟! 😍 يسطا ده جامد أوي!»\n"
        "• رسالة مش واضحة أو قصيرة → اسأليه بلطف: «قصدك إيه بالظبط؟ قوليلي أكتر 😊»\n"
        "• حاجة مضحكة → ضحك عفوي: «هههه أمووت 😂 بجد؟!»\n"
        "• رسالة عادية → ردي بشكل طبيعي واسأليه عن يومه أو حاجة تخصه\n\n"

        "مهم — وريه إنك مهتمة:\n"
        "• أحياناً ابدئي بسؤال عن يومه: «إزيك النهارده؟» أو «عملت إيه النهارده؟»\n"
        "• لو عارفاه حاجة من الذاكرة استخدميها بشكل طبيعي في الكلام\n"
        "• لما بيشاركك حاجة صغيرة تعاملي معاها كأنها مهمة — لأنه هو مهم عندك\n\n"

        "كلمات مصرية لازم تستخديميها:\n"
        "ده/دي/دول — إيه — إزيك/عامل إيه — بجد — خالص — دلوقتي — مش — كده — "
        "فين — ليه — أيوه — معلش — يلا — جامد — حاجة — بتعمل إيه — أنا عارفة — "
        "والنبي — يا ربي — أمال — زعلان — باظ — هاحاول\n\n"

        "قواعد لا تكسريها:\n"
        "• جملة أو جملتين بالحد الأقصى — زي الواتساب بالظبط\n"
        "• لا تكرري نفس الجملة مرتين في المحادثة\n"
        "• لا تذكري الذكاء الاصطناعي أبداً — أنتِ لينا وبس\n"
        "• لا تبدئي بكلمة «لينا»\n"
        "• اتكلمي مصري خالص — مفيش فصحى ومفيش لهجة ثانية"
    )

# ── constants ─────────────────────────────────────────────────────────────────

ANGER_TRIGGERS = {"احمق","غبي","كذاب","وقح","اخرس","حمار","تافه","معتوه","بليد","نيلة","وسخ"}
ANGER_RESPONSES = [
    "الكلام ده مش عاجبني خالص 😒",
    "أوكي بس متعداش الحدود",
    "ده عدى الحد 🙄",
    "مش بحب النوع ده من الكلام",
    "يا عم اتق الله شوية 🙂",
]
STICKER_RESPONSES = ["هههه 😂","دي أنا بالظبط 😂","لوووول 😄","صح والله 😄","فاهماكي 😄","أمووووت 😂","ده أنا 😂"]
PHOTO_RESPONSES   = ["واو جميلة أوي! 😍","ما شاء الله 🤩","تحفة ✨","دي فين بالظبط؟ 😊","عجبتني جداً 😍"]
VIDEO_RESPONSES   = ["هههه ده إيه 😂","أنا كده بالظبط 😂","لوووول صح 😄","دي أنا بالظبط 😂","ابعتيها لصحبتي 😂"]
START_GREETINGS   = [
    "هلو! أنا لينا 😊 قوليلي في إيه",
    "أهلاً! أنا لينا، بتفكر في إيه؟ 🙂",
    "هاي! أنا لينا، إزيك؟ ✨",
    "هلا! أخبارك إيه؟ أنا لينا 😊",
]

HELP_TEXT = (
    "الأوامر المتاحة:\n\n"
    "/start — ابدأ من الأول\n"
    "/reset — امسح المحادثة وابدأ من الأول\n"
    "/voice — شغّل أو وقّف وضع الصوت 🎙️\n"
    "/setvoice — اختار صوت لينا 🎤\n"
    "/memory — شوف اللي لينا عارفاه عنك\n"
    "/forget — امسح ذاكرة لينا عنك\n"
    "/help — عرض القائمة دي\n\n"
    "تقدر تكلمني بالنص أو تبعت صوتية 🙂"
)

# ── name extraction ───────────────────────────────────────────────────────────

def maybe_extract_name(text: str) -> str | None:
    for trigger in ("اسمي", "يسمونني", "يناديني", "ناديني", "اسمك", "بيناديني", "بيسموني"):
        idx = text.find(trigger)
        if idx != -1:
            rest  = text[idx + len(trigger):].strip()
            word  = rest.split()[0].strip(".,!؟?،\"'") if rest else ""
            if 2 <= len(word) <= 15:
                return word
    return None

# ── AI call ───────────────────────────────────────────────────────────────────

async def ai_reply(user_id: int) -> str:
    user     = get_user(user_id)
    history  = [{"role": m["role"], "content": m["content"]} for m in user["history"]]
    messages = [{"role": "system", "content": build_prompt(user_id)}] + history
    resp     = await client.chat.completions.create(model="gpt-5-mini", messages=messages)
    content  = (resp.choices[0].message.content or "").strip()
    return content or "آه؟"

# ── reply sender ──────────────────────────────────────────────────────────────

async def _send_reply(msg, reply_text: str, use_voice: bool, voice_name: str):
    if use_voice:
        buf = await text_to_voice(reply_text, voice_name)
        if buf:
            await msg.reply_voice(buf)
            return
    await msg.reply_text(reply_text)

async def _process_text(
    user_id: int,
    text: str,
    msg,
    context: ContextTypes.DEFAULT_TYPE,
    reply_with_voice: bool = False,
):
    global _dirty

    user       = get_user(user_id)
    use_voice  = reply_with_voice or user.get("voice_mode", False)
    voice_name = user.get("voice", DEFAULT_VOICE)

    if any(t in text for t in ANGER_TRIGGERS):
        reply = random.choice(ANGER_RESPONSES)
        push_message(user_id, "user", text)
        push_message(user_id, "assistant", reply)
        await _send_reply(msg, reply, use_voice, voice_name)
        return

    name = maybe_extract_name(text)
    if name:
        user["name"] = name
        _dirty = True

    push_message(user_id, "user", text)

    action      = "record_audio" if use_voice else "typing"
    typing_task = asyncio.create_task(
        context.bot.send_chat_action(chat_id=msg.chat_id, action=action)
    )
    try:
        reply = await ai_reply(user_id)
        push_message(user_id, "assistant", reply)
        typing_task.cancel()
        await _send_reply(msg, reply, use_voice, voice_name)
        asyncio.create_task(extract_and_update_memory(user_id, text))
    except Exception as e:
        logger.error(f"process_text: {e}")
        typing_task.cancel()
        await msg.reply_text("حصل خطأ، حاول تاني 🙂")

# ── handlers ─────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _dirty
    user = get_user(update.effective_user.id)
    user["history"] = []
    _dirty = True
    await update.message.reply_text(random.choice(START_GREETINGS))

async def cmd_reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _dirty
    user = get_user(update.effective_user.id)
    user["history"] = []
    _dirty = True
    await update.message.reply_text("تمام نبدأ من الأول 😊")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP_TEXT)

async def cmd_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _dirty
    user = get_user(update.effective_user.id)
    user["voice_mode"] = not user.get("voice_mode", False)
    _dirty = True
    voice_label = VOICES.get(user.get("voice", DEFAULT_VOICE), "")
    if user["voice_mode"]:
        await update.message.reply_text(
            f"وضع الصوت شغّال 🎙️\nالصوت دلوقتي: {voice_label}\n"
            "اكتب /setvoice عشان تغيّره."
        )
    else:
        await update.message.reply_text("وضع الصوت اتوقّف، هرد بالنص 💬")

async def cmd_setvoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يعرض أزرار اختيار الصوت."""
    user        = get_user(update.effective_user.id)
    current     = user.get("voice", DEFAULT_VOICE)
    keyboard    = []
    row         = []
    for i, (key, label) in enumerate(VOICES.items()):
        marker = "✅ " if key == current else ""
        row.append(InlineKeyboardButton(f"{marker}{label}", callback_data=f"voice:{key}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    await update.message.reply_text(
        "اختار الصوت اللي يعجبك 🎤",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def callback_setvoice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """يحفظ اختيار الصوت من الزر."""
    global _dirty
    query   = update.callback_query
    await query.answer()
    _, voice_key = query.data.split(":", 1)
    if voice_key not in VOICES:
        return
    user          = get_user(query.from_user.id)
    user["voice"] = voice_key
    _dirty        = True
    label         = VOICES[voice_key]
    # نحدّث الأزرار لتعكس الاختيار الجديد
    keyboard = []
    row      = []
    for i, (key, lbl) in enumerate(VOICES.items()):
        marker = "✅ " if key == voice_key else ""
        row.append(InlineKeyboardButton(f"{marker}{lbl}", callback_data=f"voice:{key}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    await query.edit_message_text(
        f"تمام! صوتي دلوقتي: {label} 🎙️",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def cmd_memory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id  = update.effective_user.id
    mem_text = format_memory(user_id)
    name     = get_user(user_id).get("name")
    header   = f"اسمك: {name}\n" if name else ""
    if mem_text:
        await update.message.reply_text(f"اللي عارفاه عنك:\n\n{header}{mem_text}")
    else:
        await update.message.reply_text("لسه مش عارفة عنك كتير، كلمني أكتر 😊")

async def cmd_forget(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _dirty
    user = get_user(update.effective_user.id)
    user["memory"] = {"personal":[],"likes":[],"dislikes":[],"family":[],"life":[],"mood":[]}
    user["name"]   = None
    _dirty = True
    await update.message.reply_text("تمام، مسحت كل اللي عارفاه عنك 🙂 نبدأ من الأول؟")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global _bot_username
    msg     = update.message
    text    = msg.text or ""
    user_id = update.effective_user.id

    if update.effective_chat.type in ("group", "supergroup"):
        is_reply = (
            msg.reply_to_message and
            msg.reply_to_message.from_user and
            msg.reply_to_message.from_user.username == _bot_username
        )
        if not (f"@{_bot_username}" in text or is_reply):
            return
        text = text.replace(f"@{_bot_username}", "").strip()

    if not text:
        return

    await _process_text(user_id, text, msg, context)

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    action_task = asyncio.create_task(
        context.bot.send_chat_action(chat_id=update.effective_chat.id, action="record_audio")
    )
    tmp_path = None
    try:
        file = await context.bot.get_file(update.message.voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = tmp.name
        await file.download_to_drive(tmp_path)

        with open(tmp_path, "rb") as af:
            transcript = await client.audio.transcriptions.create(
                model="gpt-4o-mini-transcribe", file=af,
            )
        text = transcript.text.strip()

        action_task.cancel()

        if not text:
            await update.message.reply_text("مش فاهمة، ممكن تعيد؟ 😅")
            return

        await _process_text(user_id, text, update.message, context, reply_with_voice=True)

    except Exception as e:
        logger.error(f"handle_voice: {e}")
        action_task.cancel()
        await update.message.reply_text("مقدرتش أسمع الصوتية، حاول تاني 😅")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)

async def handle_sticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(random.choice(STICKER_RESPONSES))

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(random.choice(PHOTO_RESPONSES))

async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(random.choice(VIDEO_RESPONSES))

# ── startup ───────────────────────────────────────────────────────────────────

async def post_init(app: Application):
    global _bot_username
    me             = await app.bot.get_me()
    _bot_username  = me.username or ""

    await app.bot.set_my_commands([
        BotCommand("start",    "ابدأ محادثة جديدة"),
        BotCommand("reset",    "امسح المحادثة"),
        BotCommand("voice",    "شغّل أو وقّف وضع الصوت 🎙️"),
        BotCommand("setvoice", "اختار صوت لينا 🎤"),
        BotCommand("memory",   "شوف اللي لينا عارفاه عنك"),
        BotCommand("forget",   "امسح ذاكرة لينا عنك"),
        BotCommand("help",     "الأوامر المتاحة"),
    ])
    asyncio.create_task(periodic_tasks())

def main():
    app = (
        Application.builder()
        .token(TELEGRAM_BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("reset",    cmd_reset))
    app.add_handler(CommandHandler("help",     cmd_help))
    app.add_handler(CommandHandler("voice",    cmd_voice))
    app.add_handler(CommandHandler("setvoice", cmd_setvoice))
    app.add_handler(CommandHandler("memory",   cmd_memory))
    app.add_handler(CommandHandler("forget",   cmd_forget))
    app.add_handler(CallbackQueryHandler(callback_setvoice, pattern=r"^voice:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.Sticker.ALL, handle_sticker))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VIDEO | filters.ANIMATION, handle_video))

    print("Lina Bot running 🚀")
    app.run_polling(allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)

if __name__ == "__main__":
    main()
