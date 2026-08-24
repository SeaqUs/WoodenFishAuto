"""make_icon.py — 用 Pillow 绘制木鱼图标，生成 icon.ico 与 icon.png。"""
from PIL import Image, ImageDraw


def make_icon(size=256):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    m = size // 12  # 边距单位

    # 木鱼身体：略扁的圆，居中偏下，给顶部开口留空间
    cx = size // 2
    cy = size // 2 + m
    rx = size // 2 - 2 * m
    ry = int(rx * 0.88)
    body = (cx - rx, cy - ry, cx + rx, cy + ry)

    # 底部轮廓（深棕）
    d.ellipse((body[0], body[1] + 4, body[2], body[3] + 6), fill=(78, 47, 22, 255))
    # 主体（暖棕）
    d.ellipse(body, fill=(158, 98, 46, 255))
    # 高光（左上偏亮）
    d.ellipse(
        (cx - rx + 22, cy - ry + 20, cx - rx + 74, cy - ry + 66),
        fill=(196, 133, 72, 255),
    )
    d.ellipse(
        (cx - rx + 30, cy - ry + 28, cx - rx + 52, cy - ry + 48),
        fill=(216, 158, 96, 255),
    )

    # 顶部开口槽（木鱼的"嘴"）
    sw = int(rx * 0.92)
    sh = int(ry * 0.52)
    slot_top = cy - ry - sh // 2 + 6
    d.rounded_rectangle(
        (cx - sw, slot_top, cx + sw, slot_top + sh),
        radius=sh // 2,
        fill=(58, 35, 16, 255),
    )
    # 槽内深缝
    d.rounded_rectangle(
        (cx - sw + 14, slot_top + 14, cx + sw - 14, slot_top + sh - 8),
        radius=12,
        fill=(28, 16, 7, 255),
    )

    # 木鱼锤（斜放的小木槌）
    sx1 = cx + rx + 6
    sy1 = cy - ry + 4
    sx2 = cx + rx - 42
    sy2 = cy + ry + 14
    d.line((sx1, sy1, sx2, sy2), fill=(120, 72, 34, 255), width=16)
    # 锤头（圆球）
    d.ellipse((sx1 - 10, sy1 - 24, sx1 + 18, sy1 + 4), fill=(172, 112, 58, 255))
    d.ellipse((sx1 - 4, sy1 - 18, sx1 + 10, sy1 - 4), fill=(200, 140, 82, 255))

    return img


if __name__ == "__main__":
    img = make_icon(256)
    img.save("icon.ico", format="ICO", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    img.save("icon.png")
    print("已生成 icon.ico 和 icon.png")
