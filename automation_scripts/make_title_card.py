"""
RedditTales336 - title card maker
Makes a transparent PNG "post card" to lay over gameplay for the first few seconds.

Usage (from the project folder):
    python automation_scripts/make_title_card.py --sub AmItheAsshole --title "AITA for not letting my wife name our dog something stupid?" --flair "Not the A-hole" --out dog-name

Output: assets/title_cards/<out>.png   (1080 px wide, transparent background)
Needs Pillow once:  python -m pip install pillow
"""
import argparse
import os
import sys
import textwrap

from PIL import Image, ImageDraw, ImageFont

# ---- Brand settings (change these once and every card updates) ----
CHANNEL = "RedditTales336"
ACCENT = (255, 69, 0)          # orange avatar / flair outline
CARD_BG = (255, 255, 255)
TEXT = (26, 26, 27)
MUTED = (120, 124, 126)
WIDTH = 1080
PAD = 56

FONT_CANDIDATES = {
    "bold": ["C:/Windows/Fonts/segoeuib.ttf", "C:/Windows/Fonts/arialbd.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"],
    "regular": ["C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"],
}


def font(kind, size):
    for path in FONT_CANDIDATES[kind]:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size)


def wrap(draw, text, fnt, max_w):
    lines, line = [], ""
    for word in text.split():
        test = (line + " " + word).strip()
        if draw.textlength(test, font=fnt) <= max_w:
            line = test
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def arrow(draw, cx, cy, s, up=True, color=MUTED):
    # simple outlined arrow: triangle head + stem
    d = -1 if up else 1
    head = [(cx, cy + d * s), (cx - s, cy), (cx - s * 0.45, cy),
            (cx - s * 0.45, cy - d * s * 0.9), (cx + s * 0.45, cy - d * s * 0.9),
            (cx + s * 0.45, cy), (cx + s, cy)]
    draw.polygon(head, outline=color, width=4)


def bubble(draw, x, y, s, color=MUTED):
    draw.rounded_rectangle([x, y, x + s * 1.6, y + s * 1.2], radius=s * 0.45, outline=color, width=4)
    draw.polygon([(x + s * 0.35, y + s * 1.1), (x + s * 0.2, y + s * 1.55), (x + s * 0.75, y + s * 1.15)], fill=color)


def make_card(sub, title, flair, out_path, votes="99+", comments="99+"):
    f_sub = font("bold", 38)
    f_chan = font("regular", 30)
    f_title = font("bold", 60)
    f_flair = font("bold", 30)
    f_stat = font("bold", 34)
    f_avatar = font("bold", 40)

    scratch = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    title_lines = wrap(scratch, title, f_title, WIDTH - 2 * PAD)
    line_h = 74

    header_h = 96
    flair_h = 64 if flair else 0
    title_h = len(title_lines) * line_h
    footer_h = 80
    height = PAD + header_h + 24 + flair_h + title_h + 28 + footer_h + PAD - 20

    img = Image.new("RGBA", (WIDTH, height), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, WIDTH - 1, height - 1], radius=44, fill=CARD_BG)

    # header: avatar + subreddit + channel
    y = PAD
    av = 88
    d.ellipse([PAD, y, PAD + av, y + av], fill=ACCENT)
    d.text((PAD + av / 2, y + av / 2), "RT", font=f_avatar, fill="white", anchor="mm")
    d.text((PAD + av + 22, y + 6), f"r/{sub}", font=f_sub, fill=TEXT)
    d.text((PAD + av + 22, y + 52), f"Told by {CHANNEL}", font=f_chan, fill=MUTED)
    y += header_h + 24

    # flair pill
    if flair:
        tw = d.textlength(flair, font=f_flair)
        d.rounded_rectangle([PAD, y, PAD + tw + 40, y + 48], radius=24, fill=(255, 237, 228), outline=ACCENT, width=3)
        d.text((PAD + 20, y + 24), flair, font=f_flair, fill=ACCENT, anchor="lm")
        y += flair_h

    # title
    for ln in title_lines:
        d.text((PAD, y), ln, font=f_title, fill=TEXT)
        y += line_h
    y += 28

    # footer: votes + comments
    cy = y + 30
    arrow(d, PAD + 24, cy, 22, up=True)
    d.text((PAD + 64, cy), votes, font=f_stat, fill=MUTED, anchor="lm")
    vx = PAD + 64 + d.textlength(votes, font=f_stat) + 22
    arrow(d, vx + 22, cy, 22, up=False)
    bx = vx + 110
    bubble(d, bx, cy - 20, 26)
    d.text((bx + 58, cy), comments, font=f_stat, fill=MUTED, anchor="lm")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    img.save(out_path)
    return out_path


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Make a RedditTales336 title card PNG")
    p.add_argument("--sub", required=True, help="subreddit name without r/, e.g. AmItheAsshole")
    p.add_argument("--title", required=True, help="post title (bleep swear words yourself)")
    p.add_argument("--flair", default="", help='optional verdict/flair, e.g. "Not the A-hole"')
    p.add_argument("--out", default="title_card", help="file name without .png")
    p.add_argument("--votes", default="99+")
    p.add_argument("--comments", default="99+")
    a = p.parse_args()

    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(root, "assets", "title_cards", a.out + ".png")
    print("Saved:", make_card(a.sub, a.title, a.flair, out, a.votes, a.comments))
