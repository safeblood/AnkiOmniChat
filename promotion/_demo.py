# -*- coding: utf-8 -*-
"""
演示动作驱动器 —— 由本脚本点击 Anki，配合 _record.py 抓帧出 GIF。

只读检查用 `probe`；真正动手用 `run`，可指定从哪一步开始（--from）。
执行时 Anki 会被提到前台（真实键鼠输入必须发给前台窗口）。

步骤：
    1 deck      点选牌组
    2 study     点「学习」进入复习界面
    3 answer    空格翻到答案面
    4 inject    Ctrl+Alt+I 注入卡片到网页输入框
    5 send      点网页输入框 + 回车（触发网页发送）
    6 wait      等回复生成完（靠帧稳定判定）
    7 scrape    点「抓取网页回复」
    8 append    点「追加到卡片字段」并选字段
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _capture  # noqa: E402

from pywinauto import Application  # noqa: E402
from pywinauto.keyboard import send_keys  # noqa: E402

import ctypes
import ctypes.wintypes as wt

U = ctypes.windll.user32
TITLE = "837731400@qq.com - Anki"
DECK = "02-DNS域名解析"

MOUSE_LEFTDOWN, MOUSE_LEFTUP = 0x0002, 0x0004


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def find_hwnd():
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, wt.HWND, wt.LPARAM)
    def cb(hwnd, _lp):
        if not U.IsWindowVisible(hwnd):
            return True
        n = U.GetWindowTextLengthW(hwnd)
        if not n:
            return True
        buf = ctypes.create_unicode_buffer(n + 2)
        U.GetWindowTextW(hwnd, buf, n + 2)
        if TITLE.lower() in buf.value.lower():
            found.append(hwnd)
        return True

    U.EnumWindows(cb, 0)
    return found[0] if found else None


def win():
    hwnd = find_hwnd()
    app = Application(backend="uia").connect(handle=hwnd)
    return hwnd, app.window(handle=hwnd)


def activate(hwnd):
    if U.IsIconic(hwnd):
        U.ShowWindow(hwnd, 9)          # SW_RESTORE
        time.sleep(0.5)
    U.SetForegroundWindow(hwnd)
    time.sleep(0.4)


def click(cx, cy):
    U.SetCursorPos(int(cx), int(cy))
    time.sleep(0.05)
    U.mouse_event(MOUSE_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.06)
    U.mouse_event(MOUSE_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.15)


def rect_center(r):
    return (r.left + r.right) / 2, (r.top + r.bottom) / 2


def descendants(w):
    out = []
    stack = [(w, 0)]
    while stack:
        el, d = stack.pop()
        if d > 16:
            continue
        out.append((d, el))
        try:
            for k in el.children():
                stack.append((k, d + 1))
        except Exception:
            pass
    return out


def find(w, name, ctype=None, visible_only=True):
    """按名字子串 + 可选控件类型找控件，返回 (控件, rect)。"""
    hits = []
    for _d, el in descendants(w):
        try:
            ct = el.element_info.control_type
            nm = el.window_text() or ""
        except Exception:
            continue
        if name not in nm:
            continue
        if ctype and ctype not in ct:
            continue
        try:
            r = el.rectangle()
        except Exception:
            continue
        if visible_only and (r.right - r.left <= 0 or r.bottom - r.top <= 0):
            continue
        hits.append((el, r))
    return hits


def grab(hwnd):
    return _capture.grab(hwnd)


def frame_sig(hwnd):
    r = grab(hwnd)
    if not r:
        return None, None
    w, h, data, _m = r
    return (w, h), data


# --------------------------------------------------------------------------- #
# 各步骤
# --------------------------------------------------------------------------- #

def step_deck(state):
    hwnd, w = state["hwnd"], state["win"]
    hits = find(w, DECK, "Hyperlink")
    if not hits:
        log("!! 找不到牌组 %s" % DECK)
        return False
    el, r = hits[0]
    log("点牌组 %s @ %s" % (DECK, (r.left, r.top, r.right, r.bottom)))
    click(*rect_center(r))
    time.sleep(1.2)
    return True


def step_study(state):
    hwnd, w = state["hwnd"], state["win"]
    for label in ("学习", "Study", "开始学习", "立即学习"):
        hits = find(w, label, "Button")
        if hits:
            el, r = hits[0]
            log("点「%s」@ %s" % (label, (r.left, r.top, r.right, r.bottom)))
            click(*rect_center(r))
            time.sleep(2.0)
            return True
    log("!! 没找到学习按钮，当前按钮：" )
    for _d, el in descendants(w):
        try:
            if "Button" in el.element_info.control_type:
                nm = el.window_text()
                if nm:
                    log("   - %s" % nm[:40])
        except Exception:
            pass
    return False


def step_answer(state):
    activate(state["hwnd"])
    log("按空格翻答案")
    send_keys("{SPACE}")
    time.sleep(1.5)
    return True


def step_inject(state):
    activate(state["hwnd"])
    log("按 Ctrl+Alt+I 注入卡片")
    send_keys("^%i")
    time.sleep(2.0)
    return True


def locate_web_input(state):
    """注入前后各抓一帧，变化最集中的区域即网页输入框位置。"""
    hwnd = state["hwnd"]
    log("定位网页输入框：先抓基准帧")
    a = grab(hwnd)
    if not a:
        return None
    w, h, d1, _ = a
    log("请（已）触发注入，2.5s 后抓对比帧")
    time.sleep(2.5)
    b = grab(hwnd)
    w, h, d2, _ = b
    GX, GY = 24, 16
    best = (0, 0, 0)
    for gy in range(GY):
        for gx in range(GX):
            x0, x1 = gx * w // GX, (gx + 1) * w // GX
            y0, y1 = gy * h // GY, (gy + 1) * h // GY
            cnt = tot = 0
            for y in range(y0, y1, 4):
                for x in range(x0, x1, 4):
                    i = (y * w + x) * 4
                    if (abs(d1[i] - d2[i]) > 16 or abs(d1[i + 1] - d2[i + 1]) > 16
                            or abs(d1[i + 2] - d2[i + 2]) > 16):
                        cnt += 1
                    tot += 1
            ratio = cnt / max(1, tot)
            if ratio > best[0]:
                best = (ratio, gx, gy)
    cw, ch = w // GX, h // GY
    box = (best[1] * cw, best[2] * ch, (best[1] + 1) * cw, (best[2] + 1) * ch)
    log("输入框候选区域 %s（变化率 %.2f）" % (box, best[0]))
    return box


def step_send(state):
    """点网页输入框让它拿到焦点，再回车发送。"""
    hwnd = state["hwnd"]
    activate(hwnd)
    box = state.get("web_input_box")
    if not box:
        log("!! 没有输入框坐标，先用 locate 定位")
        return False
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    log("点网页输入框 @ (%d,%d)" % (cx, cy))
    click(cx, cy)
    time.sleep(0.6)
    log("按回车发送")
    send_keys("{ENTER}")
    time.sleep(1.0)
    return True


def step_wait(state, timeout=90):
    """等回复生成完：连续 6 秒帧内容基本不变即认为结束。"""
    hwnd = state["hwnd"]
    t0 = time.time()
    last = None
    stable = 0
    while time.time() - t0 < timeout:
        r = grab(hwnd)
        if r:
            w, h, data, _ = r
            if last is not None:
                d = 0
                n = 0
                for i in range(0, len(data) - 4, 4 * 64):
                    if (abs(data[i] - last[i]) > 12 or abs(data[i + 1] - last[i + 1]) > 12
                            or abs(data[i + 2] - last[i + 2]) > 12):
                        d += 1
                    n += 1
                ratio = d / max(1, n)
                if ratio < 0.002:
                    stable += 1
                else:
                    stable = 0
                log("  t=%.0fs 变化率 %.4f 稳定计数 %d" % (time.time() - t0, ratio, stable))
            last = data
            if stable >= 6:
                log("回复已稳定")
                return True
        time.sleep(1.0)
    log("!! 超时")
    return False


def step_scrape(state):
    hwnd, w = state["hwnd"], state["win"]
    activate(hwnd)
    hits = find(w, "抓取网页回复", "Button")
    if not hits:
        log("!! 找不到「抓取网页回复」")
        return False
    el, r = hits[0]
    log("点「抓取网页回复」@ %s" % ((r.left, r.top, r.right, r.bottom),))
    click(*rect_center(r))
    time.sleep(2.0)
    return True


def step_append(state):
    hwnd, w = state["hwnd"], state["win"]
    activate(hwnd)
    hits = find(w, "追加到卡片字段", "Button")
    if not hits:
        cands = [el.window_text() for _d, el in descendants(w)
                 if "Button" in (el.element_info.control_type or "")]
        log("!! 找不到「追加到卡片字段」，当前按钮：%s" % [c for c in cands if c][:20])
        return False
    el, r = hits[-1]
    log("点「追加到卡片字段」@ %s" % ((r.left, r.top, r.right, r.bottom),))
    click(*rect_center(r))
    time.sleep(1.5)
    # 字段选择弹窗
    hwnd2, w2 = win()
    items = find(w2, "", "ListItem") or find(w2, "", "CheckBox") or find(w2, "", "RadioButton")
    log("弹窗候选 %d 个" % len(items))
    if items:
        el2, r2 = items[0]
        log("选第一个字段：%r" % (el2.window_text()[:40],))
        click(*rect_center(r2))
        time.sleep(1.0)
    return True


STEPS = [
    ("deck", step_deck),
    ("study", step_study),
    ("answer", step_answer),
    ("inject", step_inject),
    ("locate", None),
    ("send", step_send),
    ("wait", step_wait),
    ("scrape", step_scrape),
    ("append", step_append),
]


def cmd_probe(a):
    hwnd, w = win()
    log("hwnd=%s" % hwnd)
    for name in ("学习", "Study", "追加", "复制", "粘贴", "抓取"):
        hits = find(w, name)
        if hits:
            log("%-8s -> %d 个：%s" % (name, len(hits),
                                    [(el.window_text()[:24],
                                      (r.left, r.top, r.right, r.bottom))
                                     for el, r in hits[:3]]))
        else:
            log("%-8s -> 无" % name)


def cmd_run(a):
    hwnd, w = win()
    activate(hwnd)
    state = {"hwnd": hwnd, "win": w}
    names = [s[0] for s in STEPS]
    start = names.index(a.start) if a.start in names else 0
    for name, fn in STEPS[start:]:
        if a.until and names.index(name) > names.index(a.until):
            break
        log("===== 步骤 %s =====" % name)
        if name == "locate":
            box = step_inject(state) and None
            # locate 需要在注入动作前后各抓一帧，所以这里重新注入一次再比对
            before = grab(hwnd)
            time.sleep(0.2)
            step_inject(state)
            time.sleep(1.5)
            after = grab(hwnd)
            w_, h_, d1, _ = before
            _w, _h, d2, _ = after
            GX, GY = 24, 16
            best = (0, 0, 0)
            for gy in range(GY):
                for gx in range(GX):
                    x0, x1 = gx * w_ // GX, (gx + 1) * w_ // GX
                    y0, y1 = gy * h_ // GY, (gy + 1) * h_ // GY
                    cnt = tot = 0
                    for y in range(y0, y1, 4):
                        for x in range(x0, x1, 4):
                            i = (y * w_ + x) * 4
                            if (abs(d1[i] - d2[i]) > 16 or abs(d1[i + 1] - d2[i + 1]) > 16
                                    or abs(d1[i + 2] - d2[i + 2]) > 16):
                                cnt += 1
                            tot += 1
                    if cnt / max(1, tot) > best[0]:
                        best = (cnt / max(1, tot), gx, gy)
            cw, ch = w_ // GX, h_ // GY
            state["web_input_box"] = (best[1] * cw, best[2] * ch,
                                      (best[1] + 1) * cw, (best[2] + 1) * ch)
            log("网页输入框候选区域: %s (变化率 %.2f)" % (state["web_input_box"], best[0]))
            continue
        ok = fn(state)
        log("步骤 %s: %s" % (name, "OK" if ok else "失败"))
        if not ok and a.strict:
            log("中止")
            return
        w = state["win"] = win()[1]
    log("全部步骤完成")


def main():
    p = argparse.ArgumentParser(description="演示动作驱动器")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("probe").set_defaults(func=cmd_probe)
    sp = sub.add_parser("run")
    sp.add_argument("--start", default="deck")
    sp.add_argument("--until", default=None)
    sp.add_argument("--strict", action="store_true")
    sp.set_defaults(func=cmd_run)
    a = p.parse_args()
    a.func(a)


if __name__ == "__main__":
    main()
