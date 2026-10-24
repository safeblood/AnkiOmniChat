# -*- coding: utf-8 -*-
"""
重启 Anki 后的「一键接管」脚本：等新进程 → 定位窗口 → 无激活恢复 → 挪到独立桌面 → 验证抓帧。

全程**不切用户的显示桌面**、不抢前台：
  * 恢复最小化用 SetWindowPlacement(SW_SHOWNOACTIVATE)，不激活
  * 挪桌面用 pyvda 的 AppView.move()，只搬窗口不改显示
  * 抓帧用 PrintWindow，对后台/别的桌面一样有效

用法：
    python _ready.py --old-pid 18540 --wait 420
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
SW_SHOWNOACTIVATE = 4


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


def wait_restart(old_pid, timeout):
    """等到出现一个 pid != old_pid 的 anki 进程（且旧进程最好已消失）。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        pids = anki_pids()
        if pids and old_pid not in pids:
            return pids[0]
        if len(pids) > 1:
            new = [p for p in pids if p != old_pid]
            if new:
                return new[0]
        time.sleep(2.0)
    return None


def wait_hwnd(timeout=90):
    t0 = time.time()
    while time.time() - t0 < timeout:
        hwnd = _demo.find_hwnd()
        if hwnd and U.IsWindow(hwnd):
            r = wt.RECT()
            U.GetWindowRect(hwnd, ctypes.byref(r))
            if (r.right - r.left) > 200:      # 已经从 160x28 的初始尺寸长出来
                return hwnd
        time.sleep(1.0)
    return None


def rect_of(hwnd):
    r = wt.RECT()
    U.GetWindowRect(hwnd, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def restore_no_activate(hwnd):
    wp = WINDOWPLACEMENT()
    wp.length = ctypes.sizeof(WINDOWPLACEMENT)
    if not U.GetWindowPlacement(hwnd, ctypes.byref(wp)):
        return False
    if wp.showCmd != 2:          # 2 = SW_SHOWMINIMIZED
        return False
    wp.showCmd = SW_SHOWNOACTIVATE
    U.SetWindowPlacement(hwnd, ctypes.byref(wp))
    return True


def move_to_other_desktop(hwnd):
    from pyvda import AppView, VirtualDesktop, get_virtual_desktops
    cur = VirtualDesktop.current()
    target = None
    for d in get_virtual_desktops():
        if str(d.id) != str(cur.id):
            target = d
            break
    if target is None:
        target = VirtualDesktop.create()
        time.sleep(1.0)
        cur.go()                 # 新建桌面会自动切过去，切回用户桌面
        time.sleep(0.8)
    AppView(hwnd).move(target)
    time.sleep(0.8)
    after = VirtualDesktop.current()
    return str(cur.id), str(AppView(hwnd).desktop_id), str(after.id)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old-pid", type=int, default=0)
    ap.add_argument("--wait", type=float, default=420)
    a = ap.parse_args()

    log("等待 Anki 重启（旧 pid=%s，最长等 %.0f 秒）…" % (a.old_pid or "-", a.wait))
    pid = wait_restart(a.old_pid, a.wait)
    if not pid:
        log("超时：没等到重启")
        return 2
    log("检测到新 Anki 进程 pid=%s" % pid)

    hwnd = wait_hwnd()
    if not hwnd:
        log("超时：没找到 Anki 主窗口")
        return 3
    log("主窗口 hwnd=%s  矩形=%s" % (hwnd, rect_of(hwnd)))

    if restore_no_activate(hwnd):
        time.sleep(0.6)
        log("已从最小化恢复（未激活），矩形=%s" % (rect_of(hwnd),))
    else:
        log("窗口不是最小化，无需恢复")

    user_id, anki_id, cur_after = move_to_other_desktop(hwnd)
    log("用户桌面=%s  Anki 现处桌面=%s  当前显示桌面=%s" % (user_id, anki_id, cur_after))
    if cur_after != user_id:
        log("!! 显示桌面被改动了，正在切回")
        from pyvda import VirtualDesktop, get_virtual_desktops
        for d in get_virtual_desktops():
            if str(d.id) == user_id:
                d.go()
                break
        time.sleep(0.8)

    res = _capture.grab(hwnd)
    if not res:
        log("抓帧失败")
        return 4
    w, h, data, method = res
    st = _capture.color_stats(w, h, data)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_ready.png")
    _capture.save(out, w, h, data)
    log("抓帧 %dx%d 方式=%s 颜色数=%d 非白比例=%.3f -> %s"
        % (w, h, method, st["colors"], st["non_white_ratio"], out))
    if st["colors"] < 20:
        log("!! 画面内容疑似为空，可能需要再等等 Anki 渲染完成")
        return 5
    log("接管就绪：hwnd=%s 画面正常，可以开录" % hwnd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
