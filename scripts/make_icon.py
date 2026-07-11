"""Ritar appens ikon (sjökortsstil med kompassros + texten RUNN) och sparar de
storlekar webben/hemskärmen behöver i docs/icons/.

    py -3 scripts/make_icon.py

Genererar favicon samt hemskärms-/PWA-ikoner. Kör om bara om du vill ändra ikonen.
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "icons"

SEA_TOP = (196, 226, 240)
SEA_BOTTOM = (140, 194, 222)
NAVY = (23, 56, 74)
RED = (192, 57, 43)
WHITE = (255, 255, 255)

MASTER = 1024  # ritas stort och skalas ned för skarpa kanter


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in (r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\Arialbd.ttf"):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.truetype("DejaVuSans-Bold.ttf", size)


def _star_points(cx, cy, r_long, r_short, start_deg=-90):
    pts = []
    for k in range(8):
        ang = math.radians(start_deg + k * 45)
        r = r_long if k % 2 == 0 else r_short
        pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return pts


def draw_icon() -> Image.Image:
    S = MASTER
    img = Image.new("RGB", (S, S), SEA_BOTTOM)
    draw = ImageDraw.Draw(img, "RGBA")

    # Sjö-gradient uppifrån och ner.
    for y in range(S):
        t = y / (S - 1)
        col = tuple(round(SEA_TOP[i] + (SEA_BOTTOM[i] - SEA_TOP[i]) * t) for i in range(3))
        draw.line([(0, y), (S, y)], fill=col)

    # Svaga djupkurvor (isobarer) för sjökortskänsla.
    for i, rr in enumerate((0.60, 0.72, 0.84)):
        bbox = [S * (0.5 - rr / 2), S * (0.42 - rr / 2), S * (0.5 + rr / 2), S * (0.42 + rr / 2)]
        draw.ellipse(bbox, outline=(255, 255, 255, 70), width=max(2, S // 220))

    cx, cy = S * 0.5, S * 0.42
    r_long, r_short = S * 0.30, S * 0.12

    # Kompassring.
    draw.ellipse(
        [cx - r_long * 1.12, cy - r_long * 1.12, cx + r_long * 1.12, cy + r_long * 1.12],
        outline=NAVY, width=max(3, S // 150),
    )

    # Kompassros (åttauddig stjärna).
    star = _star_points(cx, cy, r_long, r_short)
    draw.polygon(star, fill=NAVY)
    # Röd nordspets.
    north = star[0]
    nw, ne = star[7], star[1]
    draw.polygon([north, ne, (cx, cy), nw], fill=RED)
    # Vit mittpunkt.
    cr = S * 0.035
    draw.ellipse([cx - cr, cy - cr, cx + cr, cy + cr], fill=WHITE)

    # Nedre band med RUNN.
    band_h = int(S * 0.27)
    draw.rectangle([0, S - band_h, S, S], fill=NAVY)
    font = _font(int(band_h * 0.62))
    text = "RUNN"
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    tw, th = r - l, b - t
    draw.text(
        ((S - tw) / 2 - l, (S - band_h) + (band_h - th) / 2 - t),
        text, font=font, fill=WHITE,
    )
    return img


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    master = draw_icon()
    targets = {
        "icon-512.png": 512,       # PWA / Android
        "icon-192.png": 192,       # PWA / Android
        "apple-touch-icon.png": 180,  # iOS hemskärm
        "favicon-32.png": 32,      # webbläsarflik
        "favicon-16.png": 16,
    }
    for name, size in targets.items():
        master.resize((size, size), Image.LANCZOS).save(OUT_DIR / name)
        print(f"Skrev {OUT_DIR / name} ({size}x{size})")


if __name__ == "__main__":
    main()
