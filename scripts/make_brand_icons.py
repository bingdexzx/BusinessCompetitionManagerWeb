"""从品牌原图重新生成网站图标与页面 logo。

输出：
- public/favicon.ico（16/32/48/64，PNG 压缩，多尺寸分别渲染，避免缩放后贴边）
- public/favicon-32.png、apple-touch-icon.png、icon-192.png、icon-512.png
- src/assets/logo.png（登录/注册/侧栏）

所有尺寸都按「非白内容包围盒」居中，favicon 额外留 12% 边距，
保证 16px 标签页图标也不会顶到边。

用法：
    python scripts/make_brand_icons.py
"""

import io
import struct
from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / 'BusinessCompetitionManagerWebFrontend' / 'public'
ASSETS = ROOT / 'BusinessCompetitionManagerWebFrontend' / 'src' / 'assets'

CROP = (280, 150, 1040, 900)
FAVICON_SIZES = (16, 32, 48, 64)
FAVICON_PADDING = 0.12
PAGE_PADDING = 0.06


def centered_square(emblem: Image.Image, padding_ratio: float) -> Image.Image:
    """按非白内容的包围盒裁剪，并放到正方形白底正中。"""
    diff = ImageChops.difference(emblem, Image.new('RGB', emblem.size, 'white'))
    mask = diff.convert('L').point(lambda value: 255 if value > 8 else 0)
    bbox = mask.getbbox()
    if bbox:
        emblem = emblem.crop(bbox)
    side = max(emblem.size)
    padding = max(1, round(side * padding_ratio))
    canvas = Image.new('RGB', (side + padding * 2, side + padding * 2), 'white')
    canvas.paste(emblem, ((canvas.width - emblem.width) // 2,
                          (canvas.height - emblem.height) // 2))
    return canvas


def save_ico(path: Path, frames: list[Image.Image]) -> None:
    """把多张 PNG 帧写成 ICO（Vista+ 支持 PNG 压缩帧）。"""
    header = struct.pack('<HHH', 0, 1, len(frames))
    entries = b''
    data = b''
    offset = 6 + 16 * len(frames)
    for frame in frames:
        buffer = io.BytesIO()
        frame.save(buffer, format='PNG')
        png = buffer.getvalue()
        width = 0 if frame.width >= 256 else frame.width
        height = 0 if frame.height >= 256 else frame.height
        entries += struct.pack('<BBBBHHII', width, height, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
        data += png
    path.write_bytes(header + entries + data)


def main() -> None:
    source = Image.open(PUBLIC / 'brand-logo.jpg').convert('RGB')
    emblem = source.crop(CROP)

    # 页面 logo：6% 边距
    page = centered_square(emblem, PAGE_PADDING).resize((512, 512), Image.LANCZOS)
    page.save(ASSETS / 'logo.png')
    page.save(PUBLIC / 'icon-512.png')
    page.resize((192, 192), Image.LANCZOS).save(PUBLIC / 'icon-192.png')
    page.resize((180, 180), Image.LANCZOS).save(PUBLIC / 'apple-touch-icon.png')

    # favicon：逐尺寸计算整数边距，保证 16px 也严格居中（不留 1px 偏差）
    content = centered_square(emblem, 0.0)
    frames = []
    for size in FAVICON_SIZES:
        pad = max(1, round(size * FAVICON_PADDING))
        inner = size - pad * 2
        frame = Image.new('RGB', (size, size), 'white')
        frame.paste(content.resize((inner, inner), Image.LANCZOS), (pad, pad))
        frames.append(frame)
    save_ico(PUBLIC / 'favicon.ico', frames)
    frames[FAVICON_SIZES.index(32)].save(PUBLIC / 'favicon-32.png')

    print('已生成 favicon（16/32/48/64）与页面 logo')


if __name__ == '__main__':
    main()
