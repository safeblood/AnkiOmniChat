# -*- coding: utf-8 -*-
"""
极简 Windows GUI 控制工具 —— 只依赖标准库 ctypes + ffmpeg，不装任何第三方包。

用途：驱动 Anki 窗口录制演示 GIF。

能力：
    find_window     按标题后缀找窗口
    activate        前置并激活窗口（绕过前台锁）
    rect            取窗口矩形
    key             按组合键，如 key('ctrl', 'alt', 'i')
    type_text       通过剪贴板粘贴输入（支持中文）
    click           点击屏幕坐标
    shot            ffmpeg 抓单帧
    record_start / record_stop
    to_gif          mp4 -> 高质量 GIF（双遍 palette）
"""

import ctypes
import ctypes.wintypes as wt
import os
import shlex
import shutil
import subprocess
import time

U = ctypes.windll.user32

# 虚拟键码
VK_MAP = {
    "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "win": 0x5B,
    "enter": 0x0D, "esc": 0x1B, "tab": 0x09, "space": 0x20,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "home": 0x24, "end": 0x23, "backspace": 0x08, "delete": 0x2E,
}
for _c in "abcdefghijklmnopqrstuvwxyz":
    VK_MAP[_c] = ord(_c.upper())
for _i in range(10):
    VK_MAP[str(_i)] = 0x30 + _i
for _i in range(1, 13):
    VK_MAP["f%d" % _i] = 0x6E + _i

KEYEVENTF_KEYUP = 0x0002
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_MOVE = 0x0001


def log(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def find_window(title_suffix):
    """按标题后缀查找可见窗口，返回 hwnd。"""
    found = []
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)

    def cb(h, l):
        if U.IsWindowVisible(h):
            n = U.GetWindowTextLengthW(h)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                U.GetWindowTextW(h, buf, n + 1)
                found.append((h, buf.value))
        return True

    U.EnumWindows(EnumWindowsProc(cb), 0)
    for h, t in found:
        if t.endswith(title_suffix):
            return h, t
    return None, None


def activate(hwnd, restore=True):
    """前置窗口。ALT 键技巧 + AttachThreadInput + SwitchToThisWindow 三重保险。"""
    if restore:
        U.ShowWindow(hwnd, 9)  # SW_RESTORE
        time.sleep(0.15)

    # 经典绕过：模拟按一下 ALT，让系统认为用户有输入，从而允许切换前台
    U.keybd_event(0x12, 0, 0, 0)   # ALT down
    U.keybd_event(0x12, 0, KEYEVENTF_KEYUP, 0)  # ALT up
    time.sleep(0.1)

    cur = U.GetForegroundWindow()
    tid_cur = U.GetWindowThreadProcessId(cur, None)
    tid_dst = U.GetWindowThreadProcessId(hwnd, None)
    attached = False
    if tid_cur and tid_dst and tid_cur != tid_dst:
        attached = bool(U.AttachThreadInput(tid_cur, tid_dst, True))
    try:
        U.BringWindowToTop(hwnd)
        ok = bool(U.SetForegroundWindow(hwnd))
        if not ok:
            try:
                U.SwitchToThisWindow(hwnd, True)
                ok = (U.GetForegroundWindow() == hwnd)
            except Exception:
                pass
    finally:
        if attached:
            U.AttachThreadInput(tid_cur, tid_dst, False)
    time.sleep(0.4)
    return U.GetForegroundWindow() == hwnd


def rect(hwnd):
    r = wt.RECT()
    U.GetWindowRect(hwnd, ctypes.byref(r))
    return {"left": r.left, "top": r.top, "right": r.right, "bottom": r.bottom,
            "width": r.right - r.left, "height": r.bottom - r.top}


def _tap(vk, down=True):
    U.keybd_event(vk, 0, 0 if down else KEYEVENTF_KEYUP, 0)


def key(*names):
    """按下组合键后释放，如 key('ctrl','alt','i')。"""
    vks = []
    for n in names:
        vk = VK_MAP.get(str(n).lower())
        if vk is None:
            raise ValueError("未知按键: %s" % n)
        vks.append(vk)
    for vk in vks:
        _tap(vk, True)
        time.sleep(0.05)
    for vk in reversed(vks):
        _tap(vk, False)
        time.sleep(0.05)


def press(name):
    vks = [VK_MAP[str(name).lower()]]
    _tap(vks[0], True)
    time.sleep(0.05)
    _tap(vks[0], False)


def _set_clipboard(text):
    """把 Unicode 文本写入剪贴板（CF_UNICODE）。"""
    CF_UNICODE = 13
    GMEM_MOVEABLE = 0x0002
    k = ctypes.windll.kernel32
    if not U.OpenClipboard(None):
        return False
    try:
        U.EmptyClipboard()
        data = text.encode("utf-16-le") + b"\x00\x00"
        h = k.GlobalAlloc(GMEM_MOVEABLE, len(data))
        if not h:
            return False
        p = k.GlobalLock(h)
        ctypes.memmove(p, data, len(data))
        k.GlobalUnlock(h)
        if not U.SetClipboardData(CF_UNICODE, h):
            return False
        return True
    finally:
        U.CloseClipboard()


def type_text(text):
    """输入文本（中文走剪贴板 + Ctrl+V）。"""
    if all(ord(c) < 128 for c in text):
        for ch in text:
            if ch == " ":
                press("space")
            else:
                key(ch.lower()) if ch.isalnum() else None
            time.sleep(0.02)
    else:
        if not _set_clipboard(text):
            log("剪贴板写入失败")
            return False
        time.sleep(0.1)
        key("ctrl", "v")
    return True


def click(x, y, move_first=True):
    if move_first:
        U.SetCursorPos(int(x), int(y))
        time.sleep(0.15)
    U.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.08)
    U.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.15)


def move(x, y):
    U.SetCursorPos(int(x), int(y))
    time.sleep(0.1)


def _ffmpeg():
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RuntimeError("找不到 ffmpeg")
    return exe


def shot(window_title, out):
    """抓窗口单帧 PNG。"""
    subprocess.run([_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "gdigrab", "-i", "title=%s" % window_title,
                    "-frames:v", "1", out], timeout=60)
    return out if os.path.exists(out) else None


class Recorder:
    """用 ffmpeg gdigrab 录制窗口。"""

    def __init__(self, window_title, fps=12):
        self.title = window_title
        self.fps = fps
        self.proc = None
        self.out = None

    def start(self, out_mp4):
        self.out = out_mp4
        cmd = [_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error",
               "-f", "gdigrab", "-framerate", str(self.fps),
               "-draw_mouse", "1",
               "-i", "title=%s" % self.title,
               "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
               out_mp4]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE,
                                     stdout=subprocess.DEVNULL,
                                     stderr=subprocess.PIPE)
        time.sleep(1.2)
        log("录制中：%s" % out_mp4)

    def stop(self):
        if not self.proc:
            return None
        try:
            self.proc.stdin.write(b"q")
            self.proc.stdin.flush()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=20)
        except Exception:
            self.proc.kill()
        log("录制结束：%s" % self.out)
        return self.out


def to_gif(mp4, gif, fps=12, width=1000, start=0, duration=None):
    """高质量 GIF：先生成调色板再转换，可选裁剪起始与时长。"""
    args = [_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error"]
    if start:
        args += ["-ss", str(start)]
    args += ["-i", mp4]
    if duration:
        args += ["-t", str(duration)]
    palette = gif + ".palette.png"
    vf = "fps=%d,scale=%d:-1:flags=lanczos" % (fps, width)
    subprocess.run([_ffmpeg(), "-y", "-hide_banner", "-loglevel", "error"]
                   + (["-ss", str(start)] if start else [])
                   + ["-i", mp4]
                   + (["-t", str(duration)] if duration else [])
                   + ["-vf", vf + ",palettegen=max_colors=128", palette],
                   timeout=180)
    subprocess.run(args + ["-i", palette, "-lavfi",
                            "%s [x]; [x][1:v] paletteuse=dither=bayer" % vf,
                            gif], timeout=180)
    if os.path.exists(palette):
        os.remove(palette)
    return gif if os.path.exists(gif) else None
