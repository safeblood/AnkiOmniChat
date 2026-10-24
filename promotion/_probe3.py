# -*- coding: utf-8 -*-
"""探查 Anki：PrintWindow 抓帧（含内容判定）+ UIA 读出按钮坐标。"""

import ctypes
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

ctypes.windll.user32.SetProcessDPIAware()

from _capture import color_stats, grab, log, save  # noqa: E402
from _gui import find_window, rect  # noqa: E402


def main():
    hwnd, title = find_window("- Anki")
    if not hwnd:
        log("没找到 Anki 窗口")
        return 1
    log("窗口: %s" % title)
    log("矩形: %s" % rect(hwnd))

    # 1) PrintWindow 抓帧
    res = grab(hwnd)
    if not res:
        log("抓帧失败")
        return 2
    w, h, data, method = res
    log("抓帧方式: %s  尺寸: %dx%d" % (method, w, h))
    stats = color_stats(w, h, data)
    log("内容判定: 颜色数=%s 非白比例=%s" % (stats["colors"], stats["non_white_ratio"]))
    out = save(os.path.join(HERE, "_cap.png"), w, h, data)
    log("已保存: %s (%.0f KB)" % (out, os.path.getsize(out) / 1024.0))
    if stats["colors"] < 8:
        log("警告：画面接近纯色，可能没抓到真实内容")

    # 2) UIA 控件：列出按钮及其坐标
    try:
        from pywinauto import Desktop
        d = Desktop(backend="uia")
        win = None
        for wnd in d.windows():
            try:
                if wnd.window_text().endswith("- Anki"):
                    win = wnd
                    break
            except Exception:
                continue
        if win is None:
            log("UIA 没找到窗口（Qt 可能未暴露 UIA）")
            return 0
        log("--- UIA Buttons ---")
        for c in win.descendants(control_type="Button"):
            try:
                t = c.window_text()
                r = c.rectangle()
                if t.strip():
                    log("  [%s] at (%d,%d)-(%d,%d)" % (t[:30], r.left, r.top, r.right, r.bottom))
            except Exception:
                pass
        log("--- UIA Edit/Text ---")
        for c in win.descendants(control_type="Edit"):
            try:
                r = c.rectangle()
                log("  Edit at (%d,%d)-(%d,%d) name=%s" % (r.left, r.top, r.right, r.bottom, (c.window_text() or "")[:20]))
            except Exception:
                pass
    except Exception as e:
        log("UIA 失败: %s" % str(e)[:200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
