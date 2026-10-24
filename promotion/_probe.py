# -*- coding: utf-8 -*-
"""探查 Anki 窗口：找窗口 -> 激活 -> 截图（缩放到 1200 宽便于查看）。"""

import os
import shutil
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _gui import find_window, activate, rect, shot, log  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

def main():
    hwnd, title = find_window("- Anki")
    if not hwnd:
        log("没找到 Anki 窗口，请先启动 Anki")
        return 1
    log("窗口: %s (hwnd=%s)" % (title, hwnd))
    log("矩形: %s" % rect(hwnd))
    log("激活: %s" % activate(hwnd))
    png = os.path.join(HERE, "_probe.png")
    if not shot(title, png):
        log("截图失败")
        return 2
    small = os.path.join(HERE, "_probe_small.png")
    subprocess.run([shutil.which("ffmpeg"), "-y", "-hide_banner", "-loglevel",
                    "error", "-i", png, "-vf", "scale=1200:-1", small], timeout=60)
    log("原图 %s (%.0f KB)" % (png, os.path.getsize(png) / 1024.0))
    log("缩略图 %s" % small)
    return 0


if __name__ == "__main__":
    sys.exit(main())
