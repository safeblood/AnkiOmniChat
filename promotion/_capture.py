# -*- coding: utf-8 -*-
"""
窗口内容抓取器 —— PrintWindow(PW_RENDERFULLCONTENT)。

与 ffmpeg gdigrab 的区别：
    gdigrab 抓的是窗口矩形对应的**屏幕区域**，窗口被遮挡时会拍到前面的窗口；
    PrintWindow 是请求窗口**自己重绘**到给定 DC，因此即使窗口被完全遮挡、
    甚至在另一个虚拟桌面上，抓到的仍然是这个窗口真实的内容。

所以录制期间窗口不需要保持在前台 —— 用户可以继续干自己的事。

依赖：ctypes（标准库）；有 Pillow 时直接存 PNG，没有则存 BMP（ffmpeg 可读）。
"""

import ctypes
import ctypes.wintypes as wt
import os
import struct
import time

U = ctypes.windll.user32
GDI = ctypes.windll.gdi32

PW_RENDERFULLCONTENT = 0x00000002
SRCCOPY = 0x00CC0020
DIB_RGB_COLORS = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_int32),
        ("biHeight", ctypes.c_int32), ("biPlanes", ctypes.c_uint16),
        ("biBitCount", ctypes.c_uint16), ("biCompression", ctypes.c_uint32),
        ("biSizeImage", ctypes.c_uint32), ("biXPelsPerMeter", ctypes.c_int32),
        ("biYPelsPerMeter", ctypes.c_int32), ("biClrUsed", ctypes.c_uint32),
        ("biClrImportant", ctypes.c_uint32),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER),
                ("bmiColors", ctypes.c_uint32 * 3)]


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def grab(hwnd, use_print_window=True):
    """抓取窗口像素，返回 (width, height, bytes BGRA bottom-up)。"""
    r = wt.RECT()
    U.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    if w <= 0 or h <= 0:
        return None

    hdc_win = U.GetWindowDC(hwnd)
    if not hdc_win:
        return None
    hdc_mem = GDI.CreateCompatibleDC(hdc_win)
    bmp = GDI.CreateCompatibleBitmap(hdc_win, w, h)
    GDI.SelectObject(hdc_mem, bmp)

    method = "BitBlt"
    if use_print_window:
        if U.PrintWindow(hwnd, hdc_mem, PW_RENDERFULLCONTENT):
            method = "PrintWindow(RENDERFULLCONTENT)"
        elif U.PrintWindow(hwnd, hdc_mem, 0):
            method = "PrintWindow(0)"
        else:
            GDI.BitBlt(hdc_mem, 0, 0, w, h, hdc_win, 0, 0, SRCCOPY)
    else:
        GDI.BitBlt(hdc_mem, 0, 0, w, h, hdc_win, 0, 0, SRCCOPY)

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = w
    bmi.bmiHeader.biHeight = -h           # 负值 = top-down
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0
    buf = (ctypes.c_char * (w * h * 4))()
    got = GDI.GetDIBits(hdc_mem, bmp, 0, h, buf, ctypes.byref(bmi), DIB_RGB_COLORS)

    GDI.DeleteObject(bmp)
    GDI.DeleteDC(hdc_mem)
    U.ReleaseDC(hwnd, hdc_win)
    if not got:
        return None
    return w, h, bytes(buf), method


def color_stats(w, h, data, sample=4000):
    """粗判画面是否有内容：统计采样到的不同颜色数与非白像素比例。"""
    step = max(1, (w * h) // sample)
    seen = set()
    non_white = 0
    total = 0
    i = 0
    while i < len(data) - 4:
        b, g, r, _a = data[i], data[i + 1], data[i + 2], data[i + 3]
        seen.add((r // 16, g // 16, b // 16))
        if not (r > 240 and g > 240 and b > 240):
            non_white += 1
        total += 1
        i += 4 * step
    return {"colors": len(seen), "non_white_ratio": round(non_white / max(1, total), 3)}


def save_bmp(path, w, h, data):
    """把 BGRA(top-down) 存成 24bit BMP（ffmpeg 能读）。"""
    row_size = (w * 3 + 3) & ~3
    pad = row_size - w * 3
    out = bytearray()
    out += b"BM"
    file_size = 14 + 40 + row_size * h
    out += struct.pack("<IHHI", file_size, 0, 0, 14 + 40)
    out += struct.pack("<IiiHHIIiiII", 40, w, h, 1, 24, 0, 0, 0, 0, 0, 0)
    for y in range(h):
        base = y * w * 4
        row = bytearray()
        for x in range(w):
            i = base + x * 4
            row += bytes((data[i], data[i + 1], data[i + 2]))
        row += b"\x00" * pad
        out += row
    with open(path, "wb") as f:
        f.write(bytes(out))
    return path


def save(path, w, h, data):
    """优先用 Pillow 存 PNG，否则存 BMP。"""
    try:
        from PIL import Image
        img = Image.frombuffer("RGBA", (w, h), data, "raw", "BGRA", 0, 1)
        img.convert("RGB").save(path)
        return path
    except Exception:
        base, _ext = os.path.splitext(path)
        return save_bmp(base + ".bmp", w, h, data)
