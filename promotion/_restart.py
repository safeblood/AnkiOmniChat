# -*- coding: utf-8 -*-
"""
优雅重启 Anki，并把它安置到独立虚拟桌面（全程不切用户的显示桌面）。

顺序很讲究：
  1) 先把现有 Anki 窗口挪到另一个桌面 —— 这样「是否同步」之类的关闭弹窗
     会开在另一个桌面上，用户完全看不到。
  2) PostMessage(WM_CLOSE) 优雅关闭（等它自己退出；卡住才清理弹窗）。
  3) 用 SW_SHOWMINNOACTIVE 启动新进程 —— 窗口默认最小化且不激活，屏幕不闪。
  4) 新窗口出现后立刻挪到另一个桌面，再无激活恢复。

用法：
    python _restart.py            # 关闭 + 重开 + 安置到独立桌面
    python _restart.py --close    # 只关不开
    python _restart.py --launch   # 只开不关
"""

import argparse
import ctypes
import ctypes.wintypes as wt
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _capture  # noqa: E402
import _demo  # noqa: E402

U = ctypes.windll.user32
WM_CLOSE = 0x0010
SW_SHOWMINNOACTIVE = 7
SW_SHOWNOACTIVATE = 4
ANKI_EXE = r"C:\Program Files\Anki\anki.exe"


class WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_uint), ("flags", ctypes.c_uint),
        ("showCmd", ctypes.c_uint),
        ("ptMinPosition", wt.POINT), ("ptMaxPosition", wt.POINT),
        ("rcNormalPosition", wt.RECT),
    ]


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def anki_pids():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq anki.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True)
    pids = []
    for line in (out.stdout or "").splitlines():
        parts = [p.strip('"') for p in line.split(",")]
        if len(parts) >= 2 and parts[1].isdigit():
            pids.append(int(parts[1]))
    return pids


def rect_of(hwnd):
    r = wt.RECT()
    U.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def other_desktop():
    """返回一个『不是当前显示桌面』的桌面对象。"""
    from pyvda import VirtualDesktop, get_virtual_desktops
    cur = VirtualDesktop.current()
    for d in get_virtual_desktops():
        if str(d.id) != str(cur.id):
            return cur, d
    new = VirtualDesktop.create()
    time.sleep(1.0)
    cur.go()
    time.sleep(0.8)
    return cur, new


def move_away(hwnd):
    from pyvda import AppView
    cur, target = other_desktop()
    AppView(hwnd).move(target)
    time.sleep(0.6)
    return str(cur.id), str(AppView(hwnd).desktop_id)


def close_anki():
    pids = anki_pids()
    if not pids:
        log("Anki 没在跑，跳过关闭")
        return True
    hwnd = _demo.find_hwnd()
    if hwnd:
        log("先把窗口挪走再关，弹窗就不会出现在你眼前 hwnd=%s" % hwnd)
        move_away(hwnd)
        U.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        log("已发送 WM_CLOSE")
    else:
        log("没找到主窗口，直接 taskkill /im anki.exe")
        subprocess.run(["taskkill", "/im", "anki.exe"], capture_output=True)

    for i in range(30):
        time.sleep(1.0)
        if not anki_pids():
            log("Anki 已退出（%d 秒）" % (i + 1))
            return True
        if i == 6:
            log("还没退出，清掉可能的模态弹窗")
            kill_modals(pids)
        if i == 16:
            log("仍卡住，强制结束")
            subprocess.run(["taskkill", "/f", "/im", "anki.exe"], capture_output=True)
    return not anki_pids()


def kill_modals(pids):
    """关掉属于 anki 进程的可见弹窗（如『是否同步』）。"""
    closed = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(hwnd, _lp):
        pid = wt.DWORD()
        U.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value in pids and U.IsWindowVisible(hwnd):
            cls = ctypes.create_unicode_buffer(256)
            U.GetClassNameW(hwnd, cls, 256)
            n = U.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 2)
            U.GetWindowTextW(hwnd, buf, n + 2)
            if cls.value == "#32770" or "Anki" in buf.value or "同步" in buf.value:
                U.PostMessageW(hwnd, WM_CLOSE, 0, 0)
                closed.append((hwnd, buf.value))
        return True

    U.EnumWindows(cb, 0)
    for hwnd, title in closed:
        log("  关掉弹窗 hwnd=%s '%s'" % (hwnd, title))
    return closed


def launch_anki():
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = SW_SHOWMINNOACTIVE
    subprocess.Popen([ANKI_EXE], startupinfo=si,
                     creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    log("已用 SW_SHOWMINNOACTIVE 启动：默认最小化、不激活（屏幕不闪）")


def wait_hwnd(timeout=120):
    t0 = time.time()
    last = None
    while time.time() - t0 < timeout:
        pids = anki_pids()
        hwnd = _demo.find_hwnd()
        if hwnd and U.IsWindow(hwnd):
            l, t, r, b = rect_of(hwnd)
            if (r - l) > 300 and (b - t) > 200:
                return hwnd
            if last != (r - l, b - t):
                log("  窗口尺寸 %dx%d，等它长出来…" % (r - l, b - t))
                last = (r - l, b - t)
        elif not pids:
            log("  进程还没起来")
        time.sleep(1.0)
    return None


def restore_no_activate(hwnd):
    wp = WINDOWPLACEMENT()
    wp.length = ctypes.sizeof(WINDOWPLACEMENT)
    U.GetWindowPlacement(hwnd, ctypes.byref(wp))
    if wp.showCmd != 2:
        return False
    wp.showCmd = SW_SHOWNOACTIVATE
    U.SetWindowPlacement(hwnd, ctypes.byref(wp))
    return True


def verify(hwnd):
    res = _capture.grab(hwnd)
    if not res:
        log("抓帧失败")
        return False
    w, h, data, method = res
    st = _capture.color_stats(w, h, data)
    _capture.save(os.path.join(os.path.dirname(os.path.abspath(__file__)), "_ready.png"),
                  w, h, data)
    log("抓帧 %dx%d %s 颜色数=%d 非白比例=%.3f" % (w, h, method, st["colors"],
                                                 st["non_white_ratio"]))
    return st["colors"] >= 20


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--close", action="store_true")
    ap.add_argument("--launch", action="store_true")
    a = ap.parse_args()

    if not a.launch:
        if not close_anki():
            log("关闭失败，中止")
            return 2
    if a.close:
        return 0

    launch_anki()
    hwnd = wait_hwnd()
    if not hwnd:
        log("没等到新窗口")
        return 3
    log("新窗口 hwnd=%s 矩形=%s" % (hwnd, rect_of(hwnd)))

    user_id, anki_id = move_away(hwnd)
    log("已挪到桌面 %s（你的桌面 %s 不受影响）" % (anki_id, user_id))

    if restore_no_activate(hwnd):
        time.sleep(0.8)
        log("无激活恢复，矩形=%s" % (rect_of(hwnd),))

    time.sleep(2.0)
    ok = verify(hwnd)
    log("结果：%s" % ("就绪，可以开录" if ok else "画面疑似为空"))
    return 0 if ok else 5


if __name__ == "__main__":
    sys.exit(main())
