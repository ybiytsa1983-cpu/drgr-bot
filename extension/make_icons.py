"""
make_icons.py – генерирует PNG-иконки для браузерного расширения DRGR Bot.

Запуск из корня проекта или из папки extension/:
    python extension/make_icons.py

Требует: Pillow (уже в requirements.txt).
Создаёт: extension/icons/icon16.png  icon48.png  icon128.png
"""

import math
import os
import sys

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    sys.exit("Pillow не установлен. Выполните: pip install pillow")

# ── папка для иконок ──────────────────────────────────────────────────────────

script_dir = os.path.dirname(os.path.abspath(__file__))
icons_dir  = os.path.join(script_dir, "icons")
os.makedirs(icons_dir, exist_ok=True)


def make_icon(size: int) -> Image.Image:
    """Рисует логотип DRGR Bot размером size×size пикселей."""
    img  = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # --- фон: скруглённый прямоугольник -----------------------------------
    r  = max(3, size // 6)
    bg = (30, 30, 60, 255)       # тёмно-синий
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=bg)

    # --- обводка -----------------------------------------------------------
    accent = (233, 69, 96, 255)  # красно-розовый
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=r,
                            outline=accent, width=max(1, size // 20))

    # --- буква «D» по центру -----------------------------------------------
    font_size = int(size * 0.58)
    font = None
    for fname in ("segoeui.ttf", "arial.ttf", "DejaVuSans-Bold.ttf",
                  "LiberationSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(fname, font_size)
            break
        except (IOError, OSError):
            pass
    if font is None:
        try:
            font = ImageFont.load_default(size=font_size)
        except TypeError:
            font = ImageFont.load_default()

    text = "D"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw   = bbox[2] - bbox[0]
    th   = bbox[3] - bbox[1]
    tx   = (size - tw) // 2 - bbox[0]
    ty   = (size - th) // 2 - bbox[1]
    draw.text((tx, ty), text, fill=(233, 69, 96, 255), font=font)

    # --- маленькая точка-индикатор (онлайн) в правом нижнем углу ----------
    if size >= 32:
        dot_r = max(2, size // 12)
        cx    = size - dot_r - max(1, size // 16)
        cy    = size - dot_r - max(1, size // 16)
        draw.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r],
                     fill=(76, 175, 80, 255))

    return img


for sz in (16, 48, 128):
    img  = make_icon(sz)
    path = os.path.join(icons_dir, f"icon{sz}.png")
    img.save(path, "PNG")
    print(f"  Создан: {path}")

print("\nИконки готовы. Теперь можно установить расширение в браузере.")
print("Инструкция: README.md → раздел «Браузерное расширение»")
