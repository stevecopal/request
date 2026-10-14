"""
Génère les icônes PWA (PNG) sans dépendance externe.

Dessine un carré navy arrondi avec un chapeau de diplômé blanc (diamant + base).
Sortie : static/icons/icon-192.png, icon-512.png, maskable-512.png

Usage : uv run python tools/generate_pwa_icons.py
"""

import struct
import zlib
from pathlib import Path

NAVY = (30, 58, 138)          # #1E3A8A
WHITE = (255, 255, 255)
TRANSPARENT = (0, 0, 0, 0)
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "static" / "icons"


def _write_png(path, width, height, pixels):
    """pixels : liste de tuples (r, g, b, a)."""

    def chunk(tag, data):
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    stride = width * 4
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filtre None
        row = pixels[y * width : (y + 1) * width]
        for pixel in row:
            raw.extend(pixel)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    data = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(data)


def _in_rounded_square(x, y, size, radius, maskable):
    """Vrai si (x, y) est dans le carré arrondi (ou plein si maskable)."""
    if maskable:
        return True

    far_x = size - 1 - radius
    if x < radius and y < radius:
        return (x - radius) ** 2 + (y - radius) ** 2 <= radius * radius
    if x > far_x and y < radius:
        return (x - far_x) ** 2 + (y - radius) ** 2 <= radius * radius
    if x < radius and y > far_x:
        return (x - radius) ** 2 + (y - far_x) ** 2 <= radius * radius
    if x > far_x and y > far_x:
        return (x - far_x) ** 2 + (y - far_x) ** 2 <= radius * radius
    return True


def _is_cap(x, y, size):
    """Chapeau de diplômé : diamant supérieur + base rectangulaire."""
    cx = size / 2
    cy = size * 0.44
    hw = size * 0.30
    hh = size * 0.17

    # Diamant (plateau du chapeau).
    if abs(x - cx) / hw + abs(y - cy) / hh <= 1.0:
        return True
    # Base (la coiffe sous le plateau).
    if (cx - hw * 0.55) <= x <= (cx + hw * 0.55) and (
        cy + hh * 0.55
    ) <= y <= (cy + hh * 1.15):
        return True
    # Pompon (petit carré à droite).
    if (cx + hw * 0.75) <= x <= (cx + hw * 0.95) and (cy - hh * 0.1) <= y <= (
        cy + hh * 0.35
    ):
        return True
    return False


def build_icon(size, maskable=False):
    radius = int(size * 0.22)
    pixels = []
    for y in range(size):
        for x in range(size):
            if not _in_rounded_square(x, y, size, radius, maskable):
                pixels.append(TRANSPARENT)
                continue
            if _is_cap(x, y, size):
                pixels.append(WHITE + (255,))
            else:
                pixels.append(NAVY + (255,))
    return pixels


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for size in (192, 512):
        _write_png(OUTPUT_DIR / f"icon-{size}.png", size, size, build_icon(size))
    _write_png(
        OUTPUT_DIR / "maskable-512.png", 512, 512, build_icon(512, maskable=True)
    )
    print("Icônes PWA générées dans", OUTPUT_DIR)


if __name__ == "__main__":
    main()
