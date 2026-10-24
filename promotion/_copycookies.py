# -*- coding: utf-8 -*-
"""
补齐 webprofile 里被锁的文件（Cookies 等）。

QtWebEngine 运行时会独占 Cookies / Cookies-journal / LOCK，所以必须先关掉占用它的
那个 Anki 实例，拷完再原样开回去。

用法：
    python _copycookies.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _demo  # noqa: E402
import _restart as R  # noqa: E402

SRC = r"C:\Users\83773\AppData\Roaming\Anki2\837731400@qq.com\AnkiOmniChat\webprofile"
DST = r"C:\Users\83773\AppData\Roaming\Anki2\GIFDemo\AnkiOmniChat\webprofile"


def copy_missing():
    done, bad = 0, []
    for root, _dirs, files in os.walk(SRC):
        rel = os.path.relpath(root, SRC)
        out = DST if rel == "." else os.path.join(DST, rel)
        os.makedirs(out, exist_ok=True)
        for f in files:
            s, d = os.path.join(root, f), os.path.join(out, f)
            if os.path.exists(d) and os.path.getsize(d) == os.path.getsize(s):
                continue
            try:
                with open(s, "rb") as fh:
                    data = fh.read()
                with open(d, "wb") as fh:
                    fh.write(data)
                done += 1
            except Exception as e:
                bad.append((f, str(e)[:60]))
    return done, bad


def main():
    print("--- 关掉占用 Cookies 的 Anki ---", flush=True)
    print("closed:", R.close_anki(), flush=True)
    time.sleep(1.0)
    n, bad = copy_missing()
    print("补拷 %d 个文件，仍失败：%s" % (n, bad), flush=True)
    try:
        print("Cookies 大小: %d" % os.path.getsize(os.path.join(DST, "Cookies")))
    except Exception as e:
        print("Cookies 不可用:", e)

    print("--- 原样开回原 Anki（最小化、不激活，再挪到它的桌面）---", flush=True)
    R.launch_anki()
    time.sleep(7)
    h = _demo.find_hwnd()
    print("hwnd", h)
    if h:
        print("move ->", R.move_away(h))
    return 0


if __name__ == "__main__":
    sys.exit(main())
