# -*- coding: utf-8 -*-
"""
驱动 Anki 完成演示动作（供录屏用）。

只读模式（dump / find）不激活窗口；执行模式（run）会短暂把 Anki 提到前台，
因为真实的键盘/鼠标输入必须发给前台窗口才有效。

用法：
    python _drive.py dump                       # 打印控件树（不激活窗口）
    python _drive.py find 开始                  # 按名字/类型搜控件
    python _drive.py shot                       # 抓一帧存 _drive_shot.png
    python _drive.py diff --wait 2              # 抓两帧对比，输出变化最大的区域
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _capture  # noqa: E402

from pywinauto import Application  # noqa: E402
from pywinauto.controls.uiawrapper import UIAWrapper  # noqa: E402

TITLE = "837731400@qq.com - Anki"
HWND = None


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def find_hwnd():
    import ctypes
    import ctypes.wintypes as wt
    U = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(hwnd, _lp):
        if not U.IsWindowVisible(hwnd):
            return True
        n = U.GetWindowTextLengthW(hwnd)
        if not n:
            return True
        buf = ctypes.create_unicode_buffer(n + 2)
        U.GetWindowTextW(hwnd, buf, n + 2)
        if TITLE.lower() in buf.value.lower():
            found.append(hwnd)
        return True

    U.EnumWindows(cb, 0)
    return found[0] if found else None


def connect():
    global HWND
    HWND = find_hwnd()
    if not HWND:
        log("找不到 Anki 窗口")
        sys.exit(2)
    app = Application(backend="uia").connect(handle=HWND)
    return app.window(handle=HWND)


def walk(el, out, depth=0, maxdepth=14):
    if depth > maxdepth:
        return
    try:
        r = el.rectangle()
        rect = (r.left, r.top, r.right, r.bottom)
    except Exception:
        return
    try:
        ct = el.element_info.control_type
    except Exception:
        ct = "?"
    try:
        name = (el.window_text() or "").replace("\n", " ")[:70]
    except Exception:
        name = ""
    out.append((depth, ct, name, rect, el))
    try:
        kids = el.children()
    except Exception:
        return
    for k in kids:
        walk(k, out, depth + 1, maxdepth)


def cmd_dump(a):
    w = connect()
    out = []
    walk(w, out)
    log("共 %d 个控件（hwnd=%s）" % (len(out), HWND))
    for depth, ct, name, rect, _el in out:
        if a.all or (name.strip() and rect[2] - rect[0] > 0):
            print("%s%-14s %-52s (%d,%d)-(%d,%d)"
                  % ("  " * depth, ct, name, rect[0], rect[1], rect[2], rect[3]))


def cmd_find(a):
    w = connect()
    out = []
    walk(w, out)
    log("搜索 %r" % a.pat)
    for depth, ct, name, rect, _el in out:
        blob = (name + " " + ct).lower()
        if a.pat.lower() in blob:
            print("%s%-14s %-52s (%d,%d)-(%d,%d)"
                  % ("  " * depth, ct, name, rect[0], rect[1], rect[2], rect[3]))


def cmd_shot(a):
    hwnd = find_hwnd()
    res = _capture.grab(hwnd)
    w, h, data, m = res
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_drive_shot.png")
    _capture.save(p, w, h, data)
    st = _capture.color_stats(w, h, data)
    log("%s %dx%d  颜色数=%d 非白=%.3f -> %s" % (m, w, h, st["colors"], st["non_white_ratio"], p))


def cmd_diff(a):
    """抓两帧，找出变化最集中的区域 —— 用来定位「刚刚内容出现/改变」的地方。"""
    hwnd = find_hwnd()
    r1 = _capture.grab(hwnd)
    log("第一帧已抓，等待 %.1fs ..." % a.wait)
    time.sleep(a.wait)
    r2 = _capture.grab(hwnd)
    w, h, d1, _ = r1
    _w, _h, d2, _ = r2
    GX, GY = 24, 16
    grid = [[0] * GX for _ in range(GY)]
    for gy in range(GY):
        for gx in range(GX):
            x0, x1 = gx * w // GX, (gx + 1) * w // GX
            y0, y1 = gy * h // GY, (gy + 1) * h // GY
            cnt = tot = 0
            for y in range(y0, y1, 4):
                for x in range(x0, x1, 4):
                    i = (y * w + x) * 4
                    if (abs(d1[i] - d2[i]) > 16 or abs(d1[i + 1] - d2[i + 1]) > 16
                            or abs(d1[i + 2] - d2[i + 2]) > 16):
                        cnt += 1
                    tot += 1
            grid[gy][gx] = cnt / max(1, tot)
    log("变化热力图（%% 像素变化，GX=%d GY=%d）:" % (GX, GY))
    for gy in range(GY):
        row = "".join("%4d" % int(grid[gy][gx] * 999) for gx in range(GX))
        print("y=%4d %s" % (gy * h // GY, row))
    best = max(((grid[gy][gx], gx, gy) for gy in range(GY) for gx in range(GX)))
    cw, ch = w // GX, h // GY
    log("变化最集中格: 比例=%.2f 区域=(%d,%d)-(%d,%d)"
        % (best[0], best[1] * cw, best[2] * ch, (best[1] + 1) * cw, (best[2] + 1) * ch))


def main():
    p = argparse.ArgumentParser(description="驱动 Anki 完成演示动作")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("dump")
    sp.add_argument("--all", action="store_true")
    sp.set_defaults(func=cmd_dump)

    sp = sub.add_parser("find")
    sp.add_argument("pat")
    sp.set_defaults(func=cmd_find)

    sub.add_parser("shot").set_defaults(func=cmd_shot)

    sp = sub.add_parser("diff")
    sp.add_argument("--wait", type=float, default=2.0)
    sp.set_defaults(func=cmd_diff)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
