# -*- coding: utf-8 -*-
"""
markdown.py —— 极简 Markdown -> HTML 渲染器。

为什么不用 Anki 自带的 markdown：不同小版本是否内置并不确定，且流式输出需要"每次增量
都能整体重绘"的确定性行为。这里实现常用语法子集即可，且所有输入先 HTML 转义再拼装，
避免 AI 返回内容注入脚本。

支持：标题、段落、换行、粗体/斜体/删除线、行内代码、围栏代码块、无序/有序列表、
引用、分隔线、链接、简单表格、LaTeX（$...$ / $$...$$ / \\(...\\) / \\[...\\]）。
"""

import html
import re

# 占位符：先把"不需要再加工"的片段（代码、公式）藏起来，最后原样回填
_PH = "\x01%d\x01"

_FENCE_RE = re.compile(r"^\s{0,3}```\s*([\w+-]*)\s*$")
_HR_RE = re.compile(r"^\s{0,3}([-*_])\s*(\1\s*){2,}$")
_HEAD_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
_UL_RE = re.compile(r"^(\s*)[-*+]\s+(.*)$")
_OL_RE = re.compile(r"^(\s*)\d+[.)]\s+(.*)$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")
# 单独成行的行间公式围栏：$$ 或 \[
_DISP_OPEN_RE = re.compile(r"^\s*(\$\$|\\\[)\s*$")
_DISP_CLOSE_RE = re.compile(r"^\s*(\$\$|\\\])[\s]*$")
_SAFE_URL_RE = re.compile(r"^(https?|mailto|ankiomni)://", re.I)


def _escape(text):
    return html.escape(text or "", quote=False)


def _safe_url(url):
    url = (url or "").strip()
    if _SAFE_URL_RE.match(url):
        return html.escape(url, quote=True)
    return ""


def _inline(text):
    """处理行内语法。顺序：抽取代码/公式 -> 转义 -> 其它行内标记 -> 回填。"""
    stash = []

    def stash_html(fragment):
        stash.append(fragment)
        return _PH % (len(stash) - 1)

    def code_sub(m):
        return stash_html("<code>%s</code>" % _escape(m.group(1)))

    def math_block_sub(m):
        return stash_html('<span class="aoc-math aoc-math-block">\\[%s\\]</span>' % _escape(m.group(1)))

    def math_inline_sub(m):
        return stash_html('<span class="aoc-math">\\(%s\\)</span>' % _escape(m.group(1)))

    # 行内代码（先抽，避免其中的 $ * 被误判）
    text = re.sub(r"`([^`\n]+)`", code_sub, text)
    # 行间公式 $$...$$ / \[...\]
    text = re.sub(r"\$\$(.+?)\$\$", math_block_sub, text, flags=re.S)
    text = re.sub(r"\\\[(.+?)\\\]", math_block_sub, text, flags=re.S)
    # 行内公式 \(...\) 与 $...$（要求紧贴内容，避免把 "$5 和 $10" 这类文本误判为公式）
    text = re.sub(r"\\\((.+?)\\\)", math_inline_sub, text, flags=re.S)
    text = re.sub(r"(?<![\w\\])\$(?!\s)([^$\n]+?)(?<!\s)\$(?!\w)", math_inline_sub, text)

    # 转义剩余文本
    text = _escape(text)

    # 链接
    def link_sub(m):
        label, url = m.group(1), _safe_url(m.group(2))
        if not url:
            return m.group(0)
        return '<a href="%s" class="aoc-link">%s</a>' % (url, label)

    text = re.sub(r"\[([^\]\n]+)\]\(([^)\s]+)\)", link_sub, text)
    # 裸链接（http/https 开头且后面跟空白）
    text = re.sub(r"(?<![\"'>])(https?://[^\s<]+)",
                  lambda m: '<a href="%s" class="aoc-link">%s</a>' % (_safe_url(m.group(1)), m.group(1)),
                  text)
    # 强调
    text = re.sub(r"\*\*\*([^\s*][^*]*?)\*\*\*", r"<strong><em>\1</em></strong>", text)
    text = re.sub(r"\*\*([^\s*][^*]*?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"(?<![\w*])\*([^\s*][^*]*?)\*(?!\w)", r"<em>\1</em>", text)
    text = re.sub(r"~~([^~]+)~~", r"<del>\1</del>", text)

    # 回填占位符
    def restore(m):
        idx = int(m.group(1))
        return stash[idx] if 0 <= idx < len(stash) else ""

    return re.sub(r"\x01(\d+)\x01", restore, text)


def _is_block_start(line):
    """判断一行是否开启一个新的块级结构（用于段落收集时提前结束）。"""
    return bool(
        _FENCE_RE.match(line) or _HR_RE.match(line) or _HEAD_RE.match(line)
        or _UL_RE.match(line) or _OL_RE.match(line) or line.lstrip().startswith(">")
    )


def _render_list(items, ordered):
    """渲染列表；item 中可能已经嵌入子列表的 HTML，需要先占位避免被转义。"""
    tag = "ol" if ordered else "ul"
    stash = []

    def ph(fragment):
        stash.append(fragment)
        return "\x02%d\x02" % (len(stash) - 1)

    out = ["<%s>" % tag]
    for raw in items:
        pieces = re.split(r"(<ul>.*?</ul>|<ol>.*?</ol>)", raw, flags=re.S)
        buf = []
        for p in pieces:
            if not p:
                continue
            if p.startswith("<ul>") or p.startswith("<ol>"):
                buf.append(ph(p))
            else:
                buf.append(_inline(p))
        item = "".join(buf)

        def restore(m):
            idx = int(m.group(1))
            return stash[idx] if 0 <= idx < len(stash) else ""

        out.append("<li>%s</li>" % re.sub(r"\x02(\d+)\x02", restore, item))
    out.append("</%s>" % tag)
    return "".join(out)


def _render_table(rows):
    header = [c.strip() for c in rows[0].strip().strip("|").split("|")]
    body = []
    # rows[0]=表头，rows[1:]=数据行（分隔行已在解析阶段跳过）
    for r in rows[1:]:
        cells = [c.strip() for c in r.strip().strip("|").split("|")]
        if len(cells) < len(header):
            cells += [""] * (len(header) - len(cells))
        body.append(cells[:len(header)])
    out = ["<table><thead><tr>"]
    for h in header:
        out.append("<th>%s</th>" % _inline(h))
    out.append("</tr></thead><tbody>")
    for row in body:
        out.append("<tr>" + "".join("<td>%s</td>" % _inline(c) for c in row) + "</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def render_markdown(text):
    """把 Markdown 文本渲染为 HTML 片段（不含 <html>/<body>）。"""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")

    parts = []
    stash = []

    def emit(html_fragment):
        stash.append(html_fragment)
        parts.append(_PH % (len(stash) - 1))

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]

        # 围栏代码块
        if _FENCE_RE.match(line):
            lang = _FENCE_RE.match(line).group(1)
            i += 1
            buf = []
            while i < n and not re.match(r"^\s{0,3}```\s*$", lines[i]):
                buf.append(lines[i])
                i += 1
            i += 1
            cls = "aoc-code" + (" lang-%s" % html.escape(lang) if lang else "")
            emit('<pre class="%s"><code>%s</code></pre>' % (cls, _escape("\n".join(buf))))
            continue

        # 空行
        if not line.strip():
            i += 1
            continue

        # 行间公式块：单独成行的 $$ ... $$ 或 \[ ... \]
        if _DISP_OPEN_RE.match(line):
            i += 1
            buf = []
            while i < n and not _DISP_CLOSE_RE.match(lines[i]):
                buf.append(lines[i])
                i += 1
            i += 1
            emit('<span class="aoc-math aoc-math-block">\\[%s\\]</span>'
                 % _escape("\n".join(buf).strip()))
            continue

        # 分隔线
        if _HR_RE.match(line):
            emit("<hr/>")
            i += 1
            continue

        # 标题
        m = _HEAD_RE.match(line)
        if m:
            level = len(m.group(1))
            emit("<h%d>%s</h%d>" % (level, _inline(m.group(2)), level))
            i += 1
            continue

        # 引用
        if line.lstrip().startswith(">"):
            buf = []
            while i < n and lines[i].lstrip().startswith(">"):
                buf.append(re.sub(r"^\s*>\s?", "", lines[i]))
                i += 1
            emit("<blockquote>%s</blockquote>" % render_markdown("\n".join(buf)))
            continue

        # 表格
        if "|" in line and i + 1 < n and _TABLE_SEP_RE.match(lines[i + 1]):
            rows = [line]
            i += 2
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append(lines[i])
                i += 1
            emit(_render_table(rows))
            continue

        # 列表（支持一级缩进嵌套）
        m_ul = _UL_RE.match(line)
        m_ol = _OL_RE.match(line)
        if m_ul or m_ol:
            ordered = bool(m_ol)
            m = m_ol or m_ul
            base_indent = len(m.group(1))
            items = []
            children = []
            while i < n:
                cur_ul = _UL_RE.match(lines[i])
                cur_ol = _OL_RE.match(lines[i])
                if cur_ul or cur_ol:
                    cur = cur_ol or cur_ul
                    indent = len(cur.group(1))
                    if indent >= base_indent + 2:
                        children.append(cur.group(2))
                        i += 1
                        continue
                    if indent <= base_indent and (cur_ol is not None) == ordered:
                        if children:
                            items[-1] = "%s\n%s" % (
                                items[-1],
                                _render_list(children, (cur_ol is not None)),
                            )
                            children = []
                        items.append(cur.group(2))
                        i += 1
                        continue
                break
            if children and items:
                items[-1] = "%s\n%s" % (items[-1], _render_list(children, ordered))
            emit(_render_list(items, ordered))
            continue

        # 普通段落
        buf = []
        while i < n and lines[i].strip() and not _is_block_start(lines[i]):
            buf.append(lines[i])
            i += 1
        if not buf:  # 理论上不会走到，防止死循环
            buf.append(line)
            i += 1
        emit("<p>%s</p>" % _inline("\n".join(buf)).replace("\n", "<br/>"))

    result = "\n".join(parts)

    def restore(m):
        idx = int(m.group(1))
        return stash[idx] if 0 <= idx < len(stash) else ""

    result = re.sub(r"\x01(\d+)\x01", restore, result)
    return result
