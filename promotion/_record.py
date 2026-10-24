# -*- coding: utf-8 -*-
"""
非侵入式录屏驱动器。

工作方式：
    用 PrintWindow(PW_RENDERFULLCONTENT) 定时抓 Anki 窗口内容，存成帧序列。
    抓的是窗口**自己重绘**的结果，不是屏幕区域 —— 所以窗口被别的窗口挡住、
    甚至推到屏幕外，都照样能录到真实内容。**全程不调用 SetForegroundWindow，
    不会抢用户的前台**。

帧去重：连续帧字节完全相同时不落盘，只在 concat 里累加时长 —— 静止画面不产生
多余帧，动起来才密集采样，最终 GIF 时间轴与真实操作一致。

用法：
    python _record.py selftest                      # 抓一帧，自检窗口内容/网页区是否渲染
    python _record.py rec --fps 10 --max 240        # 后台录（可用 .stop 文件叫停）
    python _record.py stop                          # 另一个进程里叫停录制
    python _record.py gif --width 1100 --fps 12     # 帧序列 -> GIF（两遍调色板）
    python _record.py gif --crop "1300,300,620,700" # 只保留局部（面板特写）
"""

import argparse
import ctypes
import ctypes.wintypes as wt
import hashlib
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _capture  # noqa: E402

U = ctypes.windll.user32
HERE = os.path.dirname(os.path.abspath(__file__))
FRAMES = os.path.join(HERE, "_frames")
STOP_FILE = os.path.join(FRAMES, ".stop")

DEFAULT_TITLE = "837731400@qq.com - Anki"


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def find_window(title_sub):
    """按标题子串找顶层可见窗口，返回 hwnd。"""
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(hwnd, _lp):
        if not U.IsWindowVisible(hwnd):
            return True
        n = U.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 2)
        U.GetWindowTextW(hwnd, buf, n + 2)
        if title_sub.lower() in buf.value.lower():
            found.append((hwnd, buf.value))
        return True

    U.EnumWindows(cb, 0)
    return found


def pick(title_sub):
    ws = find_window(title_sub)
    if not ws:
        log("找不到标题包含 %r 的窗口。当前顶层窗口：" % title_sub)
        for h, t in find_window("")[:40]:
            log("  hwnd=%s  %s" % (h, t[:80]))
        sys.exit(2)
    if len(ws) > 1:
        log("匹配到多个窗口，取第一个：")
        for h, t in ws:
            log("  hwnd=%s  %s" % (h, t))
    hwnd, title = ws[0]
    r = wt.RECT()
    U.GetWindowRect(hwnd, ctypes.byref(r))
    log("窗口 hwnd=%s  %r  矩形=(%d,%d)-(%d,%d)  %dx%d"
        % (hwnd, title, r.left, r.top, r.right, r.bottom,
           r.right - r.left, r.bottom - r.top))
    if U.IsIconic(hwnd):
        log("!! 窗口处于最小化状态，PrintWindow 可能抓到空内容。请把它恢复（不需要置顶）。")
    return hwnd


def crop_rect(data, w, h, spec):
    """spec = "x,y,w,h"，裁掉其余部分。data 为 BGRA。"""
    x, y, cw, ch = [int(v) for v in spec.split(",")]
    x = max(0, min(x, w - 1))
    y = max(0, min(y, h - 1))
    cw = max(1, min(cw, w - x))
    ch = max(1, min(ch, h - y))
    stride = w * 4
    out = bytearray()
    for row in range(y, y + ch):
        base = row * stride + x * 4
        out += data[base:base + cw * 4]
    return cw, ch, bytes(out)


def diff_ratio(old, new, step=64, thresh=12):
    """两次抓帧之间「明显不同」的像素占比（抽样比较，够快）。

    用来区分「周期性重绘」（只动一小块）和「用户真的在操作」（大半屏在变）。
    """
    if old is None or len(old) != len(new):
        return 1.0
    n = d = 0
    stride = 4 * step
    for i in range(0, len(new) - 4, stride):
        if (abs(new[i] - old[i]) > thresh
                or abs(new[i + 1] - old[i + 1]) > thresh
                or abs(new[i + 2] - old[i + 2]) > thresh):
            d += 1
        n += 1
    return d / max(1, n)


# --------------------------------------------------------------------------- #
# 录制
# --------------------------------------------------------------------------- #

def cmd_rec(a):
    os.makedirs(FRAMES, exist_ok=True)
    if os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)
    for f in os.listdir(FRAMES):
        if f.endswith(".png"):
            os.remove(os.path.join(FRAMES, f))

    hwnd = pick(a.title)
    base_interval = 1.0 / a.fps
    interval = 1.0 if a.arm else base_interval
    t0 = time.time()
    idx = 0
    prev_hash = None
    last_emit = t0
    lines = ["ffconcat version 1.0"]
    grabbed = emitted = idle = 0
    burst_t = None
    armed = not a.arm
    arm_t = t0 if armed else None
    watch = []
    last_change = t0
    prev_data = None

    log("开始录制：fps=%s  最长 %ss  输出 %s" % (a.fps, a.max, FRAMES))
    log("（不会抢前台，你可以正常操作 Anki；遮挡/切窗口都不影响）")
    if a.arm:
        log("待触发模式：1fps 廉价监视，%.0fs 内出现 %d 次变化才判定为「开始操作」"
            % (a.win, a.hits))
        log("           触发后满帧率录 %.0fs，或活动停止 %.0fs 后自动收尾" % (a.dur, a.tail))
    else:
        log("（空闲自动退避到 1fps，画面一变立刻恢复满帧率）")

    while True:
        loop_t = time.time()
        if os.path.exists(STOP_FILE):
            log("收到停止信号")
            break
        if a.max and time.time() - t0 > a.max:
            log("到达最长时长，自动停止")
            break

        res = _capture.grab(hwnd)
        if not res:
            log("抓帧失败（窗口可能已最小化或关闭），重试中")
            time.sleep(interval)
            continue
        w, h, data, method = res
        grabbed += 1

        if a.crop:
            w, h, data = crop_rect(data, w, h, a.crop)

        hh = hashlib.blake2b(data, digest_size=16).digest()
        now = time.time()
        changed = (hh != prev_hash)

        if a.arm and not armed:
            # 监视期：只统计变化，不落盘。
            # 双重判据 —— 变化幅度够大 AND 短时间内够密集，周期性重绘两个条件都不满足
            if changed:
                mag = diff_ratio(prev_data, data)
                if mag >= a.mag:
                    watch.append(now)
                    watch = [t for t in watch if now - t <= a.win]
                    log("[监视] t=%.0fs 变化幅度 %.1f%%（%d/%d）"
                        % (now - t0, mag * 100, len(watch), a.hits))
                    if len(watch) >= a.hits:
                        armed = True
                        arm_t = now
                        interval = base_interval
                        prev_hash = None          # 让当前帧成为首帧
                        last_emit = now
                        log("[触发] t=%.0fs 确认操作开始，进入满帧率录制" % (now - t0))
                else:
                    watch = []
            prev_hash = hh
            prev_data = data
            dt = interval - (time.time() - loop_t)
            if dt > 0:
                time.sleep(dt)
            continue

        if changed or (a.force and now - last_emit >= interval):
            dur = max(0.02, now - last_emit)
            idx += 1
            name = "f_%05d.png" % idx
            _capture.save(os.path.join(FRAMES, name), w, h, data)
            lines.append("file '%s'" % name)
            lines.append("duration %.3f" % dur)
            prev_hash = hh
            last_emit = now
            emitted += 1
            if emitted == 1:
                log("首帧已存（%s，%dx%d）" % (method, w, h))
            if emitted % 50 == 0:
                log("已存 %d 帧 / 抓了 %d 次 / 用时 %.0fs" % (emitted, grabbed, now - t0))

        # 自适应退避：长时间没变化就放慢轮询，变化一来立刻恢复满帧率
        if changed:
            if burst_t is None or now - burst_t > 1.0:
                log("[活动] t=%.0fs 检测到画面变化" % (now - t0))
            burst_t = now
            last_change = now
            idle = 0
            interval = base_interval
        else:
            idle += 1
            if idle > 60:
                interval = max(interval, 1.0)
            elif idle > 10:
                interval = max(interval, 0.5)

        if a.arm:
            if now - arm_t > a.dur:
                log("到达录制上限 %.0fs，收尾" % a.dur)
                break
            if now - arm_t > 20 and now - last_change > a.tail:
                log("活动已静止 %.0fs，收尾（共录 %.0fs）" % (a.tail, now - arm_t))
                break

        prev_data = data
        dt = interval - (time.time() - loop_t)
        if dt > 0:
            time.sleep(dt)

    if idx:
        lines.append("file 'f_%05d.png'" % idx)
        lines.append("duration 0.60")
        with open(os.path.join(FRAMES, "ffconcat.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    log("录制结束：%d 帧（抓取 %d 次），用时 %.1fs" % (emitted, grabbed, time.time() - t0))
    log("下一步：python _record.py gif --width %d" % (a.width or 1100))


def cmd_stop(_a):
    os.makedirs(FRAMES, exist_ok=True)
    with open(STOP_FILE, "w") as f:
        f.write("stop")
    log("已写入停止信号")


# --------------------------------------------------------------------------- #
# 合成 GIF
# --------------------------------------------------------------------------- #

def cmd_gif(a):
    cc = os.path.join(FRAMES, "ffconcat.txt")
    if not os.path.exists(cc):
        log("没有 %s，先跑 rec" % cc)
        sys.exit(2)
    out = os.path.abspath(a.out)
    fps = a.fps

    # 把过长的静止帧时长压掉，否则中间发呆 10 分钟 GIF 也会真放 10 分钟
    if a.maxdur > 0:
        raw = open(cc, encoding="utf-8").read().splitlines()
        clamped = []
        for ln in raw:
            if ln.startswith("duration "):
                clamped.append("duration %.3f" % min(float(ln.split()[1]), a.maxdur))
            else:
                clamped.append(ln)
        cc = os.path.join(FRAMES, "ffconcat_clamped.txt")
        open(cc, "w", encoding="utf-8").write("\n".join(clamped) + "\n")
        log("已裁剪静止帧（单帧最长 %.2fs）" % a.maxdur)

    vf = ("fps=%d,scale=%d:-1:flags=lanczos,split[x][y];"
          "[x]palettegen=max_colors=%d[p];[y][p]paletteuse=dither=bayer"
          % (fps, a.width, a.colors))
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", cc,
           "-vf", vf, "-loop", "0", out]
    log("合成中：%s" % " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        log("ffmpeg 失败：\n" + r.stderr[-2000:])
        sys.exit(1)
    size = os.path.getsize(out) / 1024 / 1024
    log("完成：%s  (%.2f MB)" % (out, size))
    if size > 5:
        log("!! 超过 5MB，Reddit 加载会慢。建议 --width 900 --colors 64 重跑")


# --------------------------------------------------------------------------- #
# 自检
# --------------------------------------------------------------------------- #

def cmd_selftest(a):
    hwnd = pick(a.title)
    res = _capture.grab(hwnd)
    if not res:
        log("抓帧失败")
        sys.exit(1)
    w, h, data, method = res
    st = _capture.color_stats(w, h, data)
    log("抓帧方式: %s  尺寸: %dx%d" % (method, w, h))
    log("整窗内容判定: 颜色数=%d 非白比例=%.3f" % (st["colors"], st["non_white_ratio"]))

    # 分横带看内容分布 —— 用来判断内嵌网页区到底渲染出来没有
    log("横带扫描（每 60px 一行，看非白像素占比）：")
    stride = w * 4
    y = 0
    while y < h:
        cnt = tot = 0
        x = 0
        while x < w:
            i = y * stride + x * 4
            r_, g_, b_ = data[i + 2], data[i + 1], data[i]
            if not (r_ > 240 and g_ > 240 and b_ > 240):
                cnt += 1
            tot += 1
            x += 6
        ratio = cnt / max(1, tot)
        bar = "#" * int(ratio * 40)
        log("  y=%4d  %.3f %s" % (y, ratio, bar))
        y += 60

    path = _capture.save(os.path.join(HERE, "_selftest.png"), w, h, data)
    log("样帧已存: %s" % path)


def main():
    p = argparse.ArgumentParser(description="非侵入式窗口录制（PrintWindow）")
    p.add_argument("--title", default=DEFAULT_TITLE)
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("rec")
    sp.add_argument("--fps", type=float, default=10)
    sp.add_argument("--max", type=float, default=240, help="最长录制秒数")
    sp.add_argument("--force", action="store_true", help="静止时也按帧率落盘")
    sp.add_argument("--crop", default=None, help="x,y,w,h")
    sp.add_argument("--width", type=int, default=1100)
    sp.add_argument("--arm", action="store_true",
                    help="待触发：检测到连续活动才开始录")
    sp.add_argument("--win", type=float, default=10.0, help="判定窗口秒数")
    sp.add_argument("--hits", type=int, default=2, help="窗口内大幅变化次数阈值")
    sp.add_argument("--mag", type=float, default=0.05,
                    help="判定为「在操作」的最小变化像素占比")
    sp.add_argument("--dur", type=float, default=120.0, help="触发后最长录多久")
    sp.add_argument("--tail", type=float, default=6.0, help="活动静止多久收尾")
    sp.set_defaults(func=cmd_rec)

    sub.add_parser("stop").set_defaults(func=cmd_stop)

    sp = sub.add_parser("gif")
    sp.add_argument("--out", default=os.path.join(HERE, "demo.gif"))
    sp.add_argument("--width", type=int, default=1100)
    sp.add_argument("--fps", type=int, default=12)
    sp.add_argument("--colors", type=int, default=128)
    sp.add_argument("--maxdur", type=float, default=1.0,
                    help="单帧最长显示秒数，压掉发呆片段；0=不裁剪")
    sp.set_defaults(func=cmd_gif)

    sp = sub.add_parser("selftest")
    sp.set_defaults(func=cmd_selftest)

    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
