# -*- coding: utf-8 -*-
"""
纯 UIA 后台驱动器 —— 只走「定向到控件」的通道，绝不抢前台、绝不切桌面。

可用通道（都不需要窗口在前台）：
    Button    -> InvokePattern.Invoke()
    CheckBox  -> TogglePattern.Toggle()
    TabItem   -> SelectionItemPattern.Select()
    Edit      -> ValuePattern.SetValue()   （Qt 的 QLineEdit 通常支持）
禁止通道：
    set_focus() / SetForegroundWindow() —— 会强制 Windows 把显示切到目标窗口所在的桌面
    SendInput / mouse_event / keybd_event / send_keys —— 只进当前显示桌面的前台窗口
"""

import ctypes
import ctypes.wintypes as wt
import time

from pywinauto import Application, Desktop

U = ctypes.windll.user32


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


# ------------------------------------------------------------------ 连接
def connect(handle=None, title=None):
    """连到某个顶层窗口，返回 UIA wrapper。"""
    if handle:
        return Application(backend="uia").connect(handle=handle).window(handle=handle)
    d = Desktop(backend="uia")
    for w in d.windows():
        try:
            if title and title in w.window_text():
                return w
        except Exception:
            pass
    return None


def descendants(w, max_depth=18):
    out = []
    stack = [(w, 0)]
    while stack:
        el, d = stack.pop()
        if d > max_depth:
            continue
        out.append((d, el))
        try:
            for k in el.children():
                stack.append((k, d + 1))
        except Exception:
            pass
    return out


def meta(el):
    try:
        ct = el.element_info.control_type
    except Exception:
        ct = "?"
    try:
        nm = el.window_text() or ""
    except Exception:
        nm = ""
    try:
        r = el.rectangle()
        rc = (r.left, r.top, r.right, r.bottom)
    except Exception:
        rc = None
    return ct, nm, rc


def find(w, name=None, ctype=None, visible_only=True):
    """按名字子串 + 控件类型找控件，返回 [(el, rect)]。"""
    hits = []
    for _d, el in descendants(w):
        ct, nm, rc = meta(el)
        if name and name not in nm:
            continue
        if ctype and ctype not in ct:
            continue
        if visible_only and (rc is None or rc[2] - rc[0] <= 0 or rc[3] - rc[1] <= 0):
            continue
        hits.append((el, rc))
    return hits


def dump(w, only_types=None, limit=400):
    lines = []
    for d, el in descendants(w)[:limit]:
        ct, nm, rc = meta(el)
        if only_types and not any(t in ct for t in only_types):
            continue
        lines.append("%s%s  %s  %s" % ("  " * d, ct, nm[:48], rc))
    return "\n".join(lines)


# ------------------------------------------------------------------ 动作
def invoke(el):
    try:
        el.invoke()
        return True
    except Exception:
        pass
    try:
        el.iface_invoke.Invoke()
        return True
    except Exception as e:
        log("  invoke 失败: %s" % e)
        return False


def toggle(el, want=None):
    """切换 CheckBox；want=True/False 表示想要的目标状态。"""
    state = None
    try:
        state = el.get_toggle_state()
    except Exception:
        pass
    if want is None or (state is not None and bool(state) != want):
        try:
            el.toggle()
        except Exception:
            try:
                el.iface_toggle.Toggle()
            except Exception as e:
                log("  toggle 失败: %s" % e)
                return None
    try:
        return el.get_toggle_state()
    except Exception:
        return None


def select(el):
    try:
        el.select()
        return True
    except Exception:
        try:
            el.iface_selection_item.Select()
            return True
        except Exception as e:
            log("  select 失败: %s" % e)
            return False


def is_enabled(el):
    try:
        return bool(el.is_enabled())
    except Exception:
        return None


def wait_window(title, timeout=15):
    """等某个标题的顶层窗口出现。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        w = connect(title=title)
        if w is not None:
            try:
                if w.exists() and w.is_visible():
                    return w
            except Exception:
                pass
        time.sleep(0.4)
    return None
