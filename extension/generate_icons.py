"""
Script pour générer les icônes de l'extension Chrome.
Usage : python generate_icons.py
Requiert : Pillow (pip install Pillow)
"""

from pathlib import Path

from PIL import Image, ImageDraw

SIZES = [16, 32, 48, 128]
OUT_DIR = Path(__file__).parent / "icons"
OUT_DIR.mkdir(exist_ok=True)

BG_COLOR = (99, 102, 241)       # --accent indigo
BAR_COLOR = (255, 255, 255)     # blanc
BAR_DARK = (180, 182, 245)      # blanc cassé pour variation


def draw_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Fond arrondi
    radius = max(2, size // 6)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=BG_COLOR)

    # Mini bar-chart centré
    pad = max(2, size // 8)
    chart_x = pad
    chart_y = pad
    chart_w = size - pad * 2
    chart_h = size - pad * 2

    # 3 barres de hauteurs croissantes
    n_bars = 3
    gap = max(1, chart_w // 10)
    bar_w = (chart_w - gap * (n_bars - 1)) // n_bars
    heights = [0.4, 0.65, 1.0]  # relatives

    for i, rel_h in enumerate(heights):
        bh = int(chart_h * rel_h)
        bx = chart_x + i * (bar_w + gap)
        by = chart_y + chart_h - bh
        color = BAR_DARK if i < n_bars - 1 else BAR_COLOR
        draw.rectangle([bx, by, bx + bar_w - 1, chart_y + chart_h - 1], fill=color)

    return img


for size in SIZES:
    icon = draw_icon(size)
    out_path = OUT_DIR / f"icon{size}.png"
    icon.save(out_path, "PNG")
    print(f"  Generated {out_path.name} ({size}×{size})")

print(f"\nIcônes générées dans : {OUT_DIR}")
