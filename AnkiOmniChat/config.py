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


def normalize_prompts(prompts):
    """给提示词补齐新增字段（prompts 是 list，_merge 不会递归进去）。"""
    out = []
    for index, p in enumerate(prompts or []):
        if not isinstance(p, dict):
            continue
        item = dict(p)
        item.setdefault("id", "custom-%d" % index)
        item.setdefault("name", "未命名")
        item.setdefault("desc", "")
        item.setdefault("prefix", "")
        item.setdefault("suffix", "")
        out.append(item)
    return out


def _prompt(pid, name, desc, prefix, suffix=""):
    """构造一条注入提示词。

    prefix 在卡片正文之前、suffix 在之后；两者任意位置出现 {card} 时，卡片正文会被
    插到那个位置（而不是默认的"夹在中间"），方便写出先给任务再给材料的句式。
    """
    return {"id": pid, "name": name, "desc": desc, "prefix": prefix, "suffix": suffix}


DEFAULT_INJECT_PREFIX = (
    "下面是我在 Anki 中正在复习的一张卡片，请基于它回答我的问题。\n\n"
)
DEFAULT_INJECT_SUFFIX = "\n\n（以上为卡片内容，我的问题是：）\n"

# 内置提示词库：覆盖复习时真正会反复用到的几种提问方式。
# 之所以做成列表而不是单个 prompt —— 同一张卡今天想弄懂原理、明天想找反例、
# 临考前想被出题考一遍，靠改设置里的前缀后缀来回倒腾是不现实的。
DEFAULT_PROMPTS = [
    _prompt("default", "默认问答", "把卡片摆给 AI 后自由提问",
            DEFAULT_INJECT_PREFIX, DEFAULT_INJECT_SUFFIX),
    _prompt("explain", "讲透原理", "追到底层为什么，顺带纠正误解",
            "我在复习下面这张卡片。请讲透它的底层原理：为什么是这样、依据是什么、"
            "它解决的是什么问题。若有常见误解请一并指出。\n\n",
            "\n\n（以上是卡片内容，请开始讲解，必要时用类比。）\n"),
    _prompt("analogy", "举例类比", "看懂了但记不牢时，用类比+例子变直观",
            "我在复习下面这张卡片，字面看懂了但不够直观。请用一个贴切的类比和"
            "两个具体例子帮我把它变得好懂，例子尽量贴近日常。\n\n",
            "\n\n（以上是卡片内容，请给类比和例子。）\n"),
    _prompt("contrast", "对比辨析", "拎出易混概念做表格对比 + 区分口诀",
            "下面是我正在复习的卡片，它很容易和其它概念混淆。请找出最容易和它弄混的"
            "两三个概念，用表格对比关键差异，最后给一句区分口诀。\n\n",
            "\n\n（以上是卡片内容，请做辨析。）\n"),
    _prompt("quiz", "出题自测", "让它考你三道题，先不给答案",
            "我在复习下面这张卡片。请出三道题检验我是否真的掌握：一道基础识别、"
            "一道应用、一道需要推导的。只给题目，先不要给答案，我答完会告诉您。\n\n",
            "\n\n（以上是卡片内容，请出题，不要附答案。）\n"),
    _prompt("critique", "挑错补漏", "审视卡片本身：严谨性、歧义、遗漏前提",
            "下面这张是我自己的复习卡片。请挑它的毛病：表述是否严谨、有无事实错误、"
            "有无歧义、是否遗漏必要前提。然后给一版修改后的建议。\n\n",
            "\n\n（以上是卡片内容，请开始挑错。）\n"),
    _prompt("mnemonic", "助记口诀", "口诀 / 联想 / 缩写 / 故事，帮你挂住记忆点",
            "我在背下面这张卡片，内容太多记不住。请帮我设计记忆方法：口诀、图像联想、"
            "首字母缩写或故事串联均可，并说明这个记忆点具体挂在哪几个关键词上。\n\n",
            "\n\n（以上是卡片内容，请给助记方案。）\n"),
    _prompt("english", "英英释义", "适合单词卡：英语释义 + 搭配 + 例句",
            "我在背下面这个词条。请用英语释义解释它（难度控制在中学阅读水平），并给出："
            "1) 词性与核心义 2) 两个常见搭配 3) 一个例句。中文说明请尽量简短。\n\n",
            "\n\n（以上是词条内容，请按上述结构输出。）\n"),
]


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
        "write_format": "markdown",          # 写字段的内容格式：markdown=存源码 / rendered=渲染成 HTML / html=原样
    },

    # ---------------- 卡片注入 ----------------
    "inject": {
        "template": "{name}：{value}",       # 每个字段的渲染模板
        "field_separator": "\n",             # 字段之间的分隔符
        "exclude_fields": "",                # 逗号分隔，需要排除的字段名
        "prefix": DEFAULT_INJECT_PREFIX,     # 兼容旧配置；实际取 prompts 里 active 那条
        "suffix": DEFAULT_INJECT_SUFFIX,     # 同上
        "strip_html": True,                  # 注入时剥离 HTML 标签
        "prompts": copy.deepcopy(DEFAULT_PROMPTS),
        "active_prompt": "default",
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
        "cycle_prompt": "Ctrl+Alt+P",     # 轮换提示词
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
        self._migrate_prompts(raw if isinstance(raw, dict) else {})
        # 预设为空时补回内置预设，避免用户误删后无可用入口
        if not self._data.get("web", {}).get("presets"):
            self._data["web"]["presets"] = copy.deepcopy(DEFAULT_WEB_PRESETS)
        # 旧配置升级：presets 是 list，_merge 覆盖不进去，这里单独补齐新字段
        self._data["web"]["presets"] = normalize_presets(self._data["web"]["presets"])
        return self

    def _migrate_prompts(self, raw):
        """
        把 1.1.4 及更早的单条 inject.prefix/suffix 吸收进提示词库。

        raw 是**合并前**的磁盘配置 —— 必须看它而不是合并后的结果，否则永远分不清
        "用户自己改过前缀" 和 "用的就是默认值"。判断错了就会把用户的自定义覆盖掉。
        """
        inject = self._data.setdefault("inject", {})
        raw_inject = raw.get("inject") if isinstance(raw.get("inject"), dict) else {}

        prompts = raw_inject.get("prompts")
        if isinstance(prompts, list) and prompts:
            # 已经升级过：只需补齐字段，不要动用户的数据
            inject["prompts"] = normalize_prompts(prompts)
        else:
            # 旧配置或首次运行。若用户改过 prefix/suffix，那份必须保下来。
            legacy_prefix = raw_inject.get("prefix")
            legacy_suffix = raw_inject.get("suffix")
            changed = (
                isinstance(legacy_prefix, str) and legacy_prefix != DEFAULT_INJECT_PREFIX
            ) or (
                isinstance(legacy_suffix, str) and legacy_suffix != DEFAULT_INJECT_SUFFIX
            )
            items = list(DEFAULT_PROMPTS)
            if changed:
                # 把用户原来那套放在最前面并标记为当前使用，其余内置的仍然保留
                mine = _prompt(
                    "legacy", "我的提示词", "升级前自定义的前缀/后缀，已自动保留",
                    legacy_prefix if isinstance(legacy_prefix, str) else "",
                    legacy_suffix if isinstance(legacy_suffix, str) else "",
                )
                items.insert(0, mine)
                inject["active_prompt"] = "legacy"
                # 同时写回 prefix/suffix，老代码路径读到的也是同一份内容
                inject["prefix"] = mine["prefix"]
                inject["suffix"] = mine["suffix"]
            inject["prompts"] = copy.deepcopy(items)

        inject["prompts"] = normalize_prompts(inject["prompts"])
        active = inject.get("active_prompt")
        if not self._prompt_by_id(active):
            first = inject["prompts"][0] if inject["prompts"] else None
            inject["active_prompt"] = first["id"] if first else "default"

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

    # ---------- 提示词库 ----------
    def _prompt_by_id(self, pid):
        for p in self.prompt_presets():
            if isinstance(p, dict) and p.get("id") == pid:
                return p
        return None

    def prompt_presets(self):
        prompts = self.get("inject.prompts")
        if not isinstance(prompts, list):
            prompts = []
        return prompts

    def set_prompt_presets(self, prompts):
        self.set("inject.prompts", normalize_prompts(prompts))

    def active_prompt_id(self):
        pid = self.get("inject.active_prompt")
        return pid if self._prompt_by_id(pid) else self._fallback_prompt_id()

    def _fallback_prompt_id(self):
        presets = self.prompt_presets()
        return presets[0]["id"] if presets else "default"

    def active_prompt(self):
        """当前启用的提示词。拿不到就退化成旧的 inject.prefix/suffix 那一份。"""
        p = self._prompt_by_id(self.get("inject.active_prompt"))
        if isinstance(p, dict):
            return p
        presets = self.prompt_presets()
        if presets:
            return presets[0]
        return {
            "id": "default", "name": "默认问答", "desc": "",
            "prefix": self.get("inject.prefix") or "",
            "suffix": self.get("inject.suffix") or "",
        }

    def set_active_prompt(self, pid):
        """指定当前使用的提示词；id 不存在则忽略（返回 False）。"""
        if not self._prompt_by_id(pid):
            return False
        self.set("inject.active_prompt", pid)
        # 同步到旧的字段上，让没有升级的老代码路径读到同样的内容
        p = self._prompt_by_id(pid)
        self.set("inject.prefix", p.get("prefix") or "")
        self.set("inject.suffix", p.get("suffix") or "")
        return True

    def cycle_prompt(self, step=1):
        """按列表顺序轮换（默认往后一条），到头回绕。返回切换后的那一条。"""
        presets = self.prompt_presets()
        if not presets:
            return None
        cur = self.active_prompt_id()
        ids = [p.get("id") for p in presets]
        try:
            index = (ids.index(cur) + int(step)) % len(ids)
        except (ValueError, TypeError):
            index = 0
        self.set_active_prompt(ids[index])
        return self.active_prompt()
