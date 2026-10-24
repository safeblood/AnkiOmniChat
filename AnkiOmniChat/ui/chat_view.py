# -*- coding: utf-8 -*-
"""
chat_view.py —— 消息区视图（QWebEngineView 封装）。

职责：
    * 载入本地生成的 chat.html
    * 渲染整个会话（Markdown + LaTeX）
    * 流式输出：主线程定时把累积文本重绘到"流式气泡"
    * 拦截 ankiomni:// 自定义协议，把消息动作按钮的点击回调给 Python

不使用 QWebChannel（需要额外 websocket 传输层），改用自定义协议 + 导航拦截，
更轻量且在所有目标版本上行为一致。
"""

import json
import time

from aqt.qt import (
    QDesktopServices, QLabel, QSize, QUrl, QVBoxLayout, QWidget, pyqtSignal,
)

from ..qt_compat import (
    QWebEnginePage, QWebEngineProfile, QWebEngineView, nav_type_link_clicked,
    set_web_attr, web_engine_available,
)
from . import markdown
from .chat_page import ensure_chat_html

CUSTOM_SCHEME = "ankiomni"


class _ChatPage(QWebEnginePage):
    """消息页：拦截自定义协议与外部链接。"""

    actionRequested = pyqtSignal(str, str)  # (action, message_id)

    def acceptNavigationRequest(self, url, nav_type, isMainFrame):
        try:
            scheme = (url.scheme() or "").lower()
            if scheme == CUSTOM_SCHEME:
                # ankiomni://copy?mid=xxxx
                # 自定义协议下不同 Qt 版本对 authority/path 的解析略有差异，两者都取
                path = (url.path() or "").strip("/")
                if not path:
                    path = (url.authority() or url.host() or "").strip("/")
                parts = path.split("/")
                action = parts[0] if parts else ""
                msg_id = ""
                q = url.query()
                if q:
                    for kv in q.split("&"):
                        if "=" in kv:
                            k, v = kv.split("=", 1)
                            if k == "mid":
                                msg_id = v
                self.actionRequested.emit(action, msg_id)
                return False
            if scheme in ("http", "https") and nav_type == nav_type_link_clicked():
                QDesktopServices.openUrl(url)
                return False
        except Exception:
            pass
        try:
            return super().acceptNavigationRequest(url, nav_type, isMainFrame)
        except Exception:
            return True


class ChatView(QWidget):
    """消息列表 + 流式渲染。"""

    actionRequested = pyqtSignal(str, str)  # (action, message_id)

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._ready = False
        self._pending = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if web_engine_available():
            self.profile = self._make_profile()
            self.view = QWebEngineView(self)
            self.page = _ChatPage(self.profile, self.view)
            self.view.setPage(self.page)
            self.page.actionRequested.connect(self.actionRequested)
            self.page.loadFinished.connect(self._on_load_finished)
            layout.addWidget(self.view)
            self.view.setMinimumHeight(120)
            self.load()
        else:
            # 极端环境（没有 QtWebEngine）：退化为纯文本标签，保证插件不炸
            self.profile = None
            self.view = None
            self.page = None
            layout.addWidget(QLabel("当前环境没有可用的 QtWebEngine，消息区不可用。", self))

    # ------------------------------------------------------------------ 初始化
    def _make_profile(self):
        """独立 profile：不污染 Anki 主 webview，同时允许加载本地文件与 CDN。"""
        try:
            prof = QWebEngineProfile("AnkiOmniChatChat", self)
        except Exception:
            prof = QWebEngineProfile.defaultProfile()
        try:
            settings = prof.settings()
            set_web_attr(settings, "LocalContentCanAccessFileUrls", True)
            set_web_attr(settings, "LocalContentCanAccessRemoteUrls", True)
            set_web_attr(settings, "LocalStorageEnabled", True)
            set_web_attr(settings, "JavascriptEnabled", True)
            set_web_attr(settings, "ErrorPageEnabled", False)
        except Exception:
            pass
        return prof

    def load(self):
        if self.view is None:
            return
        path = ensure_chat_html(self.cfg, night=self._is_night())
        if path:
            self.view.setUrl(QUrl.fromLocalFile(path))
        else:
            # 兜底：直接 setHtml（此时 LaTeX 走 CDN 或原样显示）
            self.view.setHtml("<html><body><div id='messages'></div>"
                              "<div id='typing'></div></body></html>")

    def _is_night(self):
        """夜间模式判断：不同版本分别提供 pm.night_mode() 与 theme_manager.night_mode。"""
        try:
            from aqt import mw
            if mw is None:
                return False
            fn = getattr(mw.pm, "night_mode", None)
            if callable(fn):
                try:
                    return bool(fn())
                except Exception:
                    pass
            try:
                from aqt.theme import theme_manager
                value = getattr(theme_manager, "night_mode", None)
                if value is not None:
                    return bool(value() if callable(value) else value)
            except Exception:
                pass
        except Exception:
            pass
        return False

    def _on_load_finished(self, ok):
        if self.page is None:
            return
        self._ready = bool(ok)
        self._run_js("__aoc.setTheme(%s)" % ("true" if self._is_night() else "false"))
        for js in self._pending:
            self.page.runJavaScript(js)
        self._pending = []

    def _run_js(self, js):
        if self.page is None:
            return
        if not self._ready:
            self._pending.append(js)
            return
        try:
            self.page.runJavaScript(js)
        except Exception:
            pass

    # ------------------------------------------------------------------ 渲染
    def set_messages(self, messages, empty_hint=""):
        html = render_messages_html(messages)
        self._run_js("__aoc.setMessages(%s, %s)" % (json.dumps(html), json.dumps(empty_hint)))

    def set_stream(self, html, done=False):
        self._run_js("__aoc.setStream(%s, %s)" % (json.dumps(html), "true" if done else "false"))

    def clear_stream(self):
        self._run_js("__aoc.clearStream()")

    def set_typing(self, on):
        self._run_js("__aoc.setTyping(%s)" % ("true" if on else "false"))

    def scroll_bottom(self):
        self._run_js("__aoc.scrollToBottom()")

    def reload_page(self):
        self._ready = False
        self.load()

    def sizeHint(self):
        return QSize(360, 320)


# ---------------------------------------------------------------------------
# 消息 -> HTML
# ---------------------------------------------------------------------------

def _time_str(ts):
    try:
        return time.strftime("%H:%M", time.localtime(float(ts)))
    except Exception:
        return ""


def _action_bar(msg_id):
    """AI 消息下方的动作按钮：追加 / 覆盖 / 复制。"""
    items = [
        ("append", "追加到卡片字段"),
        ("overwrite", "覆盖卡片字段"),
        ("copy", "复制"),
    ]
    links = []
    for action, label in items:
        links.append(
            '<a href="%s://%s?mid=%s" title="%s">%s</a>'
            % (CUSTOM_SCHEME, action, msg_id, label, label)
        )
    return '<div class="acts">%s</div>' % "".join(links)


def render_messages_html(messages):
    """把会话消息列表渲染为消息区 HTML。"""
    out = []
    for msg in messages or []:
        role = msg.get("role", "user")
        content = msg.get("content", "") or ""
        body = markdown.render_markdown(content)
        mid = msg.get("id", "")
        cls = {"user": "user", "assistant": "assistant"}.get(role, "note")
        out.append('<div class="msg %s">' % cls)
        out.append('<div class="bubble">%s</div>' % body)
        out.append('<div class="meta">%s</div>' % _time_str(msg.get("ts", 0)))
        if cls == "assistant" and mid:
            out.append(_action_bar(mid))
        out.append("</div>")
    return "".join(out)
