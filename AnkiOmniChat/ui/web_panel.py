# -*- coding: utf-8 -*-
"""
web_panel.py —— 模式 A（WebView 内嵌免费网页）。

要点：
    * 使用独立的 QWebEngineProfile 并开启持久化 cookie 存储，
      用户在内置浏览器里登录一次后，重启 Anki 仍保持登录（cookie 只保存在本地，
      插件不会读取或上传任何凭证）。
    * 「粘贴到输入框」优先用原生事件写入（兼容 React / Vue 受控组件），
      失败则退回剪贴板；默认只粘贴、不发送（auto_send 默认关闭）。
    * 「抓取回复」是尽力而为功能：站点改版后可能失效，抓不到就提示用户手动复制。
"""

import os

from aqt.qt import (
    QApplication, QComboBox, QDesktopServices, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QSize, QUrl, QVBoxLayout, QWidget, pyqtSignal,
)
from aqt.utils import tooltip

from ..backend import WebBackend
from ..config import data_dir
from ..qt_compat import (
    QWebEnginePage, QWebEngineProfile, QWebEngineView, persistent_cookie_policy,
    set_web_attr, web_engine_available,
)

_PROFILE = None  # QWebEngineProfile 单例：整个进程只创建一次


def get_profile(cfg, parent=None):
    """创建（或复用）用于网页登录态的持久化 profile。"""
    global _PROFILE
    if not web_engine_available():
        return None
    if _PROFILE is not None:
        if parent is not None:
            try:
                _PROFILE.setParent(parent)
            except Exception:
                pass
        return _PROFILE

    try:
        prof = QWebEngineProfile("AnkiOmniChatWeb", parent)
    except Exception:
        prof = QWebEngineProfile.defaultProfile()

    storage = os.path.join(data_dir(cfg), "webprofile")
    try:
        os.makedirs(storage, exist_ok=True)
    except Exception:
        pass
    try:
        prof.setPersistentStoragePath(storage)
    except Exception:
        pass
    try:
        prof.setCachePath(os.path.join(storage, "cache"))
    except Exception:
        pass
    pol = persistent_cookie_policy()
    if pol is not None:
        try:
            prof.setPersistentCookiesPolicy(pol)
        except Exception:
            pass
    try:
        ua = (cfg.get("web.custom_user_agent") or "").strip()
        if ua:
            prof.setHttpUserAgent(ua)
    except Exception:
        pass
    try:
        settings = prof.settings()
        set_web_attr(settings, "LocalStorageEnabled", True)
        set_web_attr(settings, "JavascriptEnabled", True)
        set_web_attr(settings, "JavascriptCanOpenWindows", True)
        set_web_attr(settings, "LocalContentCanAccessRemoteUrls", True)
    except Exception:
        pass

    _PROFILE = prof
    return prof


class WebPanel(QWidget):
    """网页模式视图：地址栏 + 预设 + 网页本体 + 常用动作按钮。"""

    replyScraped = pyqtSignal(str)   # 抓取到的网页回复文本
    urlChanged = pyqtSignal(str)

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.backend = WebBackend(cfg)

        root = QVBoxLayout(self)
        root.setContentsMargins(2, 2, 2, 2)
        root.setSpacing(3)

        # ---- 第一行：预设 / 地址 / 打开 ----
        row1 = QHBoxLayout()
        self.preset_combo = QComboBox(self)
        self.preset_combo.setToolTip("内置免费网页入口（豆包 / Kimi / DeepSeek / 自定义）")
        self.url_edit = QLineEdit(self)
        self.url_edit.setPlaceholderText("网页地址，例如 https://www.doubao.com/chat/")
        self.btn_go = QPushButton("打开", self)
        self.btn_reload = QPushButton("刷新", self)
        row1.addWidget(self.preset_combo, 0)
        row1.addWidget(self.url_edit, 1)
        row1.addWidget(self.btn_go, 0)
        row1.addWidget(self.btn_reload, 0)
        root.addLayout(row1)

        # ---- 第二行：粘贴 / 抓取 / 登录提示 ----
        row2 = QHBoxLayout()
        self.btn_paste = QPushButton("粘贴卡片到输入框", self)
        self.btn_paste.setToolTip("把当前（或最近注入的）卡片文本写入网页输入框，不会自动发送")
        self.btn_scrape = QPushButton("抓取网页回复", self)
        self.btn_scrape.setToolTip("尽力读取网页上最后一条回复，失败时请在网页里手动复制")
        self.btn_send = QPushButton("发送", self)
        self.btn_send.setToolTip("点击网页上的发送按钮（默认关闭，需自行承担风险）")
        self.btn_send.setEnabled(bool(cfg.get("web.auto_send", False)))
        self.btn_external = QPushButton("外部打开", self)
        self.btn_external.setToolTip(
            "内嵌浏览器被站点拦截时，用系统默认浏览器打开当前网址（登录态不与内嵌浏览器共享）"
        )
        row2.addWidget(self.btn_paste)
        row2.addWidget(self.btn_scrape)
        row2.addWidget(self.btn_send)
        row2.addWidget(self.btn_external)
        row2.addStretch(1)
        root.addLayout(row2)

        # ---- 网页本体 ----
        if web_engine_available():
            self.view = QWebEngineView(self)
            self.page = QWebEnginePage(get_profile(cfg, self), self.view)
            self.view.setPage(self.page)
            root.addWidget(self.view, 1)
        else:
            self.view = None
            self.page = None
            root.addWidget(QLabel("当前环境没有可用的 QtWebEngine，网页模式不可用，请改用 API 模式。", self))

        self.btn_go.clicked.connect(self.open_current_url)
        self.btn_reload.clicked.connect(self.reload)
        self.btn_paste.clicked.connect(lambda: self.paste_text(self._last_text))
        self.btn_scrape.clicked.connect(self.scrape_reply)
        self.btn_send.clicked.connect(self.click_send)
        self.btn_external.clicked.connect(self.open_external)
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        if self.page is not None:
            self.page.urlChanged.connect(lambda u: self.urlChanged.emit(u.toString()))
            self.page.loadFinished.connect(self._on_load_finished)

        self._last_text = ""
        # 由 ChatPanel 注入：返回当前卡片文本，用于待粘贴区为空时兜底
        self.note_provider = lambda: ""
        self.refresh_presets()
        self.open_preset(self.cfg.active_preset(), auto=True)

    def reload(self):
        if self.view is not None:
            self.view.reload()

    # ------------------------------------------------------------------ 预设
    def refresh_presets(self):
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        for p in self.cfg.web_presets():
            self.preset_combo.addItem(p.get("name") or p.get("id") or "未命名", p.get("id"))
        active = self.cfg.get("web.active_preset")
        idx = self.preset_combo.findData(active)
        if idx < 0 and self.preset_combo.count():
            idx = 0
        if idx >= 0:
            self.preset_combo.setCurrentIndex(idx)
        self.preset_combo.blockSignals(False)

    def _on_preset_changed(self, idx):
        """切换预设：写入配置 + 立即加载对应网址 + 持久化。"""
        pid = self.preset_combo.itemData(idx)
        if not pid:
            return
        if pid == self.cfg.get("web.active_preset"):
            return   # 仅因刷新列表导致的重复信号，忽略
        self.cfg.set("web.active_preset", pid)
        preset = self.preset_by_id(pid)
        url = WebBackend.normalize_url((preset or {}).get("url", ""))
        if not url:
            tooltip("该预设没有配置网址，请在『设置 → 网页模式』里补充")
            return
        try:
            self.cfg.save()
        except Exception:
            pass
        self.load_url(url, preset=preset)
        tooltip("已切换到：%s" % (preset.get("name") or pid))

    def preset_by_id(self, pid):
        """按 id 取预设；找不到返回 None。"""
        for p in self.cfg.web_presets():
            if isinstance(p, dict) and p.get("id") == pid:
                return p
        return None

    def _apply_preset_ua(self, preset):
        """站点可以自带 User-Agent，没有则用全局自定义 UA。"""
        ua = (preset or {}).get("user_agent") or (self.cfg.get("web.custom_user_agent") or "")
        if not ua:
            return
        try:
            prof = self.page.profile() if self.page is not None else None
            if prof is not None:
                prof.setHttpUserAgent(ua)
        except Exception:
            pass

    def load_url(self, url, preset=None):
        """统一入口：应用 UA / 更新地址栏 / 记录 last_url / 加载网页。"""
        self._apply_preset_ua(preset if preset is not None else self.cfg.active_preset())
        url = WebBackend.normalize_url(url)
        if not url:
            return
        self.url_edit.setText(url)
        self.cfg.set("web.last_url", url)
        if self.view is not None:
            self.view.setUrl(QUrl(url))
        else:
            tooltip("当前环境没有可用的 QtWebEngine，网页模式不可用，请改用 API 模式")

    def open_preset(self, preset, auto=False):
        url = WebBackend.normalize_url((preset or {}).get("url", ""))
        if not url:
            return
        self.load_url(url, preset=preset)

    def open_external(self):
        """用系统默认浏览器打开当前网址（内嵌 WebView 被拦截时的兜底）。"""
        url = WebBackend.normalize_url(self.url_edit.text())
        if not url:
            tooltip("请先填写网页地址")
            return
        try:
            QDesktopServices.openUrl(QUrl(url))
        except Exception:
            tooltip("无法打开外部浏览器")

    def open_current_url(self):
        url = self.url_edit.text().strip()
        if not url:
            tooltip("请先填写网页地址")
            return
        self.load_url(url)

    def _on_load_finished(self, ok):
        if self.page is None:
            return
        try:
            url = self.page.url().toString()
            self.url_edit.setText(url)
            if not ok and url.startswith("http"):
                # 部分站点会拦截内嵌浏览器，提示用户手动处理
                tooltip("网页可能加载失败（站点拦截或需登录）。"
                        "可尝试『刷新』，或在设置里调整 User-Agent。")
        except Exception:
            pass

    def apply_active_preset(self):
        """把当前 active_preset 的网址同步到网页（设置里改动预设后调用）。"""
        preset = self.cfg.active_preset() or {}
        url = WebBackend.normalize_url(preset.get("url", ""))
        if not url or self.view is None:
            return
        try:
            cur = self.view.url().toString()
        except Exception:
            cur = ""
        if cur.rstrip("/") == url.rstrip("/"):
            return
        self.load_url(url, preset=preset)

    def refresh_flags(self):
        """把网页模式的开关状态重新同步到面板控件。

        修复：btn_send 的 enabled 原先只在构造时读一次 web.auto_send，
        导致在设置里开启『粘贴后自动点击网页的发送按钮』后必须重启 Anki 才生效。
        现在设置保存时会调用本方法，即时生效。
        """
        auto_send = bool(self.cfg.get("web.auto_send", False))
        self.btn_send.setEnabled(auto_send)
        self.btn_send.setToolTip(
            "点击网页上的发送按钮（已开启，自行承担风险）" if auto_send
            else "点击网页上的发送按钮（默认关闭；到『设置 → 网页模式』开启后可用）"
        )

    # ------------------------------------------------------------------ 交互
    def set_pending_text(self, text):
        """缓存待粘贴文本：翻卡自动注入（仅复制剪贴板）时也要存下来，
        否则用户随后点『粘贴卡片到输入框』会拿到空内容。"""
        if text:
            self._last_text = text

    def paste_text(self, text):
        """把文本写入网页输入框；失败时退回剪贴板。"""
        text = text or self._last_text or ""
        if not text:
            # 兜底：直接从当前卡片取，省去用户先按注入快捷键
            try:
                text = self.note_provider() or ""
            except Exception:
                text = ""
        if not text:
            tooltip("没有可粘贴的内容，请先注入卡片（Ctrl+Alt+I）")
            return
        self._last_text = text
        try:
            QApplication.clipboard().setText(text)
        except Exception:
            pass

        if self.page is None:
            tooltip("已复制到剪贴板（当前环境无 WebView，请在外部浏览器里粘贴）")
            return
        preset = self.cfg.active_preset() or {}
        selector = preset.get("input_selector", "")
        js = self.backend.inject_script(text, selector)
        try:
            self.page.runJavaScript(js, self._on_paste_result)
        except Exception:
            self._on_paste_result("error")

    def _on_paste_result(self, result):
        if result == "ok":
            tooltip("已写入网页输入框（未自动发送）")
        elif result == "no-input":
            tooltip("未找到输入框，文本已复制到剪贴板，请在网页里 Ctrl+V")
        else:
            tooltip("自动写入失败，文本已复制到剪贴板，请在网页里 Ctrl+V")

    def scrape_reply(self):
        if not self.cfg.get("web.scrape_reply", True):
            tooltip("抓取功能已在设置中关闭")
            return
        if self.page is None:
            tooltip("当前环境无 WebView，无法抓取")
            return
        preset = self.cfg.active_preset() or {}
        selector = preset.get("reply_selector", "")
        try:
            self.page.runJavaScript(self.backend.scrape_script(selector), self._on_scrape_result)
        except Exception:
            tooltip("抓取失败")

    def _on_scrape_result(self, text):
        text = (text or "").strip()
        if not text:
            tooltip("没能抓到回复（站点结构可能已变化），请在网页里手动复制后粘贴到输入框")
            return
        self.replyScraped.emit(text)
        tooltip("已抓取回复，可在输入框确认后保存")

    def click_send(self):
        if not self.cfg.get("web.auto_send", False):
            tooltip("自动发送默认关闭（设置 → 网页模式 可开启）")
            return
        if self.page is None:
            return
        preset = self.cfg.active_preset() or {}
        selector = preset.get("send_selector", "")
        try:
            self.page.runJavaScript(self.backend.send_script(selector), self._on_send_result)
        except Exception:
            tooltip("未找到发送按钮，请手动点击")

    def _on_send_result(self, result):
        """把网页里点发送的结果反馈出来，失败时说清楚到哪一步没命中。"""
        result = (result or "").strip()
        if result.startswith("ok:"):
            how = result[3:]
            if how == "enter":
                tooltip("已发送（用 Enter 兜底触发）")
            else:
                tooltip("已点击网页的发送按钮")
            return
        if result.startswith("not-found"):
            tooltip("没找到可点的发送按钮（已试 %s 个元素），请手动点击；"
                    "可在预设里填 send_selector 指定" % result.split(":")[-1])
            return
        tooltip("点击发送按钮失败，请手动点击")

    def sizeHint(self):
        return QSize(360, 420)
