#!/usr/bin/env python3
"""Generate CYPHER65 PWA icons and splash screens from code."""
import os
from PIL import Image, ImageDraw, ImageFont

OUT_DIR = os.path.dirname(os.path.abspath(__file__))

# Brand colors
BG = (4, 6, 10)
ACCENT = (0, 255, 159)
GRAD_START = (6, 214, 240)
GRAD_END = (0, 255, 159)
WHITE = (255, 255, 255)


def make_gradient(size, start, end):
    """Create a linear gradient image."""
    base = Image.new("RGB", size, end)
    draw = ImageDraw.Draw(base)
    for y in range(size[1]):
        ratio = y / max(size[1] - 1, 1)
        color = (
            int(start[0] * (1 - ratio) + end[0] * ratio),
            int(start[1] * (1 - ratio) + end[1] * ratio),
            int(start[2] * (1 - ratio) + end[2] * ratio),
        )
        draw.line([(0, y), (size[0], y)], fill=color)
    return base


# Cache the first available monospace font path so we don't open files repeatedly.
_FONT_PATH = None

def _resolve_font_path():
    global _FONT_PATH
    if _FONT_PATH is None:
        candidates = [
            "/System/Library/Fonts/Menlo.ttc",
            "/System/Library/Fonts/Monaco.dfont",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
            "/usr/share/fonts/truetype/freefont/FreeMono.ttf",
            "/Windows/Fonts/consola.ttf",
            "/Windows/Fonts/cour.ttf",
        ]
        for path in candidates:
            try:
                ImageFont.truetype(path, 12)
                _FONT_PATH = path
                break
            except Exception:
                continue
        if _FONT_PATH is None:
            _FONT_PATH = "__default__"
    return _FONT_PATH


def _find_font(size):
    """Return the first available monospace font for the current platform."""
    path = _resolve_font_path()
    if path == "__default__":
        return ImageFont.load_default()
    return ImageFont.truetype(path, size)


def fit_font(draw, text, width, font_path=None):
    """Find the largest font size that fits the text within width."""
    for size in range(500, 10, -5):
        font = _find_font(size) if font_path is None else ImageFont.truetype(font_path, size)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= width:
            return font
    return font


def draw_rounded_rect(draw, xy, radius, fill):
    draw.rounded_rectangle(xy, radius=radius, fill=fill)


def create_icon(size, maskable=False):
    img = Image.new("RGBA", (size, size), BG if not maskable else (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    radius = int(size * 0.2) if maskable else 0

    if maskable:
        # Gradient background with rounded corners
        grad = make_gradient((size, size), GRAD_START, GRAD_END)
        mask = Image.new("L", (size, size), 0)
        mdraw = ImageDraw.Draw(mask)
        mdraw.rounded_rectangle([(0, 0), (size, size)], radius=radius, fill=255)
        img.paste(grad, (0, 0), mask)
        # Inner dark rounded square
        pad = int(size * 0.1)
        mdraw2 = Image.new("L", (size, size), 0)
        mdraw2d = ImageDraw.Draw(mdraw2)
        mdraw2d.rounded_rectangle(
            [(pad, pad), (size - pad, size - pad)],
            radius=int(radius * 0.6),
            fill=255,
        )
        dark = Image.new("RGBA", (size, size), BG)
        img.paste(dark, (0, 0), mdraw2)
    else:
        draw.rectangle([(0, 0), (size, size)], fill=BG)

    # Draw "65" text
    font = fit_font(draw, "65", int(size * 0.7))
    bbox = draw.textbbox((0, 0), "65", font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (size - text_w) // 2
    y = (size - text_h) // 2 - int(size * 0.05)
    draw.text((x, y), "65", font=font, fill=ACCENT)
    return img


def create_splash(width, height):
    """Create a splash screen with centered logo and brand text."""
    img = Image.new("RGBA", (width, height), BG)
    draw = ImageDraw.Draw(img)

    # Logo size relative to screen
    logo_size = min(width, height) // 3
    logo = create_icon(logo_size, maskable=True)
    lx = (width - logo_size) // 2
    ly = (height - logo_size) // 2 - int(height * 0.08)
    img.paste(logo, (lx, ly), logo)

    # Brand text
    brand_text = "CYPHER65"
    font = fit_font(draw, brand_text, int(width * 0.8))
    bbox = draw.textbbox((0, 0), brand_text, font=font)
    text_w = bbox[2] - bbox[0]
    tx = (width - text_w) // 2
    ty = ly + logo_size + int(height * 0.04)
    draw.text((tx, ty), brand_text, font=font, fill=WHITE)

    # Tagline
    tag = "BITCOIN MINING COMMAND CENTER"
    tag_font = fit_font(draw, tag, int(width * 0.7))
    tbbox = draw.textbbox((0, 0), tag, font=tag_font)
    tag_w = tbbox[2] - tbbox[0]
    ttx = (width - tag_w) // 2
    tty = ty + int(height * 0.06)
    draw.text((ttx, tty), tag, font=tag_font, fill=(150, 150, 150))

    return img


def main():
    print("[icons] generating CYPHER65 PWA assets...")
    sizes = [16, 32, 72, 96, 128, 144, 152, 192, 384, 512]
    for s in sizes:
        create_icon(s).save(os.path.join(OUT_DIR, f"icon-{s}x{s}.png"), "PNG")
        print(f"[icons] icon-{s}x{s}.png")

    # Maskable icon
    create_icon(512, maskable=True).save(os.path.join(OUT_DIR, "maskable-icon-512x512.png"), "PNG")
    print("[icons] maskable-icon-512x512.png")

    # Apple touch icon
    create_icon(180, maskable=True).save(os.path.join(OUT_DIR, "apple-touch-icon.png"), "PNG")
    print("[icons] apple-touch-icon.png")

    # Favicon.ico multi-size (32x32 with embedded 16x16)
    fav32 = create_icon(32)
    fav16 = create_icon(16)
    fav32.save(
        os.path.join(OUT_DIR, "favicon.ico"),
        format="ICO",
        append_images=[fav16],
        sizes=[(32, 32), (16, 16)],
    )
    print("[icons] favicon.ico")

    # Splash screens
    for (w, h) in [(1024, 1024), (1125, 2436), (1242, 2688), (750, 1334), (828, 1792)]:
        create_splash(w, h).save(os.path.join(OUT_DIR, f"splash-{w}x{h}.png"), "PNG")
        print(f"[icons] splash-{w}x{h}.png")

    print("[icons] done")


if __name__ == "__main__":
    main()
