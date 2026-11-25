"""从品牌原图重新生成网站图标（favicon.ico / 各尺寸 PNG）。

原图：BusinessCompetitionManagerWebFrontend/public/brand-logo.jpg（1280×1280，白底）
输出：public/favicon.ico、favicon-32.png、apple-touch-icon.png、icon-192.png、icon-512.png

用法：
    python scripts/make_brand_icons.py
"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / 'BusinessCompetitionManagerWebFrontend' / 'public'

# 盾牌徽标在原图中的位置（去掉下方 "Gipfel" 文字，保留一点留白）
CROP = (300, 170, 1030, 890)


def main() -> None:
    source = Image.open(PUBLIC / 'brand-logo.jpg').convert('RGB')

    emblem = source.crop(CROP)
    side = max(emblem.size)
    padding = int(side * 0.08)
    canvas = Image.new('RGB', (side + padding * 2, side + padding * 2), 'white')
    canvas.paste(
        emblem,
        ((canvas.width - emblem.width) // 2, (canvas.height - emblem.height) // 2),
    )

    base = canvas.resize((512, 512), Image.LANCZOS)
    base.save(PUBLIC / 'icon-512.png')
    base.resize((192, 192), Image.LANCZOS).save(PUBLIC / 'icon-192.png')
    base.resize((180, 180), Image.LANCZOS).save(PUBLIC / 'apple-touch-icon.png')
    base.resize((32, 32), Image.LANCZOS).save(PUBLIC / 'favicon-32.png')
    base.save(PUBLIC / 'favicon.ico', sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])

    print('已生成：', ', '.join(sorted(p.name for p in PUBLIC.glob('*icon*'))))


if __name__ == '__main__':
    main()
