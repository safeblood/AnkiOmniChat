# -*- coding: utf-8 -*-
"""
抓帧后用颜色聚类定位网页内的可点击控件（发送按钮 / 输入框）。

用途：WebView 内部的控件 UIA 看不到，只能靠像素特征定位。
DeepSeek 的发送按钮是蓝色 (#4D6BFE) 圆形/圆角按钮，位于输入框右侧。
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from PIL import Image  # noqa: E402


def analyze(path, panel_left=1260):
    im = Image.open(path).convert("RGB")
    W, H = im.size
    px = im.load()
    print("图像尺寸 %dx%d，面板区域 x>=%d" % (W, H, panel_left))

    # 1) 蓝色主导像素（发送按钮候选）
    blue = []
    for y in range(0, H, 2):
        for x in range(panel_left, W, 2):
            r, g, b = px[x, y]
            if b > 150 and b - r > 60 and b - g > 40:
                blue.append((x, y))
    if blue:
        xs = [p[0] for p in blue]
        ys = [p[1] for p in blue]
        print("蓝色像素 %d 个，范围 x:%d-%d y:%d-%d" % (len(blue), min(xs), max(xs), min(ys), max(ys)))
        # 按 y 分桶找密度最高的簇
        buckets = {}
        for x, y in blue:
            buckets.setdefault(y // 20 * 20, []).append((x, y))
        top = sorted(buckets.items(), key=lambda kv: -len(kv[1]))[:5]
        for yb, pts in top:
            xs2 = [p[0] for p in pts]
            ys2 = [p[1] for p in pts]
            print("  候选簇 y≈%d 中心=(%d,%d) 点数=%d 宽=%d" % (
                yb, sum(xs2) // len(xs2), sum(ys2) // len(ys2), len(pts), max(xs2) - min(xs2)))
    else:
        print("未找到蓝色像素（可能未登录或主题不同）")

    # 2) 面板区域的水平"分隔线"：用于推断网页/输入框边界
    print("--- 面板内明显的横向边界（整行颜色突变）---")
    prev = None
    edges = []
    for y in range(120, H - 1, 1):
        row = [px[x, y] for x in range(panel_left + 20, W - 40, 40)]
        avg = tuple(sum(c[i] for c in row) // len(row) for i in range(3))
        if prev and abs(avg[0] - prev[0]) + abs(avg[1] - prev[1]) + abs(avg[2] - prev[2]) > 60:
            edges.append((y, avg))
        prev = avg
    for y, avg in edges[:25]:
        print("  y=%d  avg_rgb=%s" % (y, avg))


if __name__ == "__main__":
    p = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "_cap.png")
    left = int(sys.argv[2]) if len(sys.argv) > 2 else 1260
    analyze(p, left)
