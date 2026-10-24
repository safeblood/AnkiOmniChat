# -*- coding: utf-8 -*-
"""
actions.py —— 与卡片/剪贴板相关的动作。

    build_card_text(note, cfg)      把一张 Note 的全部字段拼成文本（供注入）
    copy_text(text)                 复制到剪贴板
    apply_to_field(nid, text, mode) 追加 / 覆盖到指定字段并写回 Anki
"""

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


def build_card_text(note, cfg):
    """
    把 Note 的字段拼成一段上下文文本。
    template 支持占位符：{name} 字段名、{value} 字段值；exclude_fields 逗号分隔排除。
    """
    template = cfg.get("inject.template") or "{name}：{value}"
    sep = cfg.get("inject.field_separator") or "\n"
    sep = sep.replace("\\n", "\n").replace("\\t", "\t")
    prefix = (cfg.get("inject.prefix") or "").replace("\\n", "\n")
    suffix = (cfg.get("inject.suffix") or "").replace("\\n", "\n")
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
    return (prefix or "") + body + (suffix or "")


def copy_text(text):
    try:
        QApplication.clipboard().setText(text or "")
        tooltip("已复制")
        return True
    except Exception:
        showWarning("复制失败")
        return False


def apply_to_field(note_id, text, mode="append"):
    """
    把 AI 文本写回卡片字段。
    mode: append=追加到字段末尾 / overwrite=覆盖字段。
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

    old = note[chosen] or ""
    if mode == "overwrite":
        new = text
    else:
        new = (old.rstrip() + "\n" + text.strip()) if old.strip() else text.strip()

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

    try:
        mw.reset()
    except Exception:
        pass
    tooltip("已%s字段：%s" % ("覆盖" if mode == "overwrite" else "追加到", chosen))
    return True
