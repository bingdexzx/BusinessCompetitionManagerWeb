"""从品牌原图重新生成网站图标（favicon.ico / 各尺寸 PNG）。

原图：BusinessCompetitionManagerWebFrontend/public/brand-logo.jpg（1280×1280，白底）
输出：public/favicon.ico、favicon-32.png、apple-touch-icon.png、icon-192.png、icon-512.png
      src/assets/logo.png（登录页/注册页/侧栏用）

按「非白内容」的包围盒重新居中，避免徽标在白色方块里偏左/偏右。

用法：
    python scripts/make_brand_icons.py
"""

from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / 'BusinessCompetitionManagerWebFrontend' / 'public'
ASSETS = ROOT / 'BusinessCompetitionManagerWebFrontend' / 'src' / 'assets'

# 盾牌徽标在原图中的大致区域（不含下方 "Gipfel" 文字）
CROP = (280, 150, 1040, 900)
PADDING_RATIO = 0.06


def centered_square(emblem: Image.Image) -> Image.Image:
    """按非白内容的包围盒裁剪并放到正方形白底中间。"""
    diff = ImageChops.difference(emblem, Image.new('RGB', emblem.size, 'white'))
    mask = diff.convert('L').point(lambda value: 255 if value > 8 else 0)
    bbox = mask.getbbox()
    if bbox:
        emblem = emblem.crop(bbox)
    side = max(emblem.size)
    padding = max(4, int(side * PADDING_RATIO))
    canvas = Image.new('RGB', (side + padding * 2, side + padding * 2), 'white')
    canvas.paste(emblem, ((canvas.width - emblem.width) // 2,
                          (canvas.height - emblem.height) // 2))
    return canvas


def main() -> None:
    source = Image.open(PUBLIC / 'brand-logo.jpg').convert('RGB')
    emblem = centered_square(source.crop(CROP))

    base = emblem.resize((512, 512), Image.LANCZOS)
    base.save(PUBLIC / 'icon-512.png')
    base.resize((192, 192), Image.LANCZOS).save(PUBLIC / 'icon-192.png')
    base.resize((180, 180), Image.LANCZOS).save(PUBLIC / 'apple-touch-icon.png')
    base.resize((32, 32), Image.LANCZOS).save(PUBLIC / 'favicon-32.png')
    base.save(PUBLIC / 'favicon.ico', sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])

    # 页面内图标（登录/注册/侧栏）
    base.save(ASSETS / 'logo.png')

    print('已生成图标与 src/assets/logo.png')


if __name__ == '__main__':
    main()
