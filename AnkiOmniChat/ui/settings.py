# -*- coding: utf-8 -*-
"""
settings.py —— 设置对话框。

分组：通用 / 网页模式 / API 模式 / 注入 / 快捷键 / 数据
保存后立即写回 Anki 配置，并通过回调通知主程序重新应用（快捷键、预设、面板宽度等）。
"""

import os
import subprocess
import sys

from aqt import mw
from aqt.qt import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit, QVBoxLayout,
    QWidget,
)
from aqt.utils import tooltip

from ..config import data_dir
from ..qt_compat import (
    HEADER_STRETCH, LINEEDIT_PASSWORD, MSGBOX_YES, TEXT_SELECTABLE, _std_button,
)


class SettingsDialog(QDialog):
    def __init__(self, cfg, sessions, on_saved=None, parent=None):
        super().__init__(parent or mw)
        self.cfg = cfg
        self.sessions = sessions
        self.on_saved = on_saved

        self.setWindowTitle("AnkiOmniChat 设置")
        self.resize(560, 560)

        root = QVBoxLayout(self)
        self.tabs = QTabWidget(self)
        root.addWidget(self.tabs, 1)

        self.tabs.addTab(self._build_general(), "通用")
        self.tabs.addTab(self._build_web(), "网页模式")
        self.tabs.addTab(self._build_api(), "API 模式")
        self.tabs.addTab(self._build_inject(), "卡片注入")
        self.tabs.addTab(self._build_shortcuts(), "快捷键")
        self.tabs.addTab(self._build_data(), "数据")

        buttons = QDialogButtonBox(_std_button("Ok") | _std_button("Cancel"), self)
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ------------------------------------------------------------------ 通用
    def _build_general(self):
        w = QWidget(self)
        form = QFormLayout(w)

        self.cmb_mode = QComboBox(w)
        self.cmb_mode.addItem("网页模式（内置浏览器，免费）", "web")
        self.cmb_mode.addItem("API 模式（OpenAI 兼容接口）", "api")
        idx = self.cmb_mode.findData(self.cfg.get("general.backend_mode", "web"))
        self.cmb_mode.setCurrentIndex(max(0, idx))
        form.addRow("默认后端模式：", self.cmb_mode)

        self.chk_switch = QCheckBox("切换卡片时自动切换会话", w)
        self.chk_switch.setChecked(bool(self.cfg.get("general.auto_switch_session", True)))
        form.addRow("", self.chk_switch)

        self.chk_auto_inject = QCheckBox("翻卡（显示答案）时自动注入当前卡片", w)
        self.chk_auto_inject.setChecked(bool(self.cfg.get("general.auto_inject_on_show_answer", True)))
        form.addRow("", self.chk_auto_inject)

        self.chk_context = QCheckBox("API 请求始终附带当前卡片上下文", w)
        self.chk_context.setChecked(bool(self.cfg.get("general.always_attach_card_context", True)))
        form.addRow("", self.chk_context)

        self.chk_show_review = QCheckBox("进入复习界面时自动显示侧边栏", w)
        self.chk_show_review.setChecked(bool(self.cfg.get("general.auto_show_panel_in_review", True)))
        form.addRow("", self.chk_show_review)

        self.spin_history = QSpinBox(w)
        self.spin_history.setRange(0, 100)
        self.spin_history.setValue(int(self.cfg.get("general.history_limit", 20)))
        form.addRow("单次请求携带历史条数：", self.spin_history)

        self.spin_width = QSpinBox(w)
        self.spin_width.setRange(240, 900)
        self.spin_width.setValue(int(self.cfg.get("general.panel_width", 400)))
        form.addRow("侧边栏宽度（像素）：", self.spin_width)

        self.cmb_dock = QComboBox(w)
        self.cmb_dock.addItem("右侧", "right")
        self.cmb_dock.addItem("左侧", "left")
        i = self.cmb_dock.findData(self.cfg.get("general.dock_area", "right"))
        self.cmb_dock.setCurrentIndex(max(0, i))
        form.addRow("停靠位置：", self.cmb_dock)

        return w

    # ------------------------------------------------------------------ 网页
    def _build_web(self):
        w = QWidget(self)
        layout = QVBoxLayout(w)

        self.chk_auto_paste = QCheckBox("注入卡片时自动写入网页输入框（否则只复制到剪贴板）", w)
        self.chk_auto_paste.setChecked(bool(self.cfg.get("web.auto_paste_on_inject", False)))
        layout.addWidget(self.chk_auto_paste)

        self.chk_auto_send = QCheckBox("粘贴后自动点击网页的发送按钮（不推荐）", w)
        self.chk_auto_send.setChecked(bool(self.cfg.get("web.auto_send", False)))
        layout.addWidget(self.chk_auto_send)

        self.chk_scrape = QCheckBox("允许『抓取网页回复』（尽力而为，可能失败）", w)
        self.chk_scrape.setChecked(bool(self.cfg.get("web.scrape_reply", True)))
        layout.addWidget(self.chk_scrape)

        ua_row = QHBoxLayout()
        ua_row.addWidget(QLabel("User-Agent：", w))
        self.edit_ua = QLineEdit(self.cfg.get("web.custom_user_agent", ""), w)
        ua_row.addWidget(self.edit_ua, 1)
        layout.addLayout(ua_row)

        layout.addWidget(QLabel("网页入口预设（名称 / 地址 / 输入框选择器 / 回复选择器 / 发送按钮选择器）：", w))

        self.table = QTableWidget(0, 5, w)
        self.table.setHorizontalHeaderLabels(
            ["名称", "地址", "输入框选择器", "回复选择器", "发送按钮选择器"])
        self.table.horizontalHeader().setSectionResizeMode(HEADER_STRETCH)
        self.table.verticalHeader().setVisible(False)
        for p in self.cfg.web_presets():
            self._add_row(p)
        layout.addWidget(self.table, 1)

        row = QHBoxLayout()
        btn_add = QPushButton("新增预设", w)
        btn_del = QPushButton("删除选中", w)
        btn_reset = QPushButton("恢复内置预设", w)
        btn_add.clicked.connect(lambda: self._add_row({"id": "custom", "name": "自定义",
                                                       "url": "", "input_selector": "",
                                                       "reply_selector": "",
                                                       "send_selector": ""}))
        btn_del.clicked.connect(self._del_row)
        btn_reset.clicked.connect(self._reset_presets)
        row.addWidget(btn_add)
        row.addWidget(btn_del)
        row.addWidget(btn_reset)
        row.addStretch(1)
        layout.addLayout(row)

        tip = QLabel("提示：网页模式只提供官方入口，登录态由内置浏览器自己保存；"
                     "插件不读取 cookie、不代发请求、不产生 API 费用。", w)
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#888;font-size:11px;")
        layout.addWidget(tip)
        return w

    def _add_row(self, preset):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem(preset.get("name", "")))
        self.table.setItem(r, 1, QTableWidgetItem(preset.get("url", "")))
        self.table.setItem(r, 2, QTableWidgetItem(preset.get("input_selector", "")))
        self.table.setItem(r, 3, QTableWidgetItem(preset.get("reply_selector", "")))
        self.table.setItem(r, 4, QTableWidgetItem(preset.get("send_selector", "")))

    def _del_row(self):
        row = self.table.currentRow()
        if row >= 0:
            self.table.removeRow(row)

    def _reset_presets(self):
        from ..config import DEFAULT_WEB_PRESETS
        import copy
        self.table.setRowCount(0)
        for p in copy.deepcopy(DEFAULT_WEB_PRESETS):
            self._add_row(p)

    # ------------------------------------------------------------------ API
    def _build_api(self):
        w = QWidget(self)
        form = QFormLayout(w)

        self.edit_endpoint = QLineEdit(self.cfg.get("api.endpoint", ""), w)
        self.edit_endpoint.setPlaceholderText("https://api.deepseek.com/v1/chat/completions")
        form.addRow("API 地址：", self.edit_endpoint)

        self.edit_key = QLineEdit(self.cfg.get("api.api_key", ""), w)
        self.edit_key.setEchoMode(LINEEDIT_PASSWORD)
        self.edit_key.setPlaceholderText("sk-...（留空则不加 Authorization 头）")
        form.addRow("API Key：", self.edit_key)

        self.edit_model = QLineEdit(self.cfg.get("api.model", ""), w)
        form.addRow("模型名称：", self.edit_model)

        self.spin_temp = QDoubleSpinBox(w)
        self.spin_temp.setRange(0.0, 2.0)
        self.spin_temp.setSingleStep(0.1)
        self.spin_temp.setValue(float(self.cfg.get("api.temperature", 0.3) or 0.3))
        form.addRow("温度：", self.spin_temp)

        self.spin_tokens = QSpinBox(w)
        self.spin_tokens.setRange(0, 32000)
        self.spin_tokens.setValue(int(self.cfg.get("api.max_tokens", 2048) or 0))
        form.addRow("最大 tokens（0=不限）：", self.spin_tokens)

        self.spin_timeout = QSpinBox(w)
        self.spin_timeout.setRange(10, 600)
        self.spin_timeout.setValue(int(self.cfg.get("api.timeout", 120) or 120))
        form.addRow("超时（秒）：", self.spin_timeout)

        self.chk_stream = QCheckBox("流式输出（逐字显示）", w)
        self.chk_stream.setChecked(bool(self.cfg.get("api.stream", True)))
        form.addRow("", self.chk_stream)

        form.addRow(QLabel("系统提示词：", w))
        self.edit_system = QTextEdit(w)
        self.edit_system.setPlainText(self.cfg.get("api.system_prompt", ""))
        self.edit_system.setMinimumHeight(90)
        form.addRow(self.edit_system)
        return w

    # ------------------------------------------------------------------ 注入
    def _build_inject(self):
        w = QWidget(self)
        form = QFormLayout(w)

        self.edit_template = QLineEdit(self.cfg.get("inject.template", "{name}：{value}"), w)
        form.addRow("字段模板：", self.edit_template)

        self.edit_prefix = QTextEdit(w)
        self.edit_prefix.setPlainText(self.cfg.get("inject.prefix", ""))
        self.edit_prefix.setMaximumHeight(70)
        form.addRow("前缀：", self.edit_prefix)

        self.edit_suffix = QTextEdit(w)
        self.edit_suffix.setPlainText(self.cfg.get("inject.suffix", ""))
        self.edit_suffix.setMaximumHeight(70)
        form.addRow("后缀：", self.edit_suffix)

        self.edit_exclude = QLineEdit(self.cfg.get("inject.exclude_fields", ""), w)
        self.edit_exclude.setPlaceholderText("用逗号分隔，例如：额外,备注")
        form.addRow("排除字段：", self.edit_exclude)

        self.chk_strip = QCheckBox("注入时剥离 HTML 标签", w)
        self.chk_strip.setChecked(bool(self.cfg.get("inject.strip_html", True)))
        form.addRow("", self.chk_strip)
        return w

    # ------------------------------------------------------------------ 快捷键
    def _build_shortcuts(self):
        w = QWidget(self)
        form = QFormLayout(w)
        self.sc_edits = {}
        labels = {
            "toggle_panel": "显示/隐藏侧边栏：",
            "inject_card": "注入当前卡片：",
            "focus_input": "聚焦输入框：",
            "send": "发送（输入框内）：",
        }
        for key, label in labels.items():
            edit = QLineEdit(self.cfg.get("shortcuts.%s" % key, ""), w)
            edit.setPlaceholderText("例如 Ctrl+Alt+C，留空表示禁用")
            self.sc_edits[key] = edit
            form.addRow(label, edit)
        tip = QLabel("使用 Qt 按键序列写法：Ctrl+Alt+I、Ctrl+Return、F8 等。"
                     "保存后重新进入复习界面即可生效。", w)
        tip.setWordWrap(True)
        tip.setStyleSheet("color:#888;font-size:11px;")
        form.addRow(tip)
        return w

    # ------------------------------------------------------------------ 数据
    def _build_data(self):
        w = QWidget(self)
        layout = QVBoxLayout(w)

        self.lbl_path = QLabel("会话文件：%s" % os.path.join(data_dir(self.cfg), "sessions.json"), w)
        self.lbl_path.setWordWrap(True)
        self.lbl_path.setTextInteractionFlags(TEXT_SELECTABLE)
        layout.addWidget(self.lbl_path)

        row = QHBoxLayout()
        btn_open = QPushButton("打开目录", w)
        btn_open.clicked.connect(self._open_dir)
        btn_clear_all = QPushButton("清空全部会话历史", w)
        btn_clear_all.clicked.connect(self._clear_all)
        row.addWidget(btn_open)
        row.addWidget(btn_clear_all)
        row.addStretch(1)
        layout.addLayout(row)

        info = QLabel("历史以 JSON 保存在本机，重启 Anki 不丢失；每个卡片（Note ID）一个会话，"
                      "互不影响。", w)
        info.setWordWrap(True)
        info.setStyleSheet("color:#888;font-size:11px;")
        layout.addWidget(info)
        layout.addStretch(1)
        return w

    def _open_dir(self):
        path = data_dir(self.cfg)
        try:
            if sys.platform.startswith("win"):
                os.startfile(path)  # noqa: S606
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            tooltip("无法打开：%s" % path)

    def _clear_all(self):
        ret = QMessageBox.question(self, "AnkiOmniChat", "确定清空全部会话历史？此操作不可撤销。")
        if ret == MSGBOX_YES:
            self.sessions.clear_all()
            tooltip("已清空全部会话历史")

    # ------------------------------------------------------------------ 保存
    def _apply(self):
        self.cfg.set("general.backend_mode", self.cmb_mode.currentData() or "web")
        self.cfg.set("general.auto_switch_session", self.chk_switch.isChecked())
        self.cfg.set("general.auto_inject_on_show_answer", self.chk_auto_inject.isChecked())
        self.cfg.set("general.always_attach_card_context", self.chk_context.isChecked())
        self.cfg.set("general.auto_show_panel_in_review", self.chk_show_review.isChecked())
        self.cfg.set("general.history_limit", self.spin_history.value())
        self.cfg.set("general.panel_width", self.spin_width.value())
        self.cfg.set("general.dock_area", self.cmb_dock.currentData() or "right")

        self.cfg.set("web.auto_paste_on_inject", self.chk_auto_paste.isChecked())
        self.cfg.set("web.auto_send", self.chk_auto_send.isChecked())
        self.cfg.set("web.scrape_reply", self.chk_scrape.isChecked())
        self.cfg.set("web.custom_user_agent", self.edit_ua.text().strip())

        old_presets = self.cfg.web_presets()
        presets = []
        for r in range(self.table.rowCount()):
            name = (self.table.item(r, 0).text() if self.table.item(r, 0) else "").strip()
            url = (self.table.item(r, 1).text() if self.table.item(r, 1) else "").strip()
            inp = (self.table.item(r, 2).text() if self.table.item(r, 2) else "").strip()
            rep = (self.table.item(r, 3).text() if self.table.item(r, 3) else "").strip()
            snd = (self.table.item(r, 4).text() if self.table.item(r, 4) else "").strip()
            if not name and not url:
                continue
            # 尽量沿用原有 id（doubao/kimi/deepseek…），避免保存设置后 active_preset 错位
            prev_id = ""
            if r < len(old_presets) and isinstance(old_presets[r], dict):
                prev_id = old_presets[r].get("id") or ""
            presets.append({
                "id": prev_id or ("p%d" % (r + 1)),
                "name": name or url,
                "url": url,
                "input_selector": inp,
                "reply_selector": rep,
                "send_selector": snd,
                "user_agent": "",
            })
        if presets:
            self.cfg.set_web_presets(presets)
            if self.cfg.get("web.active_preset") not in [p["id"] for p in presets]:
                self.cfg.set("web.active_preset", presets[0]["id"])

        self.cfg.set("api.endpoint", self.edit_endpoint.text().strip())
        self.cfg.set("api.api_key", self.edit_key.text().strip())
        self.cfg.set("api.model", self.edit_model.text().strip())
        self.cfg.set("api.temperature", self.spin_temp.value())
        self.cfg.set("api.max_tokens", self.spin_tokens.value())
        self.cfg.set("api.timeout", self.spin_timeout.value())
        self.cfg.set("api.stream", self.chk_stream.isChecked())
        self.cfg.set("api.system_prompt", self.edit_system.toPlainText())

        self.cfg.set("inject.template", self.edit_template.text())
        self.cfg.set("inject.prefix", self.edit_prefix.toPlainText())
        self.cfg.set("inject.suffix", self.edit_suffix.toPlainText())
        self.cfg.set("inject.exclude_fields", self.edit_exclude.text())
        self.cfg.set("inject.strip_html", self.chk_strip.isChecked())

        for key, edit in self.sc_edits.items():
            self.cfg.set("shortcuts.%s" % key, edit.text().strip())

        self.cfg.save()
        if self.on_saved:
            try:
                self.on_saved()
            except Exception:
                pass
        self.accept()


def open_settings_dialog(cfg, sessions, on_saved=None, parent=None):
    dlg = SettingsDialog(cfg, sessions, on_saved=on_saved, parent=parent)
    dlg.exec_() if hasattr(dlg, "exec_") else dlg.exec()
    return dlg
