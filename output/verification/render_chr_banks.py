from pathlib import Path
from PIL import Image, ImageDraw

rom = Path(r"C:\Users\hu\Downloads\测试.nes").read_bytes()
base = 0x80010
out = Path(r"D:\GIT\mmc3\output\verification")
palette = [(0, 0, 0), (100, 100, 100), (190, 190, 190), (255, 255, 255)]

for bank in (0x00, 0x01, 0x02, 0x14, 0xA2):
    image = Image.new("RGB", (256, 256), "#202020")
    draw = ImageDraw.Draw(image)
    for tile in range(64):
        start = base + bank * 0x400 + tile * 16
        data = rom[start:start + 16]
        x = (tile % 8) * 32
        y = (tile // 8) * 32
        for py in range(8):
            plane0, plane1 = data[py], data[py + 8]
            for px in range(8):
                value = ((plane0 >> (7 - px)) & 1) | (((plane1 >> (7 - px)) & 1) << 1)
                color = palette[value]
                image.paste(color, (x + px * 3, y + py * 3, x + px * 3 + 3, y + py * 3 + 3))
        draw.text((x, y), f"{tile:02X}", fill=(255, 0, 0))
    image.save(out / f"chr-bank-{bank:02X}.png")
