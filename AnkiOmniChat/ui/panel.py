# -*- coding: utf-8 -*-
"""
panel.py —— 侧边面板主体（OmniChat 布局）。

    ┌──────────────────────────────────────────┐
    │ AnkiOmniChat   [会话标题]   ⚙ 清空 折叠  │   <- 标题栏
    │ [ 网页模式 | API 模式 ]                   │   <- 模式切换
    ├──────────────────────────────────────────┤
    │ 消息区（Markdown + LaTeX，流式输出）      │
    ├──────────────────────────────────────────┤
    │ 网页模式：网页视图 + 粘贴/抓取按钮        │
    │ API 模式：输入框 + 发送/停止/注入按钮     │
    ├──────────────────────────────────────────┤
    │ 状态栏                                    │
    └──────────────────────────────────────────┘
"""

from aqt.qt import (
    QButtonGroup, QHBoxLayout, QLabel, QPushButton, QSplitter, QStackedWidget,
    QTextEdit, QTimer, QToolButton, QVBoxLayout, QApplication, QWidget, pyqtSignal,
)
from aqt.utils import tooltip

from ..backend import ApiBackend
from ..qt_compat import (
    CTRL_MOD, KEY_ENTER, KEY_RETURN, PLAIN_TEXT, SHIFT_MOD, TEXT_SELECTABLE,
    TEXTCURSOR_END, VERTICAL,
)
from ..session_manager import FREE_KEY
from . import markdown
from .actions import build_card_text, copy_text
from .chat_view import ChatView
from .web_panel import WebPanel


class _InputBox(QTextEdit):
    """输入框：Enter 发送（Ctrl+Enter 亦发送），Shift+Enter 换行。"""

    sendRequested = pyqtSignal()

    def keyPressEvent(self, event):
        try:
            key = event.key()
            mod = event.modifiers()
            if key in (KEY_RETURN, KEY_ENTER):
                ctrl = bool(mod & CTRL_MOD) if CTRL_MOD is not None else False
                shift = bool(mod & SHIFT_MOD) if SHIFT_MOD is not None else False
                if ctrl or not shift:
                    self.sendRequested.emit()
                    return
        except Exception:
            pass
        super().keyPressEvent(event)


class ChatPanel(QWidget):
    """侧边面板：会话展示 + 双后端切换 + 注入 + 动作按钮。"""

    actionRequested = pyqtSignal(str, str)   # (append/overwrite/copy, message_id)
    settingsRequested = pyqtSignal()

    def __init__(self, cfg, sessions, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.sessions = sessions
        self.current_key = FREE_KEY
        self.get_note_id = lambda: None   # 由 anki_hook 注入：返回当前 Note ID
        self.get_note = lambda: None      # 由 anki_hook 注入：返回当前 Note 对象

        self._stream_buf = ""
        self._streaming = False
        self._collapsed = False

        self.api = ApiBackend(cfg, self)
        self.api.chunkReceived.connect(self._on_chunk)
        self.api.finished.connect(self._on_finished)
        self.api.errorOccurred.connect(self._on_error)

        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(90)
        self._flush_timer.timeout.connect(self._flush_stream)

        self._build_ui()
        self.set_mode(self.cfg.get("general.backend_mode", "web"))
        self.switch_session(FREE_KEY)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)
        root.setSpacing(3)

        # ---- 标题栏 ----
        header = QHBoxLayout()
        self.title_label = QLabel("<b>OmniChat</b>", self)
        self.session_label = QLabel("自由会话", self)
        self.session_label.setToolTip("当前会话（以 Note ID 为 key，切换卡片自动切换）")
        self.session_label.setTextInteractionFlags(TEXT_SELECTABLE)
        # 强制纯文本：卡片名可能含 < > &（HTML 残留或数学式），不能让 QLabel 当富文本解析
        if PLAIN_TEXT is not None:
            self.session_label.setTextFormat(PLAIN_TEXT)
        self.btn_settings = QPushButton("设置", self)
        self.btn_clear = QPushButton("清空", self)
        self.btn_collapse = QPushButton("折叠", self)
        header.addWidget(self.title_label)
        header.addWidget(self.session_label, 1)
        header.addWidget(self.btn_settings)
        header.addWidget(self.btn_clear)
        header.addWidget(self.btn_collapse)
        root.addLayout(header)

        # ---- 模式切换 ----
        mode_bar = QHBoxLayout()
        self.btn_mode_web = QToolButton(self)
        self.btn_mode_web.setText("网页模式")
        self.btn_mode_web.setCheckable(True)
        self.btn_mode_api = QToolButton(self)
        self.btn_mode_api.setText("API 模式")
        self.btn_mode_api.setCheckable(True)
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_group.addButton(self.btn_mode_web, 0)
        self.mode_group.addButton(self.btn_mode_api, 1)
        mode_bar.addWidget(self.btn_mode_web)
        mode_bar.addWidget(self.btn_mode_api)
        mode_bar.addStretch(1)
        root.addLayout(mode_bar)

        # ---- 主体：上消息区 / 下模式区 ----
        self.splitter = QSplitter(VERTICAL, self)
        self.chat_view = ChatView(self.cfg, self)
        self.chat_view.actionRequested.connect(self.actionRequested)
        self.splitter.addWidget(self.chat_view)

        self.bottom = QStackedWidget(self)
        # 页面 0：API 输入区
        self.api_page = QWidget(self)
        api_layout = QVBoxLayout(self.api_page)
        api_layout.setContentsMargins(0, 0, 0, 0)
        self.input_box = _InputBox(self.api_page)
        self.input_box.setPlaceholderText("输入问题…（Enter 发送 / Shift+Enter 换行）")
        self.input_box.setMinimumHeight(70)
        self.input_box.setMaximumHeight(220)
        self.input_box.sendRequested.connect(self.send)
        api_row = QHBoxLayout()
        self.btn_send = QPushButton("发送", self.api_page)
        self.btn_stop = QPushButton("停止", self.api_page)
        self.btn_inject = QPushButton("注入卡片", self.api_page)
        self.btn_stop.setEnabled(False)
        api_row.addWidget(self.btn_send)
        api_row.addWidget(self.btn_stop)
        api_row.addWidget(self.btn_inject)
        api_row.addStretch(1)
        api_layout.addWidget(self.input_box, 1)
        api_layout.addLayout(api_row)

        # 页面 1：网页模式
        self.web_page = WebPanel(self.cfg, self)
        self.web_page.replyScraped.connect(self._on_reply_scraped)
        # 网页模式点『粘贴卡片到输入框』时若无缓存，直接从当前卡片取
        def _current_card_text():
            note = self.get_note()
            return build_card_text(note, self.cfg) if note is not None else ""
        self.web_page.note_provider = _current_card_text

        self.bottom.addWidget(self.api_page)
        self.bottom.addWidget(self.web_page)
        self.splitter.addWidget(self.bottom)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 4)
        root.addWidget(self.splitter, 1)

        # ---- 状态栏 ----
        self.status_label = QLabel("", self)
        self.status_label.setStyleSheet("color:#888;font-size:11px;")
        root.addWidget(self.status_label)

        self.btn_settings.clicked.connect(self.settingsRequested.emit)
        self.btn_clear.clicked.connect(self.clear_session)
        self.btn_collapse.clicked.connect(self.toggle_collapsed)
        self.btn_send.clicked.connect(self.send)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_inject.clicked.connect(lambda: self.inject_card(auto=False))
        self.btn_mode_web.clicked.connect(lambda: self.set_mode("web"))
        self.btn_mode_api.clicked.connect(lambda: self.set_mode("api"))

    # ------------------------------------------------------------------ 状态
    def set_status(self, text):
        self.status_label.setText(text or "")

    def set_collapsed(self, collapsed):
        self._collapsed = collapsed
        self.splitter.setVisible(not collapsed)
        self.btn_collapse.setText("展开" if collapsed else "折叠")

    def toggle_collapsed(self):
        self.set_collapsed(not self._collapsed)

    def set_mode(self, mode):
        mode = "api" if mode == "api" else "web"
        self.cfg.set("general.backend_mode", mode)
        self.bottom.setCurrentIndex(1 if mode == "web" else 0)
        self.btn_mode_web.blockSignals(True)
        self.btn_mode_api.blockSignals(True)
        self.btn_mode_web.setChecked(mode == "web")
        self.btn_mode_api.setChecked(mode == "api")
        self.btn_mode_web.blockSignals(False)
        self.btn_mode_api.blockSignals(False)
        if mode == "api":
            self.set_status("API 模式：%s" % (self.cfg.get("api.model") or "未配置模型"))
        else:
            preset = self.cfg.active_preset() or {}
            self.set_status("网页模式：%s（免费网页，自行登录）" % (preset.get("name") or "自定义"))
        if mode == "api":
            self.input_box.setFocus()

    def refresh_presets(self):
        self.web_page.refresh_presets()
        self.set_mode(self.cfg.get("general.backend_mode", "web"))
        # 设置里改动过预设后，把网址同步过去
        self.web_page.apply_active_preset()

    def apply_web_flags(self):
        """设置保存后把网页模式的开关同步到控件（如『发送』按钮的可用状态）。"""
        try:
            self.web_page.refresh_flags()
        except Exception:
            pass

    # ------------------------------------------------------------------ 会话
    def switch_session(self, key, title=""):
        """切换会话（不同卡片 = 不同 key，历史互相隔离）。"""
        key = key or FREE_KEY
        self.current_key = key
        if title:
            self.sessions.set_title(key, title)
        self.session_label.setText(self._session_display())
        self.chat_view.set_messages(
            self.sessions.messages(key),
            empty_hint="本卡片还没有对话。按 Ctrl+Alt+I 注入卡片内容，然后提问。",
        )
        self.chat_view.scroll_bottom()

    def _session_display(self):
        t = self.sessions.title(self.current_key)
        if self.current_key == FREE_KEY:
            return "自由会话（未绑定卡片）"
        if t:
            # 兜底再折叠一次空白（历史会话的标题可能是旧数据，仍带换行）
            t = " ".join(t.split())
            return "卡片：%s" % self._elide(t, 28)
        return "卡片：%s" % self.current_key.replace("note:", "")

    @staticmethod
    def _elide(text, limit):
        """截断并补省略号，避免标题撑破标题栏。"""
        if len(text) <= limit:
            return text
        return text[:limit].rstrip() + "…"

    def clear_session(self):
        self.sessions.clear(self.current_key)
        self.chat_view.set_messages([], empty_hint="会话已清空")
        tooltip("当前会话已清空")

    # ------------------------------------------------------------------ 注入
    def inject_card(self, auto=False):
        """把当前卡片全部字段注入（API 模式写入输入框；网页模式复制到网页输入框）。"""
        note = self.get_note()
        if note is None:
            if not auto:
                tooltip("没有可用卡片（请在复习界面或浏览界面选中一张卡片）")
            return False
        text = build_card_text(note, self.cfg)
        if not text.strip():
            if not auto:
                tooltip("卡片内容为空")
            return False
        return self.inject_text(text, auto=auto)

    def inject_text(self, text, auto=False):
        mode = self.cfg.get("general.backend_mode", "web")
        if mode == "web":
            auto_paste = bool(self.cfg.get("web.auto_paste_on_inject", False))
            # 记录到历史，便于回看"当时问了什么"
            self.sessions.add_message(self.current_key, "note", text)
            self.chat_view.set_messages(self.sessions.messages(self.current_key))
            self.chat_view.scroll_bottom()
            self.web_page.set_pending_text(text)
            if auto_paste or not auto:
                # 手动点击按钮 或 显式开启自动粘贴：写入网页输入框
                self.web_page.paste_text(text)
            else:
                # 翻卡自动注入：默认只复制到剪贴板，避免打断用户阅读
                try:
                    QApplication.clipboard().setText(text)
                except Exception:
                    pass
                self.set_status("已复制卡片内容到剪贴板（点『粘贴卡片到输入框』写入网页）")
            return True

        # API 模式：追加到输入框，由用户确认后发送
        cur = self.input_box.toPlainText().rstrip()
        merged = (cur + "\n\n" + text) if cur else text
        self.input_box.setPlainText(merged)
        if TEXTCURSOR_END is not None:
            self.input_box.moveCursor(TEXTCURSOR_END)
        self.input_box.setFocus()
        self.set_status("已注入卡片内容，确认后发送")
        return True

    # ------------------------------------------------------------------ 发送
    def send(self):
        text = self.input_box.toPlainText().strip()
        if not text:
            tooltip("请输入内容")
            return

        mode = self.cfg.get("general.backend_mode", "web")
        if mode == "web":
            # 网页模式：记录提问 + 粘贴到网页输入框（不自动发送）
            self.sessions.add_message(self.current_key, "user", text)
            self.chat_view.set_messages(self.sessions.messages(self.current_key))
            self.chat_view.scroll_bottom()
            self.input_box.clear()
            self.web_page.paste_text(text)
            return

        # API 模式：流式请求
        if self.api.is_busy():
            tooltip("正在生成中，请稍候或点『停止』")
            return
        self.input_box.clear()
        self.sessions.add_message(self.current_key, "user", text)
        self.chat_view.set_messages(self.sessions.messages(self.current_key))
        self.chat_view.scroll_bottom()

        messages = self._build_request_messages(text)
        self._stream_buf = ""
        self._streaming = True
        self.btn_send.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.chat_view.set_typing(True)
        if not self.api.send(messages):
            self._streaming = False
            self.btn_send.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.chat_view.set_typing(False)

    def _build_request_messages(self, user_text):
        """系统提示 + 卡片上下文 + 最近历史。"""
        api = self.cfg.get("api", {}) or {}
        out = []
        system = (api.get("system_prompt") or "").strip()
        if system:
            out.append({"role": "system", "content": system})

        # 卡片上下文（不显示在消息区，只随请求发送）
        if self.cfg.get("general.always_attach_card_context", True):
            note = self.get_note()
            if note is not None:
                ctx = build_card_text(note, self.cfg)
                if ctx.strip() and ctx.strip()[:60] not in user_text:
                    out.append({
                        "role": "user",
                        "content": ctx + "\n\n（以上是当前卡片内容，请据此回答我的问题。）",
                    })

        limit = int(self.cfg.get("general.history_limit", 20) or 20)
        for m in self.sessions.last_messages(self.current_key, limit):
            role = m.get("role")
            if role not in ("user", "assistant"):
                continue
            out.append({"role": role, "content": m.get("content", "")})
        return out

    def stop(self):
        self.api.cancel()
        self._streaming = False
        self._flush_timer.stop()
        self.btn_send.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.chat_view.set_typing(False)
        self.set_status("已停止")

    # ------------------------------------------------------------------ 流式
    def _on_chunk(self, text):
        if not self._streaming:
            self._streaming = True
            self.chat_view.set_typing(True)
        self._stream_buf += text or ""
        if not self._flush_timer.isActive():
            self._flush_timer.start()

    def _flush_stream(self):
        if not self._streaming:
            self._flush_timer.stop()
            return
        html = markdown.render_markdown(self._stream_buf)
        self.chat_view.set_stream(html, done=False)

    def _on_finished(self, text):
        self._flush_timer.stop()
        self._streaming = False
        self.btn_send.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.chat_view.set_typing(False)
        self.chat_view.clear_stream()

        content = (text or self._stream_buf or "").strip()
        if content:
            self.sessions.add_message(self.current_key, "assistant", content)
        self._stream_buf = ""
        self.chat_view.set_messages(self.sessions.messages(self.current_key))
        self.chat_view.scroll_bottom()
        self.set_status("完成 · %d 字" % len(content))

    def _on_error(self, message):
        # 已生成的部分内容也保存，避免丢失
        if self._stream_buf.strip():
            self.sessions.add_message(self.current_key, "assistant", self._stream_buf.strip())
            self._stream_buf = ""
            self.chat_view.set_messages(self.sessions.messages(self.current_key))
        self.stop()
        self.set_status("错误：%s" % (message or ""))
        tooltip("请求失败：%s" % (message or "未知错误"))

    # ------------------------------------------------------------------ 其它
    def _on_reply_scraped(self, text):
        """网页模式：把抓到的回复保存为一条 AI 消息（便于后续写入卡片）。"""
        self.sessions.add_message(self.current_key, "assistant", text)
        self.chat_view.set_messages(self.sessions.messages(self.current_key))
        self.chat_view.scroll_bottom()
        self.set_status("已保存网页回复到当前会话")

    def focus_input(self):
        self.input_box.setFocus()

    def copy_message(self, msg_id):
        """供 anki_hook 调用：按消息 id 取文本并复制。"""
        msg = self.sessions.message_by_id(self.current_key, msg_id)
        if msg is None:
            return False
        return copy_text(msg.get("content", ""))
