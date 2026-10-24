# -*- coding: utf-8 -*-
"""
AnkiOmniChat —— 在 Anki 内复刻 Obsidian OmniChat 的侧边 AI 对话体验。

设计约定
--------
* 兼容 Anki 2.1.60 ~ 2.1.66（Qt5 / PyQt5，Qt6 相关枚举做了兜底）。
* 只使用官方 Qt WebEngine、anki/aqt hooks 与 Anki 自带库，不引入任何第三方 pip 依赖。
* 不使用已废弃 API：`note.flush()`、`mw.col.updateNote` 等旧写法一律以 2.1.60+ 的
  `Collection.update_note()` 替代（内部仍做降级兜底，保证不同小版本可用）。

模块装配顺序：config -> session_manager -> backend -> ui -> anki_hook
"""

from aqt import gui_hooks, mw

from .anki_hook import init_addon, shutdown_addon

# 场景一：Anki 启动时插件随 profile 一起加载 —— 由 hook 触发初始化
gui_hooks.profile_did_open.append(init_addon)
# 场景二：在 Anki 运行中被手动启用/重载 —— profile 已打开，需立即初始化
gui_hooks.profile_will_close.append(shutdown_addon)

if mw is not None and getattr(mw, "col", None) is not None:
    # 延迟到下一轮主循环，避免与 Anki 自身的初始化争抢（此时 reviewer 等尚未就绪）
    from aqt.qt import QTimer

    QTimer.singleShot(300, init_addon)
