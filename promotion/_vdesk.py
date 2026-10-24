# -*- coding: utf-8 -*-
"""
把 Anki 搬到独立虚拟桌面，避免操作过程中抢占用户正在看的那个桌面。

Windows 的真实限制（先说清楚，别抱幻想）：
  * 一台机器同一时刻只能显示一个虚拟桌面，所以「切过去操作」必然会让屏幕画面切换。
  * 但只要**不切过去**，就能做到完全不打扰：
      - UIA 的 InvokePattern 对后台窗口照样生效（按钮随便点）
      - PrintWindow 抓帧对后台/被遮挡窗口照样生效
      - 唯一需要前台的是**真实键盘输入**
    所以本模块把 Anki 挪走后，默认走「不切桌面 + UIA 点击」，
    只有在必须敲键盘时才短暂切过去（--go），用完立刻切回。

用法：
    python _vdesk.py list                    # 列出虚拟桌面
    python _vdesk.py move                    # 把 Anki 挪到新建的独立桌面，然后切回原桌面
    python _vdesk.py go                      # 切到 Anki 所在桌面
    python _vdesk.py back                    # 切回用户原来的桌面
    python _vdesk.py where                   # 看 Anki 当前在哪个桌面
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _demo  # noqa: E402

STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_vdesk.json")


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def vda():
    from pyvda import AppView, VirtualDesktop, get_virtual_desktops
    return AppView, VirtualDesktop, get_virtual_desktops


def load_state():
    import json
    if os.path.exists(STATE_FILE):
        return json.load(open(STATE_FILE, encoding="utf-8"))
    return {}


def save_state(d):
    import json
    json.dump(d, open(STATE_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def cmd_list(_a):
    _AppView, _VD, get_vds = vda()
    vds = get_vds()
    cur = _VD.current()
    for i, d in enumerate(vds):
        log("%d: %s %s" % (i, d, "<== 当前" if d.id == cur.id else ""))
    log("共 %d 个桌面" % len(vds))


def cmd_where(_a):
    AppView, _VD, get_vds = vda()
    hwnd = _demo.find_hwnd()
    v = AppView(hwnd)
    log("Anki hwnd=%s 所在桌面 id=%s" % (hwnd, v.desktop_id))
    cur = _VD.current()
    log("当前显示桌面 id=%s  同一桌面: %s" % (cur.id, v.desktop_id == cur.id))
    for i, d in enumerate(get_vds()):
        if d.id == v.desktop_id:
            log("Anki 位于第 %d 个桌面" % i)
    st = load_state()
    if st.get("user_desktop_id"):
        log("记录的『用户原桌面』id=%s" % st["user_desktop_id"])


def cmd_move(_a):
    AppView, VD, get_vds = vda()
    hwnd = _demo.find_hwnd()
    user = VD.current()
    log("用户当前桌面 id=%s（记下来，稍后切回）" % user.id)

    target = None
    for d in get_vds():
        if d.id != user.id:
            target = d
            break
    if target is None:
        log("只有一个桌面，新建一个")
        target = VD.create()          # 会切到新桌面
        time.sleep(1.0)
    log("目标桌面 id=%s" % target.id)

    AppView(hwnd).move(target)
    time.sleep(0.6)
    log("Anki 已挪到目标桌面，当前所在: %s" % AppView(hwnd).desktop_id)

    user.go()                          # 切回用户原来的桌面
    time.sleep(0.8)
    save_state({"user_desktop_id": str(user.id),
                "anki_desktop_id": str(target.id),
                "hwnd": hwnd})
    log("已切回用户桌面 id=%s。现在 Anki 在另一个桌面上，你的屏幕不受影响。" % user.id)


def cmd_go(_a):
    _AppView, _VD, _g = vda()
    st = load_state()
    if not st.get("anki_desktop_id"):
        log("还没 move，先跑 move")
        return
    for d in _g():
        if str(d.id) == st["anki_desktop_id"]:
            d.go()
            log("已切到 Anki 桌面")
            return
    log("没找到记录的桌面")


def cmd_back(_a):
    _AppView, _VD, _g = vda()
    st = load_state()
    if not st.get("user_desktop_id"):
        log("没记录用户桌面")
        return
    for d in _g():
        if str(d.id) == st["user_desktop_id"]:
            d.go()
            log("已切回用户桌面")
            return
    log("没找到记录的桌面")


def main():
    p = argparse.ArgumentParser(description="虚拟桌面隔离")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").set_defaults(func=cmd_list)
    sub.add_parser("where").set_defaults(func=cmd_where)
    sub.add_parser("move").set_defaults(func=cmd_move)
    sub.add_parser("go").set_defaults(func=cmd_go)
    sub.add_parser("back").set_defaults(func=cmd_back)
    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
