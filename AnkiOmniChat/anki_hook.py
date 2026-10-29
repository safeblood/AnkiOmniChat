# -*- coding: utf-8 -*-
"""
anki_hook.py —— 与 Anki 的集成层。

职责：
    1. 创建侧边面板，并以 QDockWidget 停靠到主窗口（复习界面）或浏览窗口（Browse）；
       同一个面板实例在两个窗口间迁移（避免创建两个 WebEngine 实例）。
    2. 注册 hooks：翻卡 / 切卡 / 浏览界面选行 / 状态切换 / 右键菜单。
    3. 注册全局快捷键与「工具」菜单。
    4. 响应消息动作按钮：追加 / 覆盖卡片字段、复制。

稳定性优先：所有 hook 内部逻辑都做了异常兜底，任一环节出错不会影响 Anki 复习流程。
"""

from aqt import gui_hooks, mw
from aqt.qt import (
    QAction, QDockWidget, QKeySequence, QObject, QShortcut,
)
from aqt.utils import showInfo

from .config import Config
from .qt_compat import (
    APP_SHORTCUT, DOCK_CLOSABLE, DOCK_FLOATABLE, DOCK_MOVABLE, EVENT_CLOSE,
    HORIZONTAL, LEFT_DOCK, RIGHT_DOCK, WIDGET_CHILDREN_SHORTCUT,
)
from .session_manager import SessionManager, note_key
from .ui.actions import apply_to_field
from .ui.panel import ChatPanel
from .ui.settings import open_settings_dialog

_app = None
_hooks_registered = False


# ---------------------------------------------------------------------------
# 浏览窗口关闭守卫：窗口销毁前先把面板取回，避免 panel 被一起 delete
# ---------------------------------------------------------------------------
class _CloseGuard(QObject):
    def __init__(self, app, window):
        super().__init__(window)
        self._app = app
        self._window = window

    def eventFilter(self, obj, event):
        if obj is self._window and event.type() == EVENT_CLOSE:
            try:
                self._app.on_window_closing(self._window)
            except Exception:
                pass
        return False


# ---------------------------------------------------------------------------
# 应用主控
# ---------------------------------------------------------------------------
class OmniChatApp(QObject):
    def __init__(self):
        super().__init__(mw)
        self.cfg = Config().load()
        self.sessions = SessionManager(self.cfg, self)
        self.panel = ChatPanel(self.cfg, self.sessions)
        self.panel.get_note_id = self.current_note_id
        self.panel.get_note = self.current_note
        self.panel.actionRequested.connect(self.on_panel_action)
        self.panel.settingsRequested.connect(self.open_settings)

        self._dock = None
        self._dock_owner = None
        self._shortcuts = []
        self._menu_actions = []
        self._browser = None
        self._browser_guard = None
        self._last_note_id = None

        self._build_menu()
        self._build_shortcuts()
        self.attach_to(mw)

    # ---------------------------------------------------------------- 当前卡片
    @staticmethod
    def _card_note_id(card):
        """兼容不同小版本的 Card 对象（属性 or 数据库查询）。"""
        try:
            nid = getattr(card, "nid", None)
            if nid:
                return nid
        except Exception:
            pass
        try:
            row = mw.col.db.first("select nid from cards where id = ?", card.id)
            if row:
                return row[0]
        except Exception:
            pass
        return None

    def _browser_selected_note_id(self):
        browser = self._browser
        if browser is None:
            return None
        try:
            nids = browser.selectedNotes()
            if nids and len(nids) == 1:
                return nids[0]
        except Exception:
            pass
        return None

    def current_note_id(self):
        """当前上下文的 Note ID：复习界面优先，其次浏览界面选中项。"""
        try:
            reviewer = getattr(mw, "reviewer", None)
            if reviewer is not None:
                card = getattr(reviewer, "card", None)
                if card is not None:
                    nid = self._card_note_id(card)
                    if nid:
                        return nid
        except Exception:
            pass
        return self._browser_selected_note_id()

    def current_note(self):
        nid = self.current_note_id()
        if nid is None:
            return None
        try:
            return mw.col.get_note(nid)
        except Exception:
            return None

    @staticmethod
    def _note_title(note):
        if note is None:
            return ""
        try:
            for _, value in note.items():
                from .ui.actions import strip_html_keep_text
                text = strip_html_keep_text(value).strip()
                if text:
                    # 折叠所有空白（含换行）：字段常以代码围栏等多行内容开头，
                    # 不折叠的话标题里的换行会把面板标题栏撑成多行
                    text = " ".join(text.split())
                    return text[:40]
        except Exception:
            pass
        return ""

    # ---------------------------------------------------------------- 面板停靠
    def attach_to(self, window):
        """把面板挂载到指定窗口（mw 或 browser）的右侧。"""
        if window is None:
            return
        if self._dock is not None and self._dock_owner is window and self._dock.widget() is self.panel:
            self._dock.show()
            return

        self.detach()

        dock = QDockWidget("AnkiOmniChat", window)
        dock.setObjectName("AnkiOmniChatDock")
        try:
            features = None
            for flag in (DOCK_CLOSABLE, DOCK_MOVABLE, DOCK_FLOATABLE):
                if flag is None:
                    continue
                features = flag if features is None else (features | flag)
            if features is not None:
                dock.setFeatures(features)
        except Exception:
            pass
        dock.setAllowedAreas(LEFT_DOCK | RIGHT_DOCK)
        dock.setWidget(self.panel)

        area = LEFT_DOCK if self.cfg.get("general.dock_area") == "left" else RIGHT_DOCK
        try:
            window.addDockWidget(area, dock)
        except Exception:
            showInfo("AnkiOmniChat：无法挂载侧边栏")
            return

        self._dock = dock
        self._dock_owner = window
        try:
            self.panel.setMinimumWidth(int(self.cfg.get("general.panel_width", 400)))
            window.resizeDocks([dock], [int(self.cfg.get("general.panel_width", 400))], HORIZONTAL)
        except Exception:
            pass
        self.panel.show()

    def detach(self):
        """从当前窗口卸载面板（保留 panel 实例，不会被销毁）。"""
        dock = self._dock
        self._dock = None
        self._dock_owner = None
        if dock is None:
            return
        try:
            owner = dock.parent()
            if isinstance(owner, QObject) and hasattr(owner, "removeDockWidget"):
                owner.removeDockWidget(dock)
            dock.setWidget(None)
            dock.setParent(None)
            dock.deleteLater()
        except Exception:
            pass
        try:
            self.panel.setParent(None)
            self.panel.hide()
        except Exception:
            pass

    def on_window_closing(self, window):
        """窗口（通常是浏览窗口）即将关闭：先把面板取回主窗口。"""
        if self._dock_owner is window:
            self.detach()
            self._browser = None
            self._browser_guard = None
            self.attach_to(mw)

    def toggle_panel(self):
        """快捷键：显示 / 隐藏侧边栏。"""
        try:
            if self._dock is None:
                self.attach_to(self._browser or mw)
                return
            if self._dock.isVisible():
                self._dock.hide()
            else:
                # 若浏览窗口处于激活状态，则挂到浏览窗口
                target = self._browser if self._is_browser_active() else mw
                if self._dock_owner is not target:
                    self.attach_to(target)
                self._dock.show()
                self._dock.raise_()
        except Exception:
            pass

    def _is_browser_active(self):
        """浏览窗口是否处于激活状态（比 objectName 判断更可靠）。"""
        try:
            browser = self._browser
            if browser is None:
                return False
            return bool(browser.isVisible()) and bool(browser.isActiveWindow())
        except Exception:
            return False

    def show_panel(self):
        try:
            if self._dock is None:
                self.attach_to(mw)
            self._dock.show()
        except Exception:
            pass

    # ---------------------------------------------------------------- 菜单
    def _resolve_menu(self):
        """
        找到可挂载菜单项的容器：
        * 老版本：mw.form.menuTools（工具菜单）
        * 新版 Anki（25/26）：菜单结构重构，退回在菜单栏上建一个 "AnkiOmniChat" 菜单
        """
        try:
            menu = getattr(mw.form, "menuTools", None)
            if menu is not None:
                return menu
        except Exception:
            pass
        try:
            bar = getattr(mw.form, "menubar", None)
            if bar is None:
                bar = mw.menuBar()
            if bar is not None:
                return bar.addMenu("AnkiOmniChat")
        except Exception:
            pass
        return None

    def _build_menu(self):
        menu = self._resolve_menu()
        if menu is None:
            return

        act_toggle = QAction("AnkiOmniChat：显示/隐藏侧边栏", mw)
        act_toggle.triggered.connect(self.toggle_panel)
        act_inject = QAction("AnkiOmniChat：注入当前卡片", mw)
        act_inject.triggered.connect(lambda: self.panel.inject_card(auto=False))
        act_settings = QAction("AnkiOmniChat：设置", mw)
        act_settings.triggered.connect(self.open_settings)
        for act in (act_toggle, act_inject, act_settings):
            menu.addAction(act)
            self._menu_actions.append(act)

    def _build_shortcuts(self):
        """按配置重建快捷键（旧对象会被丢弃）。"""
        for sc in self._shortcuts:
            try:
                sc.setEnabled(False)
                sc.deleteLater()
            except Exception:
                pass
        self._shortcuts = []

        def register(seq, slot, widget=None, context=APP_SHORTCUT):
            seq = (seq or "").strip()
            if not seq:
                return
            try:
                sc = QShortcut(QKeySequence(seq), widget or mw)
                sc.setContext(context)
                sc.activated.connect(slot)
                self._shortcuts.append(sc)
            except Exception:
                pass

        register(self.cfg.get("shortcuts.toggle_panel", ""), self.toggle_panel)
        register(self.cfg.get("shortcuts.inject_card", ""),
                 lambda: self.panel.inject_card(auto=False))
        register(self.cfg.get("shortcuts.focus_input", ""), self.focus_input)
        register(self.cfg.get("shortcuts.cycle_prompt", ""),
                 lambda: self.panel.cycle_prompt(1))
        register(self.cfg.get("shortcuts.send", ""), self.panel.send,
                 widget=self.panel, context=WIDGET_CHILDREN_SHORTCUT)

    def focus_input(self):
        try:
            if self._dock is not None:
                self._dock.show()
            self.panel.set_mode("api")
            self.panel.focus_input()
        except Exception:
            pass

    def reload_for_profile(self):
        """
        切换到另一个 profile（或插件被重新加载）后的重建流程。

        顺序不能调换：
          1. 先 flush —— 此时 SessionManager 的落盘路径还指向「上一个」profile，
             未落盘的改动会回到它自己家里；
          2. 再 cfg.load() —— 这一步之后 data_dir 才切到新 profile；
          3. 最后 sessions.reload() —— 在新路径下重新读盘，并把步骤 1 之后
             可能排队的定时器停掉。

        少了第 3 步的话，内存里还是旧 profile 的会话字典，下一次自动落盘就会把整份
        历史写进新 profile 的 sessions.json。
        """
        try:
            self.sessions.flush()
        except Exception:
            pass
        try:
            self.cfg.load()
        except Exception:
            pass
        try:
            self.sessions.reload()
        except Exception:
            pass
        # 上一张卡属于旧 profile，别让去重判断把下一张卡误判成"没换卡"
        self._last_note_id = None
        # 会话字典已换成新 profile 的，按当前 key 重绘消息区（取不到就自然显示为空）
        try:
            self.panel.switch_session(self.panel.current_key)
        except Exception:
            pass
        self.apply_config()

    # ---------------------------------------------------------------- 设置
    def open_settings(self):
        open_settings_dialog(self.cfg, self.sessions, on_saved=self.apply_config, parent=mw)

    def apply_config(self):
        """设置保存后重新应用（快捷键、预设、面板宽度、模式、网页开关）。"""
        try:
            self._build_shortcuts()
            self.panel.refresh_presets()
            self.panel.refresh_prompts()
            self.panel.apply_web_flags()
            self.panel.set_mode(self.cfg.get("general.backend_mode", "web"))
            if self._dock is not None and self._dock_owner is not None:
                try:
                    self._dock_owner.resizeDocks(
                        [self._dock], [int(self.cfg.get("general.panel_width", 400))], HORIZONTAL
                    )
                except Exception:
                    pass
        except Exception:
            pass

    # ---------------------------------------------------------------- 动作按钮
    def on_panel_action(self, action, msg_id):
        """处理消息区动作按钮（来自 WebView 的 ankiomni:// 链接）。"""
        try:
            msg = self.sessions.message_by_id(self.panel.current_key, msg_id)
            content = (msg or {}).get("content", "")
            if action == "copy":
                self.panel.copy_message(msg_id)
                return
            if action in ("append", "overwrite"):
                nid = self.current_note_id() or self._last_note_id
                # content_format 留空 -> 读配置项 general.write_format。
                # 会话里存的是 AI 回答的 Markdown 源码，默认按源码转义写入。
                apply_to_field(nid, content, "overwrite" if action == "overwrite" else "append")
                return
        except Exception:
            pass

    # ---------------------------------------------------------------- 会话切换
    def sync_session_to_note(self, note_id, auto_inject=False):
        if note_id is None:
            return
        self._last_note_id = note_id
        if not self.cfg.get("general.auto_switch_session", True):
            return
        note = None
        try:
            note = mw.col.get_note(note_id)
        except Exception:
            note = None
        self.panel.switch_session(note_key(note_id), title=self._note_title(note))
        if auto_inject and self.cfg.get("general.auto_inject_on_show_answer", True):
            try:
                self.panel.inject_card(auto=True)
            except Exception:
                pass

    # ---------------------------------------------------------------- 生命周期
    def shutdown(self):
        try:
            self.sessions.flush()
        except Exception:
            pass
        self.detach()


# ---------------------------------------------------------------------------
# Hook 实现（通过全局 _app 转发，保证重复注册也安全）
# ---------------------------------------------------------------------------

def _on_reviewer_question(card):
    if _app is None:
        return
    try:
        nid = OmniChatApp._card_note_id(card)
        _app.sync_session_to_note(nid, auto_inject=False)
    except Exception:
        pass


def _on_reviewer_answer(card):
    """翻卡（显示答案）时：切换会话 + 按需自动注入。"""
    if _app is None:
        return
    try:
        nid = OmniChatApp._card_note_id(card)
        _app.sync_session_to_note(nid, auto_inject=True)
    except Exception:
        pass


def _on_state_change(new_state, old_state):
    if _app is None:
        return
    try:
        if new_state == "review" and _app.cfg.get("general.auto_show_panel_in_review", True):
            _app.show_panel()
    except Exception:
        pass


def _on_browser_will_show(browser):
    if _app is None:
        return
    try:
        _app._browser = browser
        _app._browser_guard = _CloseGuard(_app, browser)
        browser.installEventFilter(_app._browser_guard)
        _app.attach_to(browser)
        # 选行变化：优先用官方 hook，否则按不同版本的 selection model 逐个尝试
        model = None
        table = getattr(browser, "table", None)
        for getter in (
            lambda: table.selectionModel() if table is not None else None,
            lambda: getattr(table, "_selection_model", None),
            lambda: getattr(table, "selection_model", None),
        ):
            try:
                model = getter()
            except Exception:
                model = None
            if model is not None:
                break
        if model is not None:
            try:
                model.selectionChanged.connect(lambda *_: _on_browser_row_changed(browser))
            except Exception:
                pass
        _on_browser_row_changed(browser)
    except Exception:
        pass


def _on_browser_row_changed(browser):
    if _app is None:
        return
    try:
        nids = browser.selectedNotes()
        if not nids:
            return
        nid = nids[0]
        if nid == _app._last_note_id:
            return
        _app.sync_session_to_note(nid, auto_inject=False)
    except Exception:
        pass


def _on_reviewer_menu(reviewer, menu):
    if _app is None:
        return
    try:
        act = QAction("注入当前卡片到 AnkiOmniChat", menu)
        act.triggered.connect(lambda: _app.panel.inject_card(auto=False))
        menu.addAction(act)
    except Exception:
        pass


def _on_browser_menu(browser, menu):
    if _app is None:
        return
    try:
        act = QAction("用 AnkiOmniChat 打开选中卡片", menu)
        act.triggered.connect(lambda: _on_browser_row_changed(browser))
        menu.addAction(act)
    except Exception:
        pass


def _register_hooks():
    """只注册一次的 hooks。"""
    global _hooks_registered
    if _hooks_registered:
        return
    _hooks_registered = True

    gui_hooks.reviewer_did_show_question.append(_on_reviewer_question)
    gui_hooks.reviewer_did_show_answer.append(_on_reviewer_answer)
    gui_hooks.state_did_change.append(_on_state_change)
    gui_hooks.browser_will_show.append(_on_browser_will_show)

    # 以下 hooks 在不同小版本中存在性不一致，存在才注册
    if hasattr(gui_hooks, "browser_did_change_row"):
        gui_hooks.browser_did_change_row.append(_on_browser_row_changed)
    if hasattr(gui_hooks, "reviewer_will_show_context_menu"):
        gui_hooks.reviewer_will_show_context_menu.append(_on_reviewer_menu)
    if hasattr(gui_hooks, "browser_will_show_context_menu"):
        gui_hooks.browser_will_show_context_menu.append(_on_browser_menu)


# ---------------------------------------------------------------------------
# 对外入口
# ---------------------------------------------------------------------------

def init_addon():
    """插件初始化入口（profile_did_open 或手动启用时调用，可重复调用）。"""
    global _app
    _register_hooks()
    try:
        if _app is None:
            _app = OmniChatApp()
        else:
            # 切换 profile / 重载插件：按顺序重新读配置与会话
            _app.reload_for_profile()
        return _app
    except Exception as e:
        try:
            showInfo("AnkiOmniChat 初始化失败：%s\n\n请检查工具 → 插件 → 查看日志。" % e)
        except Exception:
            pass
        return None


def shutdown_addon():
    if _app is not None:
        try:
            _app.shutdown()
        except Exception:
            pass


def get_app():
    return _app
