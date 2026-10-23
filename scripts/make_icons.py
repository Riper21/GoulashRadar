"""Generate extension icons: radar rings in two brand palettes.
  default (lifemart): white bg, dark-green rings (#016048), accent green (#3F9E37)
  goulash:            dark bg (#222222), cyan rings (#00FFFF), green accent (#B1EC52)
Run: py -X utf8 scripts/make_icons.py
"""
import math
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).parent.parent / "extension" / "icons"


def png_chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def build_png(size: int, theme: str = "lifemart") -> None:
    px = bytearray()
    if theme == "lifemart":
        bg = (255, 255, 255)     # #FFFFFF
        ring = (1, 96, 72)       # #016048
        accent = (63, 158, 55)   # #3F9E37
        dot = (1, 96, 72)        # #016048
        prefix = "icon"
    else:
        bg = (34, 34, 34)        # #222222
        ring = (0, 255, 255)     # #00FFFF
        accent = (0, 214, 214)   # #00D6D6
        dot = (177, 236, 82)     # #B1EC52
        prefix = "icon_goulash"
    c = size / 2
    rings = [0.22, 0.36, 0.50]
    beam_half = 0.14

    for y in range(size):
        px.append(0)  # filter byte per row
        for x in range(size):
            dx, dy = x - c + 0.5, y - c + 0.5
            d = (dx * dx + dy * dy) ** 0.5 / (size / 2)  # 0..1 from center
            r, g, b = bg
            # rings
            for ri, rr in enumerate(rings):
                if abs(d - rr) < 0.045:
                    col = ring if ri < 2 else accent
                    r, g, b = col
            # center dot
            if d < 0.09:
                r, g, b = dot
            # radar beam (wedge up-right)
            ang = math.atan2(-dy, dx) % (2 * math.pi)  # 0 = right, up is positive
            if 0.1 < d < 0.5 and (ang < beam_half or ang > 2 * math.pi - beam_half):
                r, g, b = accent
            px.extend((r, g, b))

    raw = bytes(px)
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", ihdr) + png_chunk(b"IDAT", zlib.compress(raw)) + png_chunk(b"IEND", b"")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{prefix}{size}.png").write_bytes(png)
    print(f"{prefix}{size}.png written ({len(png)} bytes)")


if __name__ == "__main__":
    for s in (16, 48, 128):
        build_png(s, "lifemart")
        build_png(s, "goulash")
