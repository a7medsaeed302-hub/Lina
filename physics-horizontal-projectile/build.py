#!/usr/bin/env python3
"""
Build script: template.html  ->  index.html

- Generates the projectile-motion diagrams as inline SVG (same style as the PDF:
  sandy platform, dashed burgundy/teal trajectories, mint ground strip, teal arrows)
- Embeds assets/logo.jpg as a data URI so index.html is a single portable file.

Usage:  python3 build.py
"""
import base64
import pathlib
import re

HERE = pathlib.Path(__file__).parent

TEAL = "#0E7C86"
BURG = "#7C1747"
INK = "#1E1B1B"
SAND = "#EADFA6"
MINT = "#DDF1E3"
GOLD = "#D9A441"
ORANGE = "#D98C5F"

GROUND_Y = 158
PLAT_X0, PLAT_X1 = 30, 64  # platform left / right (launch edge)


def parabola(x0, y0, x1, y1):
    """True projectile path: x linear, y quadratic."""
    pts = []
    for i in range(25):
        u = i / 24
        pts.append(f"{x0 + (x1 - x0) * u:.1f},{y0 + (y1 - y0) * u * u:.1f}")
    return "M" + " L".join(pts)


def traj(x0, y0, x1, color):
    return (
        f'<path d="{parabola(x0, y0, x1, GROUND_Y)}" fill="none" stroke="{color}" '
        f'stroke-width="2.4" stroke-dasharray="5 4.5" stroke-linecap="round"/>'
        f'<circle cx="{x1}" cy="{GROUND_Y}" r="4" fill="{color}"/>'
    )


def arrow_h(x, y, x2, color=TEAL, w=2.2):
    return (
        f'<line x1="{x}" y1="{y}" x2="{x2}" y2="{y}" stroke="{color}" stroke-width="{w}"/>'
        f'<path d="M{x2},{y} l-7,-3.6 v7.2 z" fill="{color}"/>'
    )


def arrow_v_double(x, y_top, y_bot=GROUND_Y, color=TEAL):
    return (
        f'<line x1="{x}" y1="{y_top + 3}" x2="{x}" y2="{y_bot - 3}" stroke="{color}" stroke-width="1.9"/>'
        f'<path d="M{x},{y_top} l-3.4,7 h6.8 z" fill="{color}"/>'
        f'<path d="M{x},{y_bot} l-3.4,-7 h6.8 z" fill="{color}"/>'
    )


def arrow_h_double(x0, x1, y, color=TEAL):
    return (
        f'<line x1="{x0 + 3}" y1="{y}" x2="{x1 - 3}" y2="{y}" stroke="{color}" stroke-width="1.9"/>'
        f'<path d="M{x0},{y} l7,-3.4 v6.8 z" fill="{color}"/>'
        f'<path d="M{x1},{y} l-7,-3.4 v6.8 z" fill="{color}"/>'
    )


def txt(x, y, s, size=10.5, color=TEAL, anchor="middle", weight=600, cls="svg-f", rotate=None):
    rot = f' transform="rotate({rotate} {x} {y})"' if rotate else ""
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" font-weight="{weight}" '
        f'text-anchor="{anchor}" class="{cls}"{rot}>{s}</text>'
    )


def ground():
    return (
        f'<rect x="0" y="{GROUND_Y}" width="300" height="{186 - GROUND_Y}" fill="{MINT}"/>'
        f'<line x1="0" y1="{GROUND_Y}" x2="300" y2="{GROUND_Y}" stroke="{INK}" stroke-width="1.6"/>'
    )


def platform(top):
    return (
        f'<rect x="{PLAT_X0}" y="{top}" width="{PLAT_X1 - PLAT_X0}" height="{GROUND_Y - top}" '
        f'fill="{SAND}" stroke="{INK}" stroke-width="1.7"/>'
    )


def launch_dot(x, y, color=BURG):
    return f'<circle cx="{x}" cy="{y}" r="4.4" fill="{color}" stroke="{INK}" stroke-width="1"/>'


def svg(body):
    return (
        '<svg viewBox="0 0 300 186" xmlns="http://www.w3.org/2000/svg" '
        f'role="img" aria-hidden="true">{ground()}{body}</svg>'
    )


def std(v_label=None, h_label=None, x_label=None, top=52, landing=248):
    b = platform(top)
    if h_label:
        b += arrow_v_double(16, top)
        b += txt(9, (top + GROUND_Y) / 2 + 3, h_label, 10, TEAL, rotate=-90)
    b += traj(PLAT_X1, top, landing, BURG)
    b += arrow_h(PLAT_X1 + 3, top, PLAT_X1 + 48)
    if v_label:
        b += txt(PLAT_X1 + 26, top - 7, v_label, 10.5)
    if x_label:
        b += arrow_h_double(PLAT_X0, landing, 172)
        b += txt((PLAT_X0 + landing) / 2, 168, x_label, 10)
    b += launch_dot(PLAT_X1, top)
    return svg(b)


def two_range(v_label=None, short_label=None, long_label=None, top=52):
    """Same launch point, two ranges: teal (short) + burgundy (long)."""
    b = platform(top)
    b += traj(PLAT_X1, top, 168, TEAL)
    b += traj(PLAT_X1, top, 256, BURG)
    b += arrow_h(PLAT_X1 + 3, top, PLAT_X1 + 48)
    if v_label:
        b += txt(PLAT_X1 + 26, top - 7, v_label, 10.5)
    if short_label:
        b += txt(168, GROUND_Y - 9, short_label, 9.5, TEAL)
    if long_label:
        b += txt(256, GROUND_Y - 9, long_label, 9.5, BURG)
    b += launch_dot(PLAT_X1, top, TEAL)
    return svg(b)


def two_height(top_label, low_label, kind="ar"):
    """Two launch heights from the same building."""
    top_y, low_y = 44, 92
    b = platform(top_y)
    b += traj(PLAT_X1, top_y, 256, BURG)
    b += traj(PLAT_X1, low_y, 182, TEAL)
    b += arrow_h(PLAT_X1 + 3, top_y, PLAT_X1 + 36, TEAL)
    b += arrow_h(PLAT_X1 + 3, low_y, PLAT_X1 + 36, TEAL)
    cls = "svg-ar" if kind == "ar" else "svg-f"
    b += txt(PLAT_X1 + 20, top_y - 7, top_label, 9.5, BURG, cls=cls)
    b += txt(PLAT_X1 + 20, low_y - 7, low_label, 9.5, TEAL, cls=cls)
    b += launch_dot(PLAT_X1, top_y, BURG)
    b += launch_dot(PLAT_X1, low_y, TEAL)
    return svg(b)


def heli():
    b = ""
    hx, hy = 96, 46  # helicopter centre
    # tail + rotor
    b += f'<line x1="{hx - 52}" y1="{hy - 6}" x2="{hx - 8}" y2="{hy - 2}" stroke="{INK}" stroke-width="2.6"/>'
    b += f'<line x1="{hx - 56}" y1="{hy - 14}" x2="{hx - 56}" y2="{hy + 2}" stroke="{INK}" stroke-width="2.2"/>'
    b += f'<line x1="{hx - 30}" y1="{hy - 18}" x2="{hx + 30}" y2="{hy - 18}" stroke="{INK}" stroke-width="2.6"/>'
    b += f'<line x1="{hx}" y1="{hy - 18}" x2="{hx}" y2="{hy - 9}" stroke="{INK}" stroke-width="2.2"/>'
    # body + skids
    b += f'<ellipse cx="{hx}" cy="{hy}" rx="24" ry="11" fill="{TEAL}" stroke="{INK}" stroke-width="1.6"/>'
    b += f'<line x1="{hx - 14}" y1="{hy + 12}" x2="{hx - 10}" y2="{hy + 18}" stroke="{INK}" stroke-width="1.8"/>'
    b += f'<line x1="{hx + 12}" y1="{hy + 12}" x2="{hx + 10}" y2="{hy + 18}" stroke="{INK}" stroke-width="1.8"/>'
    b += f'<line x1="{hx - 18}" y1="{hy + 18}" x2="{hx + 18}" y2="{hy + 18}" stroke="{INK}" stroke-width="1.8"/>'
    # package
    px, py = hx + 4, hy + 24
    b += f'<rect x="{px - 6}" y="{py - 5}" width="12" height="10" fill="{GOLD}" stroke="{INK}" stroke-width="1.4"/>'
    # trajectory to the man
    mx = 252
    b += traj(px, py + 5, mx, BURG)
    # velocity arrow
    b += arrow_h(hx + 30, hy - 6, hx + 66)
    b += txt(hx + 48, hy - 12, "v", 11)
    # labels y / x / d
    b += arrow_v_double(16, hy)
    b += txt(9, (hy + GROUND_Y) / 2 + 3, "y", 10.5, TEAL, rotate=-90)
    b += arrow_h_double(px, mx, 172)
    b += txt((px + mx) / 2, 168, "x", 10.5)
    b += txt(196, 104, "d", 11, BURG)
    # stick man
    b += (
        f'<circle cx="{mx}" cy="{GROUND_Y - 26}" r="5" fill="none" stroke="{INK}" stroke-width="1.8"/>'
        f'<line x1="{mx}" y1="{GROUND_Y - 21}" x2="{mx}" y2="{GROUND_Y - 10}" stroke="{INK}" stroke-width="1.8"/>'
        f'<line x1="{mx}" y1="{GROUND_Y - 17}" x2="{mx - 6}" y2="{GROUND_Y - 12}" stroke="{INK}" stroke-width="1.8"/>'
        f'<line x1="{mx}" y1="{GROUND_Y - 17}" x2="{mx + 6}" y2="{GROUND_Y - 12}" stroke="{INK}" stroke-width="1.8"/>'
        f'<line x1="{mx}" y1="{GROUND_Y - 10}" x2="{mx - 5}" y2="{GROUND_Y}" stroke="{INK}" stroke-width="1.8"/>'
        f'<line x1="{mx}" y1="{GROUND_Y - 10}" x2="{mx + 5}" y2="{GROUND_Y}" stroke="{INK}" stroke-width="1.8"/>'
    )
    return svg(b)


def coins():
    top = 52
    b = platform(top)
    bx = 252
    # B: vertical free fall (dashed teal) with matching heights
    b += (
        f'<line x1="{bx}" y1="{top}" x2="{bx}" y2="{GROUND_Y}" stroke="{TEAL}" '
        f'stroke-width="2" stroke-dasharray="4 4"/>'
    )
    b += traj(PLAT_X1, top, 208, BURG)
    for u in (0.28, 0.55, 0.8):
        x = PLAT_X1 + (208 - PLAT_X1) * u
        y = top + (GROUND_Y - top) * u * u
        b += f'<circle cx="{x:.0f}" cy="{y:.0f}" r="4.6" fill="{GOLD}" stroke="{BURG}" stroke-width="1.4"/>'
        b += f'<circle cx="{bx}" cy="{y:.0f}" r="4.6" fill="{GOLD}" stroke="{TEAL}" stroke-width="1.4"/>'
    b += f'<circle cx="{bx}" cy="{GROUND_Y}" r="4.6" fill="{GOLD}" stroke="{TEAL}" stroke-width="1.4"/>'
    b += arrow_h(PLAT_X1 + 3, top, PLAT_X1 + 42)
    b += txt(PLAT_X1 + 22, top - 7, "v₀", 10.5)
    b += txt(PLAT_X1 - 2, top - 12, "A", 11, BURG)
    b += txt(bx, top - 12, "B", 11, TEAL)
    b += launch_dot(PLAT_X1, top, GOLD)
    b += f'<circle cx="{bx}" cy="{top}" r="4.6" fill="{GOLD}" stroke="{TEAL}" stroke-width="1.4"/>'
    return svg(b)


DIAGRAMS = {
    "a1": lambda: two_height("الدور العاشر", "الدور الرابع"),
    "a2": heli,
    "a3": lambda: std("6.0 m/s", "h", "x"),
    "a4": lambda: two_range("v₀ أقل"),
    "a5": lambda: std("1.5 m/s", "0.75 m", "x"),
    "b1": lambda: two_range("2v", "v", "2v"),
    "b2": lambda: std("v₀"),
    "b3": lambda: two_height("4h", "h", kind="f"),
    "b4": coins,
    "b5": lambda: std("8 m/s", "30 m", "x"),
    "c1": lambda: two_range("v₀/2", "v₀/2", "v₀"),
    "c2": lambda: std("v₀"),
    "c3": lambda: std("v₀", "22.0 m", "35.0 m"),
    "c4": lambda: two_height("ارتفاع أكبر", "ارتفاع أقل"),
    "c5": lambda: std("3.0 m/s", "h", "x (المدى)"),
}


def main():
    html = (HERE / "template.html").read_text(encoding="utf-8")
    logo_b64 = base64.b64encode((HERE / "assets" / "logo.jpg").read_bytes()).decode()
    html = html.replace("%%LOGO%%", f"data:image/jpeg;base64,{logo_b64}")

    def repl(m):
        return DIAGRAMS[m.group(1)]()

    html = re.sub(r"%%DIAGRAM:(\w+)%%", repl, html)
    assert "%%" not in html, "unreplaced placeholder left in template"
    out = HERE / "index.html"
    out.write_text(html, encoding="utf-8")
    print(f"built {out}  ({out.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
