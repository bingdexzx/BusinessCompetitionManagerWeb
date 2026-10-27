"""压测结果总览图（Pillow 绘制，无第三方图表库依赖）。

数据来源：docs/压测验收报告.md（2026-10，18 逻辑核 / 15.4GB 本机实测）。
重新出图：.venv\\Scripts\\python.exe scripts\\make_perf_chart.py   （或用带 Pillow 的 Python）
输出：docs/压测结果总览.png
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   'docs', '压测结果总览.png')

W, H = 1680, 1180
BG = '#ffffff'
PANEL_BG = '#f8fafc'
PANEL_BORDER = '#e2e8f0'
BLUE = '#2563eb'
GREEN = '#16a34a'
AMBER = '#f59e0b'
RED = '#dc2626'
GRAY = '#64748b'
DARK = '#0f172a'

FONT_DIR = r'C:\Windows\Fonts'


def fnt(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = 'msyhbd.ttc' if bold else 'msyh.ttc'
    return ImageFont.truetype(os.path.join(FONT_DIR, name), size)


img = Image.new('RGB', (W, H), BG)
d = ImageDraw.Draw(img)


def dashed_vline(x: int, y0: int, y1: int, color, dash: int = 8, gap: int = 6, width: int = 2):
    y = y0
    while y < y1:
        d.line([x, y, x, min(y + dash, y1)], fill=color, width=width)
        y += dash + gap


def panel(px: int, py: int, pw: int, ph: int, title: str, subtitle: str = '') -> tuple:
    d.rounded_rectangle([px, py, px + pw, py + ph], radius=14, fill=PANEL_BG, outline=PANEL_BORDER, width=2)
    d.text((px + 24, py + 22), title, font=fnt(21, True), fill=DARK, anchor='lm')
    if subtitle:
        d.text((px + 24, py + 52), subtitle, font=fnt(14), fill=GRAY, anchor='lm')
    return (px + 24, py + 80, px + pw - 24, py + ph - 24)   # 画布区域


def axes(box, xmax: float, ymax: float, xlabels, ylabels, ytitle: str = ''):
    """画坐标轴与网格，返回数据区与坐标映射函数。"""
    x0, y0, x1, y1 = box
    plot = (x0 + 70, y0 + 10, x1 - 20, y1 - 56)
    px0, py0, px1, py1 = plot

    def sx(v):
        return px0 + (px1 - px0) * v / xmax

    def sy(v):
        return py1 - (py1 - py0) * v / ymax

    for val in ylabels:
        y = sy(val)
        d.line([px0, y, px1, y], fill=PANEL_BORDER, width=1)
        d.text((px0 - 10, y), f'{val:g}', font=fnt(13), fill=GRAY, anchor='rm')
    d.line([px0, py1, px1, py1], fill=GRAY, width=2)
    d.line([px0, py0, px0, py1], fill=GRAY, width=2)
    n = len(xlabels)
    for i, lab in enumerate(xlabels):
        x = px0 + (px1 - px0) * (i + 0.5) / n
        d.text((x, py1 + 12), lab, font=fnt(13), fill=DARK, anchor='ma')
    if ytitle:
        d.text((px0 - 58, py0 - 6), ytitle, font=fnt(12), fill=GRAY, anchor='lm')
    return plot, sx, sy


# ================================================================ 页眉
d.text((40, 34), '后端压测结果总览 —— 多核 / 股票同步 / 合同管理', font=fnt(34, True), fill=DARK, anchor='lm')
d.text((40, 78), 'perf-loadtest-db-opt 方法论验收（2026-10，18 逻辑核 / 15.4GB，PostgreSQL max_connections=200）',
       font=fnt(16), fill=GRAY, anchor='lm')
d.line([40, 104, W - 40, 104], fill=PANEL_BORDER, width=2)

# ================================================================ A. 多核扩展性
box = panel(40, 126, 780, 430, 'A. 多核扩展性（闭环 /api/health）',
            '吞吐随 worker 近线性；12 worker 时整机 CPU 95.7% 饱和（测试台下限）')
plot, sx, sy = axes(box, 4, 4500, ['1 worker', '2 workers', '4 workers', '12 workers'],
                    [0, 1000, 2000, 3000, 4000], 'QPS')
a_vals = [1077, 2211, 4006, 4250]
a_colors = [BLUE, BLUE, BLUE, GRAY]
for i, (v, c) in enumerate(zip(a_vals, a_colors)):
    bx0 = sx(i) + 22
    bx1 = sx(i + 1) - 22
    d.rectangle([bx0, sy(v), bx1, sy(0)], fill=c)
    d.text(((bx0 + bx1) / 2, sy(v) - 10), f'{v:,}', font=fnt(15, True), fill=DARK, anchor='mb')
d.text((sx(3) + (sx(4) - sx(3)) / 2, sy(4250) + 26), '测试台饱和（下限）', font=fnt(13), fill='#e2e8f0', anchor='ma')
d.text((plot[0] + 10, plot[1] + 6), '加速比：2 worker 2.05× / 4 worker 3.72×，错误 0',
       font=fnt(14), fill=GREEN, anchor='la')

# ================================================================ B. 真实节奏延迟
box = panel(860, 126, 780, 430, 'B. 真实节奏热路径延迟（think=1.5s）',
            '柱=P95，点=P50；目标线：股票域 P95<200ms、合同域 P95<400ms（全部达标）')
plot, sx, sy = axes(box, 9, 160,
                    ['股sync', '股stocks', '股book', '合50\nlist', '合50\ndetail', '合50\nsync',
                     '合100\nlist', '合100\ndetail', '合100\nsync'],
                    [0, 40, 80, 120, 160], 'ms')
b_p95 = [69.2, 64.4, 34.3, 66.2, 95.5, 42.4, 106.4, 148.7, 83.0]
b_p50 = [26.5, 17.0, 15.9, 21.0, 20.7, 12.4, 18.9, 20.3, 12.7]
for i, (p95, p50) in enumerate(zip(b_p95, b_p50)):
    bx0 = sx(i) + 16
    bx1 = sx(i + 1) - 16
    color = BLUE if i < 3 else GREEN
    d.rectangle([bx0, sy(p95), bx1, sy(0)], fill=color)
    cy = sy(p50)
    d.ellipse([bx0 + 8, cy - 5, bx1 - 8, cy + 5], fill=AMBER)
    d.text(((bx0 + bx1) / 2, sy(p95) - 8), f'{p95:.0f}', font=fnt(13, True), fill=DARK, anchor='mb')
d.rectangle([plot[0] + 12, plot[1] + 4, plot[0] + 32, plot[1] + 20], fill=BLUE)
d.text((plot[0] + 38, plot[1] + 12), '股票域 P95', font=fnt(13), fill=DARK, anchor='lm')
d.rectangle([plot[0] + 150, plot[1] + 4, plot[0] + 170, plot[1] + 20], fill=GREEN)
d.text((plot[0] + 176, plot[1] + 12), '合同域 P95', font=fnt(13), fill=DARK, anchor='lm')
d.ellipse([plot[0] + 288, plot[1] + 8, plot[0] + 300, plot[1] + 20], fill=AMBER)
d.text((plot[0] + 306, plot[1] + 12), 'P50', font=fnt(13), fill=DARK, anchor='lm')

# ================================================================ C. 合同域拐点
box = panel(40, 576, 780, 430, 'C. 合同管理域：吞吐 vs 延迟（拐点）',
            '2000 合同 × 20 公司；吞吐封顶 ≈770 QPS，200 并发后纯排队（延迟≈并发/吞吐）')
plot, sx, sy = axes(box, 4, 900,
                    ['50 管理员\n真实节奏', '100 管理员\n真实节奏', '50 管理员\n闭环', '200 管理员\n闭环'],
                    [0, 200, 400, 600, 800], 'QPS（柱）')
c_qps = [97.5, 194.2, 776.0, 766.0]
c_p50 = [21.0, 18.9, 64.1, 262.2]
for i, v in enumerate(c_qps):
    bx0 = sx(i) + 34
    bx1 = sx(i + 1) - 34
    d.rectangle([bx0, sy(v), bx1, sy(0)], fill=BLUE if i < 2 else GREEN)
    d.text(((bx0 + bx1) / 2, sy(v) - 10), f'{v:.0f}', font=fnt(15, True), fill=DARK, anchor='mb')
# 延迟折线（右轴 0-300ms）
def sy2(v):
    return plot[3] - (plot[3] - plot[1]) * v / 300

pts = []
for i, p in enumerate(c_p50):
    pts.append((sx(i) + (sx(i + 1) - sx(i)) / 2, sy2(p)))
for a, b in zip(pts, pts[1:]):
    d.line([a, b], fill=RED, width=3)


def label_with_bg(x, y, text, anchor, fill=RED):
    """带白色底衬的标注，避免压在柱子上看不清。"""
    bbox = d.textbbox((x, y), text, font=fnt(13, True), anchor=anchor)
    pad = 4
    d.rounded_rectangle([bbox[0] - pad, bbox[1] - pad, bbox[2] + pad, bbox[3] + pad],
                        radius=6, fill='#ffffff')
    d.text((x, y), text, font=fnt(13, True), fill=fill, anchor=anchor)


for idx, ((x, y), p) in enumerate(zip(pts, c_p50)):
    d.ellipse([x - 6, y - 6, x + 6, y + 6], fill=RED)
    if idx == 3:
        label_with_bg(x - 12, y + 4, f'P50 {p:.0f}ms', 'rm')
    else:
        label_with_bg(x + 12, y - 4, f'P50 {p:.0f}ms', 'lm')
d.text((plot[0] + 10, plot[1] + 8), '红线 = P50 延迟（右轴 0–300ms）', font=fnt(13), fill=RED, anchor='la')

# ================================================================ D. 容量余量
box = panel(860, 576, 780, 430, 'D. 容量余量（真实负载 vs 容量）',
            '目标余量 ≥2×；实际 4×–12×（容量为同机自压自测下限）')
x0, y0, x1, y1 = box
px0, py0, px1, py1 = x0 + 150, y0 + 30, x1 - 130, y1 - 46   # 右侧留倍数列
rows = [
    ('股票同步（60 账号）', 50.9, 626.0, '12.3×'),
    ('合同管理（50 管理员）', 97.5, 776.0, '8.0×'),
    ('合同管理（100 管理员）', 194.2, 776.0, '4.0×'),
]
row_h = (py1 - py0) / len(rows)
for i, (name, real, cap, mult) in enumerate(rows):
    cy = py0 + row_h * i
    d.text((px0 - 14, cy + row_h * 0.28), name, font=fnt(15, True), fill=DARK, anchor='rm')

    def bx(v):
        return px0 + (px1 - px0) * v / 800

    d.rectangle([px0, cy + 8, bx(cap), cy + 34], fill=GREEN)
    d.text((bx(cap) - 12, cy + 21), f'容量 {cap:.0f} QPS', font=fnt(14, True), fill='#ffffff', anchor='rm')
    d.rectangle([px0, cy + 46, bx(real), cy + 72], fill=BLUE)
    d.text((bx(real) + 10, cy + 59), f'真实 {real:.1f} QPS', font=fnt(14, True), fill=BLUE, anchor='lm')
    d.text((x1 - 20, cy + 40), mult, font=fnt(22, True), fill=AMBER, anchor='rm')
d.text((px0, py1 + 14), '横轴：QPS', font=fnt(13), fill=GRAY, anchor='la')

# ================================================================ 页脚结论
d.rounded_rectangle([40, 1026, W - 40, 1152], radius=14, fill='#eff6ff', outline='#bfdbfe', width=2)
d.text((64, 1050), '结论：', font=fnt(18, True), fill=DARK, anchor='lm')
lines = [
    '1) 多核改造后吞吐随 worker 近线性（1→4 worker 3.72×）；股票 60 账号、合同 50/100 管理员真实节奏全部达标、错误 0。',
    '2) 容量：股票 626 QPS（余量 12×）、合同 776 QPS（余量 8×/4×）；拐点 200 并发管理员后纯排队，P95 顶到 400ms 目标线。',
    '3) 两次踩坑已固化为约束：连接预算 workers×threads×2+20 ≤ max_connections（启动器自检）；背压额度按 worker 分摊防尾延迟。',
]
for i, t in enumerate(lines):
    d.text((64, 1082 + i * 26), t, font=fnt(15), fill=DARK, anchor='lm')

os.makedirs(os.path.dirname(OUT), exist_ok=True)
img.save(OUT)
print('saved:', OUT)
