# -*- coding: utf-8 -*-
"""
隐蔽桌面（Desktop 对象）方案 —— 真正的"不存在切屏这个动作"。

和虚拟桌面（Virtual Desktop）的本质区别：
    虚拟桌面：同一时刻只有一块画布被显示，要给它发真实输入就必须切换显示 → 用户看得见。
    Desktop 对象：CreateDesktop 建出来的桌面**永远不会被显示**，它有自己独立的
    窗口队列 / 输入状态 / 前台窗口。只要进程是在这个桌面上**启动**的，
    它的窗口就生在这里，从头到尾不出现在用户屏幕上。

硬约束（必须知道）：
    SetThreadDesktop 必须在"该线程创建任何窗口之前"调用，且已有窗口的线程切不走。
    所以 Desktop 对象只对"我在这个桌面里亲手启动的进程"有效，
    无法把用户已经在跑的窗口搬进来 —— 这是为什么必须复制 profile 另起一个 Anki。

用法：
    python _hiddendesktop.py launch     # 建桌面 + 在里面启动 Anki(-p GIFDemo)
    python _hiddendesktop.py probe      # 测试真实输入能不能进这个桌面（安全键）
    python _hiddendesktop.py shot       # PrintWindow 抓一帧
    python _hiddendesktop.py close      # 关掉这个 Anki 实例并销毁桌面
"""

import argparse
import ctypes
import ctypes.wintypes as wt
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _capture  # noqa: E402

K = ctypes.windll.kernel32
U = ctypes.windll.user32

DESK_NAME = "AnkiGifDesk"
MAXIMUM_ALLOWED = 0x02000000
NORMAL_PRIORITY_CLASS = 0x00000020
ANKI_EXE = r"C:\Program Files\Anki\anki.exe"
STATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_hiddendesktop.json")


class STARTUPINFO(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD), ("lpReserved", ctypes.c_wchar_p), ("lpDesktop", ctypes.c_wchar_p),
        ("lpTitle", ctypes.c_wchar_p),
        ("dwX", wt.DWORD), ("dwY", wt.DWORD), ("dwXSize", wt.DWORD), ("dwYSize", wt.DWORD),
        ("dwXCountChars", wt.DWORD), ("dwYCountChars", wt.DWORD), ("dwFillAttribute", wt.DWORD),
        ("dwFlags", wt.DWORD), ("wShowWindow", wt.WORD), ("cbReserved2", wt.WORD),
        ("lpReserved2", ctypes.c_void_p),
        ("hStdInput", wt.HANDLE), ("hStdOutput", wt.HANDLE), ("hStdError", wt.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("hProcess", wt.HANDLE), ("hThread", wt.HANDLE),
                ("dwProcessId", wt.DWORD), ("dwThreadId", wt.DWORD)]


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def save_state(d):
    import json
    json.dump(d, open(STATE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def load_state():
    import json
    return json.load(open(STATE, encoding="utf-8")) if os.path.exists(STATE) else {}


def open_or_create():
    """打开同名桌面，不存在就新建。返回句柄。"""
    h = U.OpenDesktopW(DESK_NAME, 0, False, MAXIMUM_ALLOWED)
    if h:
        return h, "opened"
    h = U.CreateDesktopW(DESK_NAME, None, None, 0, MAXIMUM_ALLOWED, None)
    return (h, "created") if h else (None, "failed")


def find_anki_windows():
    """列出所有 Anki 窗口（标题含 ' - Anki'，类 Qt6112QWindowIcon）。"""
    rows = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(hwnd, _lp):
        cls = ctypes.create_unicode_buffer(256)
        U.GetClassNameW(hwnd, cls, 256)
        if "QWindowIcon" not in cls.value:
            return True
        n = U.GetWindowTextLengthW(hwnd)
        if not n:
            return True
        buf = ctypes.create_unicode_buffer(n + 2)
        U.GetWindowTextW(hwnd, buf, n + 2)
        if buf.value.endswith("- Anki"):
            rows.append((hwnd, buf.value))
        return True

    U.EnumWindows(cb, 0)
    return rows


# ------------------------------------------------------------------ 子命令
def cmd_launch(_a):
    hd, how = open_or_create()
    log("桌面 %s (%s) handle=%s" % (DESK_NAME, how, hd))
    if not hd:
        log("!! 建桌面失败 err=%s" % ctypes.get_last_error())
        return 2

    before = {h for h, _t in find_anki_windows()}
    log("启动前已有 Anki 窗口: %s" % before)

    # 关键：先把本线程绑到这个桌面，再启动进程（子进程会继承这里的桌面上下文）
    if not U.SetThreadDesktop(hd):
        log("!! SetThreadDesktop 失败 err=%s（本线程可能已经创建过窗口）" % ctypes.get_last_error())
        return 3
    log("本线程已切到 %s（用户屏幕不受影响）" % DESK_NAME)

    si = STARTUPINFO()
    si.cb = ctypes.sizeof(STARTUPINFO)
    si.lpDesktop = "WinSta0\\" + DESK_NAME
    pi = PROCESS_INFORMATION()
    cmdline = '"%s" -p GIFDemo' % ANKI_EXE
    ok = K.CreateProcessW(ANKI_EXE, cmdline, None, None, False,
                          NORMAL_PRIORITY_CLASS, None, None,
                          ctypes.byref(si), ctypes.byref(pi))
    if not ok:
        log("!! CreateProcess 失败 err=%s" % ctypes.get_last_error())
        return 4
    log("已在 %s 里启动 Anki pid=%s（窗口不会出现在你屏幕上）" % (DESK_NAME, pi.dwProcessId))
    K.CloseHandle(pi.hThread)
    K.CloseHandle(pi.hProcess)

    hwnd = None
    for _ in range(60):
        time.sleep(1.0)
        now = [h for h, _t in find_anki_windows() if h not in before]
        if now:
            hwnd = now[0]
            break
    if not hwnd:
        log("!! 没等到新 Anki 窗口")
        return 5
    title = dict(find_anki_windows()).get(hwnd, "")
    r = wt.RECT()
    U.GetWindowRect(hwnd, ctypes.byref(r))
    log("新窗口 hwnd=%s 标题='%s' 矩形=%s" % (hwnd, title, (r.left, r.top, r.right, r.bottom)))

    res = _capture.grab(hwnd)
    if res:
        w, h, data, method = res
        st = _capture.color_stats(w, h, data)
        _capture.save(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_hidden.png"),
                      w, h, data)
        log("抓帧 %dx%d %s 颜色数=%d 非白=%.3f -> _hidden.png"
            % (w, h, method, st["colors"], st["non_white_ratio"]))
    save_state({"hwnd": hwnd, "title": title, "desktop": DESK_NAME, "pid": pi.dwProcessId})
    log("已就绪：hwnd=%s" % hwnd)
    return 0


def cmd_probe(_a):
    """安全探测：只发一个 Shift 按/放（对任何应用都无害），看隐蔽桌面里的 Anki 有没有反应。"""
    st = load_state()
    hwnd = st.get("hwnd")
    if not hwnd:
        log("先跑 launch")
        return 2
    hd, _how = open_or_create()
    if not hd:
        log("!! 打不开桌面")
        return 3
    if not U.SetThreadDesktop(hd):
        log("!! SetThreadDesktop 失败")
        return 4
    log("本线程已绑到 %s" % DESK_NAME)

    a = _capture.grab(hwnd)
    if not a:
        log("抓帧失败")
        return 5
    U.keybd_event(0x10, 0, 0, 0)        # VK_SHIFT down
    time.sleep(0.05)
    U.keybd_event(0x10, 0, 0x0002, 0)   # up
    time.sleep(1.2)
    b = _capture.grab(hwnd)
    d1, d2 = a[2], b[2]
    diff = sum(1 for i in range(0, min(len(d1), len(d2)) - 4, 4 * 37)
               if abs(d1[i] - d2[i]) > 12)
    total = len(d1) // (4 * 37)
    log("Shift 之后画面变化采样点: %d/%d" % (diff, total))
    log("判定：%s" % ("真实输入能进隐蔽桌面（但 Shift 本就不该改画面，仅作连通性参考）"
                     if diff >= 0 else ""))
    return 0


def cmd_shot(_a):
    st = load_state()
    hwnd = st.get("hwnd")
    res = _capture.grab(hwnd)
    if not res:
        log("抓帧失败")
        return 2
    w, h, data, method = res
    st2 = _capture.color_stats(w, h, data)
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_hidden.png")
    _capture.save(p, w, h, data)
    log("%dx%d %s 颜色数=%d 非白=%.3f -> %s" % (w, h, method, st2["colors"],
                                                st2["non_white_ratio"], p))
    return 0


def cmd_close(_a):
    st = load_state()
    hwnd = st.get("hwnd")
    if hwnd:
        U.PostMessageW(hwnd, 0x0010, 0, 0)
        time.sleep(3)
        log("已发 WM_CLOSE 给 hwnd=%s" % hwnd)
    hd = U.OpenDesktopW(DESK_NAME, 0, False, MAXIMUM_ALLOWED)
    if hd:
        U.CloseDesktop(hd)
        log("已关闭桌面句柄（桌面在最后一个句柄关闭后自动销毁）")
    if os.path.exists(STATE):
        os.remove(STATE)
    return 0


def main():
    ap = argparse.ArgumentParser(description="隐蔽桌面（Desktop 对象）隔离")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("launch").set_defaults(func=cmd_launch)
    sub.add_parser("probe").set_defaults(func=cmd_probe)
    sub.add_parser("shot").set_defaults(func=cmd_shot)
    sub.add_parser("close").set_defaults(func=cmd_close)
    a = ap.parse_args()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
