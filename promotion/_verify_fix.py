# -*- coding: utf-8 -*-
"""
验证 v1.1.2 的修复：在设置里勾上「粘贴后自动点击网页的发送按钮」，
不重启 Anki，「发送」按钮应当立刻从灰变亮。

用法：
    python _verify_fix.py            # 打开开关并验证
    python _verify_fix.py --off      # 关掉开关并验证
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _demo  # noqa: E402
import _uiadrive as ua  # noqa: E402

DLG_TITLE = "AnkiOmniChat 设置"


def panel_send_button(w):
    """面板里的『发送』按钮（面板在窗口右侧，x > 1500）。"""
    for el, rc in ua.find(w, "发送", "Button"):
        if rc[0] > 1400:
            return el, rc
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--off", action="store_true", help="把开关关回去")
    a = ap.parse_args()
    want = not a.off

    hwnd = _demo.find_hwnd()
    w = ua.connect(handle=hwnd)
    ua.log("主窗口 hwnd=%s" % hwnd)

    el, rc = panel_send_button(w)
    if el is None:
        ua.log("!! 面板里没找到『发送』按钮")
        return 3
    before = ua.is_enabled(el)
    ua.log("修复前：『发送』按钮 enabled=%s  位置=%s" % (before, rc))

    hits = ua.find(w, "设置", "Button")
    if not hits:
        ua.log("!! 没找到『设置』按钮")
        return 3
    ua.log("点『设置』（UIA invoke，不抢前台）")
    ua.invoke(hits[0][0])

    dlg = ua.wait_window(DLG_TITLE, timeout=20)
    if dlg is None:
        ua.log("!! 设置对话框没出现")
        return 4
    ua.log("设置对话框已打开：%s" % dlg.window_text())

    tabs = ua.find(dlg, "网页模式", "TabItem")
    if tabs:
        ua.select(tabs[0][0])
        time.sleep(0.6)
        ua.log("已切到『网页模式』标签页")
    else:
        ua.log("  （没找到标签页控件，直接找复选框）")

    boxes = ua.find(dlg, "发送按钮", "CheckBox")
    if not boxes:
        ua.log("!! 没找到自动发送的复选框，对话框控件清单：")
        print(ua.dump(dlg, only_types=["CheckBox", "Button", "Tab"]))
        return 5
    for el2, rc2 in boxes:
        state = None
        try:
            state = el2.get_toggle_state()
        except Exception:
            pass
        ua.log("复选框『%s』当前=%s 位置=%s" % (el2.window_text(), state, rc2))
        if bool(state) != want:
            ua.toggle(el2, want)
            time.sleep(0.4)
            try:
                ua.log("  切换后=%s" % el2.get_toggle_state())
            except Exception:
                pass
        break

    oks = []
    for label in ("OK", "确定", "Ok"):
        oks = ua.find(dlg, label, "Button")
        if oks:
            break
    if not oks:
        ua.log("!! 没找到确定按钮，按钮清单：")
        print(ua.dump(dlg, only_types=["Button"]))
        return 6
    ua.log("点『%s』保存" % oks[0][0].window_text())
    ua.invoke(oks[0][0])
    time.sleep(2.0)

    w2 = ua.connect(handle=hwnd)
    el3, rc3 = panel_send_button(w2)
    if el3 is None:
        ua.log("!! 保存后面板『发送』按钮不见了")
        return 7
    after = ua.is_enabled(el3)
    try:
        tip = el3.window_text()
    except Exception:
        tip = ""
    ua.log("修复后：『发送』按钮 enabled=%s" % after)

    print("")
    if want:
        ok = (before is False) and (after is True)
        print("结论：%s  （灰 -> 亮，未重启 Anki，修复生效）" % ("通过" if ok else "未通过"))
    else:
        ok = (before is True) and (after is False)
        print("结论：%s  （亮 -> 灰，未重启 Anki，修复生效）" % ("通过" if ok else "未通过"))
    return 0 if ok else 8


if __name__ == "__main__":
    sys.exit(main())
