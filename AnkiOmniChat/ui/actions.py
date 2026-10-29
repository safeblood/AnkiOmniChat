# -*- coding: utf-8 -*-
"""
actions.py —— 与卡片/剪贴板相关的动作。

    build_card_text(note, cfg)      把一张 Note 的全部字段拼成文本（供注入）
    copy_text(text)                 复制到剪贴板
    to_field_html(text, fmt)        按内容格式转成可安全放进字段的 HTML 片段
    apply_to_field(nid, text, mode, content_format) 追加 / 覆盖到指定字段并写回 Anki
"""

import html as _html
import re

from aqt import mw
from aqt.qt import QApplication, QInputDialog
from aqt.utils import showWarning, tooltip

try:  # Anki 自带的 HTML 剥离函数
    from anki.utils import strip_html as _strip_html
except Exception:  # pragma: no cover
    _strip_html = None

_TAG_RE = re.compile(r"<[^>]+>")
_SOUND_RE = re.compile(r"\[sound:[^\]]+\]")


def strip_html_keep_text(text):
    """去掉 HTML 标签；优先用 Anki 自带的 strip_html，不可用则正则兜底。"""
    text = text or ""
    if _strip_html is not None:
        try:
            return _strip_html(text)
        except Exception:
            pass
    text = _TAG_RE.sub("", text)
    return text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")


def note_fields(note):
    """返回字段名列表（兼容不同小版本获取 Note Type 的方式）。"""
    names = []
    try:
        nt = note.note_type()
        names = [f["name"] for f in (nt.get("flds") or [])]
    except Exception:
        try:
            model = mw.col.models.get(note.mid)
            names = [f["name"] for f in (model.get("flds") or [])]
        except Exception:
            names = []
    if not names:
        try:
            names = list(note.keys())
        except Exception:
            names = []
    return names


def _prompt_affixes(cfg):
    """
    取当前启用提示词的前缀 / 后缀。

    cfg 可能没有 active_prompt（旧版本配置对象、测试桩件），那时退回 inject.prefix
    /inject.suffix —— 那份内容在 _migrate_prompts 里已经和提示词库保持同步。
    """
    try:
        getter = cfg.active_prompt
    except Exception:
        getter = None
    if callable(getter):
        try:
            p = getter()
            if isinstance(p, dict):
                return p.get("prefix") or "", p.get("suffix") or ""
        except Exception:
            pass
    return cfg.get("inject.prefix") or "", cfg.get("inject.suffix") or ""


def build_card_text(note, cfg):
    """
    把 Note 的字段拼成一段上下文文本。

    template 支持占位符：{name} 字段名、{value} 字段值；exclude_fields 逗号分隔排除。
    提示词（prefix/suffix）里出现 {card} 时，拼接好的卡片正文会插在那个位置，而不是
    默认的「夹在 prefix 和 suffix 中间」—— 这样提示词可以自由安排语序，比如先布置
    任务再给材料。
    """
    template = cfg.get("inject.template") or "{name}：{value}"
    sep = cfg.get("inject.field_separator") or "\n"
    sep = sep.replace("\\n", "\n").replace("\\t", "\t")
    prefix, suffix = _prompt_affixes(cfg)
    prefix = (prefix or "").replace("\\n", "\n")
    suffix = (suffix or "").replace("\\n", "\n")
    exclude = [x.strip() for x in (cfg.get("inject.exclude_fields") or "").split(",") if x.strip()]
    do_strip = bool(cfg.get("inject.strip_html", True))

    parts = []
    try:
        items = list(note.items())
    except Exception:
        items = []
    for name, value in items:
        if name in exclude:
            continue
        value = value or ""
        if do_strip:
            value = strip_html_keep_text(value)
        value = _SOUND_RE.sub("[音频]", value).strip()
        if not value:
            continue
        try:
            parts.append(template.format(name=name, value=value, **{}))
        except Exception:
            parts.append("%s：%s" % (name, value))

    body = sep.join(parts)
    if "{card}" in prefix or "{card}" in suffix:
        return prefix.replace("{card}", body) + suffix.replace("{card}", body)
    return prefix + body + suffix


_NL_TO_BR = True


WRITE_FORMATS = ("markdown", "rendered", "html")


def _default_write_format():
    """读配置项 general.write_format，拿不到就用 markdown（最保守的那一档）。"""
    try:
        from aqt import mw

        cfg = mw.addonManager.getConfig(__package__.split(".")[0]) or {}
    except Exception:
        return "markdown"
    general = cfg.get("general") or {}
    fmt = (general.get("write_format") or "markdown").strip().lower()
    return fmt if fmt in WRITE_FORMATS else "markdown"


def to_field_html(text, content_format="markdown"):
    """
    把待写入的内容转成「放进 Anki 字段里是安全的」HTML 片段。

    Anki 的字段值本身是一段 HTML —— 卡片模板会把它原样 innerHTML 进页面。所以只要
    内容里出现 '<' '>' '&'，就会被当标签/实体解析：AI 回答里的 `<stdio.h>`、`a<b<c`
    这段文本会**静默消失**（浏览器当未知标签丢掉），而 `&amp;` 之类会被解成一个 `&`。
    Markdown 尤其容易踩到，因为代码块里尖括号是家常便饭。

    content_format:
      markdown  存 Markdown 源码。<>& 转义、换行转 <br>。编辑区看到的是原始源码，
                复习界面显示正常文本。（默认）
      rendered  先用自带的 renderer 把 Markdown 转成 HTML 再写入，复习时直接看到排版
                效果。renderer 不可用时自动退回到 markdown 档。
      html      内容本身就是 HTML（例如「抓取为富文本」的结果），原样写入不转义。

    注意 quote=False：只转义 <>&，不动引号 —— 正文里出现引号不会破坏任何东西，
    而转义了反而让源码里多出 &#x27; 这种噪音。
    """
    text = text or ""
    fmt = (content_format or "markdown").strip().lower()

    if fmt == "html":
        return text.strip()

    if fmt == "rendered":
        rendered = ""
        try:
            from .markdown import render_markdown

            rendered = render_markdown(text) or ""
        except Exception:
            rendered = ""
        if rendered.strip():
            return rendered.strip()
        fmt = "markdown"  # renderer 抽风就退回转义源码，至少内容不丢

    body = _html.escape(text.strip(), quote=False)
    return body.replace("\n", "<br>\n") if _NL_TO_BR else body


def copy_text(text):
    try:
        QApplication.clipboard().setText(text or "")
        tooltip("已复制")
        return True
    except Exception:
        showWarning("复制失败")
        return False


def _redraw_current_card(note_id):
    """仅重绘复习界面里的当前卡（写字段后不想走全量刷新时的最后一档）。"""
    from aqt import mw

    try:
        reviewer = getattr(mw, "reviewer", None)
        card = getattr(reviewer, "card", None)
        if card is None:
            return False
        # 写的不是当前这张卡时不要乱动（比如从浏览界面多选后写入）
        nid = None
        try:
            nid = getattr(card, "nid", None)
        except Exception:
            nid = None
        if nid is not None and nid != note_id:
            return False
        try:
            card.load()
        except Exception:
            pass
        for name in ("_redraw_current_card", "redraw_current_card"):
            fn = getattr(reviewer, name, None)
            if callable(fn):
                fn()
                return True
    except Exception:
        pass
    return False


def refresh_after_field_write(note_id):
    """
    字段写回后刷新 UI —— 刻意避开 mw.reset()。

    mw.reset() 会合成一个「所有字段都为 True」的 OpChanges 广播出去；Reviewer 收到
    study_queues=True 会把自己标成 RefreshNeeded.QUEUES，随后 refresh_if_needed()
    直接调用 nextCard()。于是复习途中往字段里写东西（这正是本插件的高频动作：把 AI
    的回答追加到卡片上），当前这张卡就被换掉了。

    正确做法是只声明"改了卡片正文"，让 Anki 自己按最小需求处理：复习界面重绘当前卡、
    浏览界面重绘表格、队列一律不动。这正是 mw.reset() 文档里推荐的 operation 机制。

    分三档，逐级退化：
      1) 广播 OpChanges(note_text=True)（等价于 Anki 自己完成一次小范围修改）
      2) 复习界面手工重载当前卡
      3) 都不行就什么都不做 —— 也比把用户的卡顶走要好
    """
    try:
        from anki.collection import OpChanges
        from aqt import gui_hooks

        changes = OpChanges()
        changes.note_text = True
        try:
            gui_hooks.operation_did_execute(changes, None)
        except TypeError:        # 旧签名只有 changes 一个参数
            gui_hooks.operation_did_execute(changes)
        return
    except Exception:
        pass
    _redraw_current_card(note_id)


def apply_to_field(note_id, text, mode="append", content_format=None):
    """
    把 AI 文本写回卡片字段。

    mode:            append=追加到字段末尾 / overwrite=覆盖字段
    content_format:  markdown / rendered / html，含义见 to_field_html()。
                     为 None 时读配置项 general.write_format。
    """
    if note_id is None:
        showWarning("没有可用的当前卡片。请在复习界面或浏览界面选中一张卡片。")
        return False
    if not text:
        tooltip("内容为空")
        return False
    try:
        note = mw.col.get_note(note_id)
    except Exception:
        showWarning("无法读取该卡片（可能已被删除）")
        return False

    fields = note_fields(note)
    if not fields:
        showWarning("该笔记没有可用字段")
        return False

    if len(fields) == 1:
        chosen = fields[0]
    else:
        chosen, ok = QInputDialog.getItem(
            mw, "AnkiOmniChat", "选择要写入的字段：", fields, 0, False
        )
        if not ok or not chosen:
            return False

    if content_format is None:
        content_format = _default_write_format()
    body = to_field_html(text, content_format)
    if not body.strip():
        tooltip("内容为空")
        return False

    old = note[chosen] or ""
    if mode == "overwrite":
        new = body
    else:
        # 字段是 HTML 上下文：用 \n 连接会被折叠成一个空格，换行根本显示不出来，
        # 所以这里用 <br> 分隔新追加的内容。
        new = (old.rstrip() + "<br><br>" + body.strip()) if old.strip() else body.strip()

    try:
        mw.checkpoint("AnkiOmniChat 写入字段")
    except Exception:
        pass
    note[chosen] = new
    try:
        # 2.1.60+ 推荐写法；旧版本通过 flush 兜底
        mw.col.update_note(note)
    except Exception:
        try:
            note.flush()
        except Exception:
            showWarning("写入失败：无法更新卡片")
            return False

    refresh_after_field_write(note_id)
    tooltip("已%s字段：%s" % ("覆盖" if mode == "overwrite" else "追加到", chosen))
    return True
