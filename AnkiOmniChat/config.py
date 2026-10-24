# -*- coding: utf-8 -*-
"""
config.py —— 配置中心。

配置读取优先级：
    1) Anki 的插件配置 API（mw.addonManager.getConfig / writeConfig，保存在 meta.json 同级的
       prefs 中，插件更新不会丢失）
    2) 插件目录下的 config.json（兜底：万一 Anki 接口不可用或文件损坏时仍能启动）

对外主要提供：
    * DEFAULT_CONFIG    默认配置字典
    * Config            配置对象，支持 "a.b.c" 点号路径读写
    * data_dir(cfg)     用户数据目录（会话 JSON / 网页 profile 缓存）
"""

import copy
import json
import os

ADDON_DIR = os.path.dirname(os.path.abspath(__file__))
ADDON_NAME = os.path.basename(ADDON_DIR)

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _preset(pid, name, url, input_sel="", reply_sel="", send_sel=""):
    """构造一个网页模式预设（免费模式：用户在 WebView 内自行登录）。

    send_selector 可选：留空时由 JS_CLICK_SEND 的多层兜底自动找发送按钮，
    站点改版导致自动找不到时，用户可以在这里手动指定。
    """
    return {
        "id": pid,
        "name": name,
        "url": url,
        "input_selector": input_sel,
        "reply_selector": reply_sel,
        "send_selector": send_sel,
        "user_agent": "",
    }


def normalize_presets(presets):
    """给旧配置里的预设补齐新增字段（presets 是 list，_merge 不会递归进去）。"""
    out = []
    for p in (presets or []):
        if not isinstance(p, dict):
            continue
        item = dict(p)
        item.setdefault("input_selector", "")
        item.setdefault("reply_selector", "")
        item.setdefault("send_selector", "")
        item.setdefault("user_agent", "")
        out.append(item)
    return out


# 内置三个免费网页入口（仅提供入口，不代付、不抓 cookie、不走付费 API）
DEFAULT_WEB_PRESETS = [
    _preset("doubao", "豆包", "https://www.doubao.com/chat/",
            "textarea, div[contenteditable='true']"),
    _preset("kimi", "Kimi", "https://www.kimi.com/",
            "div[contenteditable='true'], textarea"),
    _preset("deepseek", "DeepSeek", "https://chat.deepseek.com/",
            "textarea, div[contenteditable='true']"),
]

DEFAULT_CONFIG = {
    "version": 1,

    # ---------------- 通用 ----------------
    "general": {
        "backend_mode": "web",               # web=网页内嵌免费模式(默认) / api=OpenAI 兼容 API
        "auto_switch_session": True,         # 切换卡片时自动切换会话
        "auto_inject_on_show_answer": True,  # 翻卡（显示答案）时自动注入当前卡片
        "always_attach_card_context": True,  # API 模式：请求时始终附带当前卡片上下文
        "auto_show_panel_in_review": True,   # 进入复习界面自动显示侧边栏
        "history_limit": 20,                 # 单次请求携带的历史消息条数
        "max_messages_per_session": 200,     # 单个会话最多保留的消息数
        "panel_width": 400,                  # 侧边栏初始宽度（像素）
        "dock_area": "right",                # right / left
    },

    # ---------------- 卡片注入 ----------------
    "inject": {
        "template": "{name}：{value}",       # 每个字段的渲染模板
        "field_separator": "\n",             # 字段之间的分隔符
        "exclude_fields": "",                # 逗号分隔，需要排除的字段名
        "prefix": "下面是我在 Anki 中正在复习的一张卡片，请基于它回答我的问题。\n\n",
        "suffix": "\n\n（以上为卡片内容，我的问题是：）\n",
        "strip_html": True,                  # 注入时剥离 HTML 标签
    },

    # ---------------- 网页模式（模式 A） ----------------
    "web": {
        "presets": copy.deepcopy(DEFAULT_WEB_PRESETS),
        "active_preset": "doubao",
        "auto_paste_on_inject": False,       # 自动注入时是否直接写入网页输入框（默认否，只复制）
        "auto_send": False,                  # 是否自动发送（强烈建议关闭）
        "custom_user_agent": DEFAULT_UA,     # 自定义 UA，降低被站点拦截的概率
        "scrape_reply": True,                # 是否允许"尽力抓取网页最后一条回复"
        "last_url": "",                      # 上次访问的网页地址
    },

    # ---------------- API 模式（模式 B） ----------------
    "api": {
        "endpoint": "https://api.deepseek.com/v1/chat/completions",
        "api_key": "",
        "model": "deepseek-chat",
        "temperature": 0.3,
        "max_tokens": 2048,
        "system_prompt": (
            "你是嵌入在 Anki 中的学习助手。回答请简洁、结构化，"
            "必要时使用 Markdown 与 LaTeX 公式（行内 $...$，行间 $$...$$）。"
        ),
        "stream": True,
        "timeout": 120,
    },

    # ---------------- 快捷键 ----------------
    "shortcuts": {
        "toggle_panel": "Ctrl+Alt+C",
        "inject_card": "Ctrl+Alt+I",
        "focus_input": "Ctrl+Alt+U",
        "send": "Ctrl+Return",
    },

    # ---------------- 存储 ----------------
    "storage": {
        "location": "profile",               # profile=当前 profile 目录 / addon=插件 user_files
    },
}


def _merge(base, override):
    """递归合并：override 覆盖 base，缺失项保留默认值（只合并 dict，list 整体替换）。"""
    out = copy.deepcopy(base)
    if not isinstance(override, dict):
        return out
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def data_dir(cfg=None):
    """
    用户数据目录（会话 JSON、网页 profile 缓存、生成的 chat.html）。
    默认放在当前 profile 目录下，避免插件更新时被清空；不可用时退回插件 user_files。
    """
    loc = "profile"
    try:
        if cfg is not None:
            loc = cfg.get("storage.location") or "profile"
    except Exception:
        pass

    if loc == "addon":
        path = os.path.join(ADDON_DIR, "user_files")
    else:
        path = None
        try:
            from aqt import mw
            base = mw.pm.profileFolder() if mw is not None else None
            if base:
                path = os.path.join(base, "AnkiOmniChat")
        except Exception:
            path = None
        if path is None:
            path = os.path.join(ADDON_DIR, "user_files")

    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    return path


class Config(object):
    """轻量配置对象：点号路径读写 + 保存回 Anki。"""

    def __init__(self):
        self._data = copy.deepcopy(DEFAULT_CONFIG)

    # ---------- 载入 / 保存 ----------
    def load(self):
        raw = None
        try:
            from aqt import mw
            if mw is not None:
                raw = mw.addonManager.getConfig(ADDON_NAME)
        except Exception:
            raw = None
        if not isinstance(raw, dict):
            raw = self._read_local_json()
        self._data = _merge(DEFAULT_CONFIG, raw or {})
        # 预设为空时补回内置预设，避免用户误删后无可用入口
        if not self._data.get("web", {}).get("presets"):
            self._data["web"]["presets"] = copy.deepcopy(DEFAULT_WEB_PRESETS)
        # 旧配置升级：presets 是 list，_merge 覆盖不进去，这里单独补齐新字段
        self._data["web"]["presets"] = normalize_presets(self._data["web"]["presets"])
        return self

    def save(self):
        try:
            from aqt import mw
            if mw is not None:
                mw.addonManager.writeConfig(ADDON_NAME, self._data)
                return True
        except Exception:
            pass
        # 兜底：写回插件目录的 config.json
        try:
            with open(os.path.join(ADDON_DIR, "config.json"), "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def _read_local_json(self):
        try:
            with open(os.path.join(ADDON_DIR, "config.json"), "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    # ---------- 读写 ----------
    def data(self):
        return self._data

    def get(self, path, default=None):
        """按 'general.backend_mode' 形式的路径取值，取不到返回 default。"""
        node = self._data
        for part in str(path).split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, path, value):
        node = self._data
        parts = str(path).split(".")
        for part in parts[:-1]:
            nxt = node.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                node[part] = nxt
            node = nxt
        node[parts[-1]] = value

    # ---------- 网页预设 ----------
    def web_presets(self):
        presets = self.get("web.presets") or []
        if not isinstance(presets, list):
            presets = []
        return presets

    def set_web_presets(self, presets):
        self.set("web.presets", presets)

    def active_preset(self):
        pid = self.get("web.active_preset")
        for p in self.web_presets():
            if isinstance(p, dict) and p.get("id") == pid:
                return p
        presets = self.web_presets()
        return presets[0] if presets else {"id": "custom", "name": "自定义", "url": ""}
