# -*- coding: utf-8 -*-
"""
backend.py —— 双后端。

模式 A（web，默认）：WebView 内嵌免费网页版（豆包 / Kimi / DeepSeek）。
    · 只提供官方入口 URL，用户在内置浏览器里自行登录，cookie 由 QtWebEngine 自己的
      profile 持久化保存，插件不读取、不上传任何凭证，也不调用付费 API。
    · 提供「粘贴到网页输入框」能力：优先用 JS 原生事件写入（兼容 React/Vue 受控组件），
      失败则退回剪贴板；默认只粘贴、不发送。
    · 「抓取网页最后一条回复」为尽力而为（best effort）功能，依赖可配置选择器；抓不到时
      用户可在网页里自行复制后粘贴回输入框。

模式 B（api）：OpenAI 兼容 chat/completions 接口，SSE 流式解析，工作线程中请求，
    通过 Qt 信号把增量文本送回主线程，不阻塞 UI。

依赖说明：优先使用 Anki 自带的 requests；若不存在则用标准库 urllib，全程零第三方依赖。
"""

import json
import urllib.request
import urllib.error

from aqt.qt import QObject, QThread, pyqtSignal

# ---------------------------------------------------------------------------
# 网页注入 / 抓取脚本（在 WebView 中执行）
# ---------------------------------------------------------------------------

# 把文本写入网页输入框：textarea/input 用原生 setter + input 事件；
# contenteditable 用 execCommand('insertText') 触发受控组件的 onChange。
JS_INJECT_TEXT = """
(function(sel, text){
  try {
    var list = [];
    if (sel) { try { list = Array.prototype.slice.call(document.querySelectorAll(sel)); } catch(e) {} }
    if (!list.length) {
      var sels = ["textarea", "div[contenteditable='true']", "div[contenteditable]",
                  "[role='textbox']", "input[type='text']"];
      for (var i = 0; i < sels.length && !list.length; i++) {
        try { list = Array.prototype.slice.call(document.querySelectorAll(sels[i])); } catch(e) {}
      }
    }
    list = list.filter(function(el){
      var r = el.getBoundingClientRect();
      return r.width > 40 && r.height > 8;
    });
    if (!list.length) { return "no-input"; }
    list.sort(function(a, b){
      var ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      return (rb.width * rb.height) - (ra.width * ra.height);
    });
    var el = list[0];
    el.focus();
    var tag = (el.tagName || "").toLowerCase();
    if (tag === "textarea" || tag === "input") {
      var proto = (tag === "textarea") ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      var desc = Object.getOwnPropertyDescriptor(proto, "value");
      if (desc && desc.set) { desc.set.call(el, text); }
      else { el.value = text; }
      el.dispatchEvent(new Event("input", { bubbles: true }));
      return "ok";
    } else {
      var s = window.getSelection(), r = document.createRange();
      r.selectNodeContents(el); r.collapse(false);
      s.removeAllRanges(); s.addRange(r);
      var ok = false;
      try { ok = document.execCommand("insertText", false, text); } catch(e) { ok = false; }
      if (!ok) { el.textContent = text; el.dispatchEvent(new Event("input", { bubbles: true })); }
      return "ok";
    }
  } catch (e) {
    return "error:" + ((e && e.message) ? e.message : String(e));
  }
})(%s, %s);
"""

# 尽力抓取网页上"最后一条"回复文本；选择器可在设置中配置，抓不到返回空串。
JS_SCRAPE_REPLY = """
(function(sel){
  try {
    var sels = [];
    if (sel) { sels.push(sel); }
    sels = sels.concat([
      "[data-role='assistant']", "[data-message-author='assistant']",
      ".markdown-body", "article", "main .message", "div[class*='answer']",
      "div[class*='message-content']", "div[class*='assistant']"
    ]);
    for (var i = 0; i < sels.length; i++) {
      try {
        var nl = document.querySelectorAll(sels[i]);
        if (nl && nl.length) {
          var txt = (nl[nl.length - 1].innerText || "").trim();
          if (txt) { return txt; }
        }
      } catch(e) {}
    }
    return "";
  } catch (e) { return ""; }
})(%s);
"""

# 点击发送按钮（仅在用户明确开启 auto_send 时使用；不推荐开启）
#
# 分四层兜底，任何一层成功就返回 "ok:<命中方式>"，全失败返回 "not-found:<尝试过的元素数>"：
#   1) 用户在预设里配置的选择器
#   2) 严格选择器：submit / data-testid / aria-label —— 只认语义明确的，误点风险最低
#   3) 宽松选择器：class 或 id 里含 send / submit，且尺寸不超过 SEND_MAX_W/H（避免点到整块容器）
#   4) 就近查找：从输入框往上找祖先容器，在容器里挑一个"看起来像发送键"的小按钮
#   5) 键盘兜底：对输入框派发 Enter，React / Vue 系站点普遍能接住
#
# 注意：旧的写法一旦某个选择器查得到元素就不再往后试，哪怕这些元素全都
# hidden / disabled —— 结果就是明明有按钮却报 not-found。这里改成逐层试到能点为止。
JS_CLICK_SEND = """
(function(sel){
  // 宽松层只给高度设上限（按钮再宽也不会很高）。
  // 早期版本连宽度一起限（160/200），结果块级 div 撑满整行被误杀，只能回退到 Enter。
  var SEND_MAX_H = 120;
  var tried = 0;
  function visible(el){
    try {
      var r = el.getBoundingClientRect();
      if (r.width < 8 || r.height < 8) { return false; }
      var cs = getComputedStyle(el);
      if (!cs || cs.display === "none" || cs.visibility === "hidden") { return false; }
      if (parseFloat(cs.opacity || "1") < 0.1) { return false; }
      return true;
    } catch (e) { return false; }
  }
  function usable(el){
    if (!el || el.disabled) { return false; }
    try {
      // 非表单元素（div[role=button]）的 disabled 只是个属性，读 .disabled 拿不到
      if (el.hasAttribute && el.hasAttribute("disabled")) { return false; }
      if (el.getAttribute("aria-disabled") === "true") { return false; }
      if (el.getAttribute("data-disabled") === "true") { return false; }
      // 灰掉的按钮一般会被加上 disabled 类或干脆屏蔽点击
      var cls = (el.getAttribute("class") || "").toLowerCase();
      if (cls.indexOf("disabled") >= 0) { return false; }
      var pe = getComputedStyle(el).pointerEvents;
      if (pe === "none") { return false; }
    } catch (e) {}
    return visible(el);
  }
  function q(s){
    try { return Array.prototype.slice.call(document.querySelectorAll(s)); } catch (e) { return []; }
  }
  function clickFirst(list, how, sizeLimit){
    for (var i = 0; i < list.length; i++) {
      var el = list[i];
      tried++;
      if (!usable(el)) { continue; }
      if (sizeLimit) {
        try {
          var r = el.getBoundingClientRect();
          if (r.width > SEND_MAX_W || r.height > SEND_MAX_H) { continue; }
        } catch (e) { continue; }
      }
      try { el.click(); } catch (e) { continue; }
      return "ok:" + how + "#" + i;
    }
    return "";
  }
  // 汇总多个选择器的命中元素，去重后按面积从小到大点第一个可点的。
  // 高度设上限（按钮不会很高）；宽度不设限——块级元素会撑满整行，限宽只会误杀。
  function clickSmallest(sels, how, editable){
    var pool = [];
    for (var i = 0; i < sels.length; i++) { pool = pool.concat(q(sels[i])); }
    var uniq = [];
    for (var j = 0; j < pool.length; j++) { if (uniq.indexOf(pool[j]) < 0) { uniq.push(pool[j]); } }
    var boxed = [];
    for (var k = 0; k < uniq.length; k++) {
      // 发送键不可能"包着输入框"，把这类外层容器排除掉
      if (editable && (uniq[k] === editable || (uniq[k].contains && uniq[k].contains(editable)))) {
        continue;
      }
      var rr = null;
      try { rr = uniq[k].getBoundingClientRect(); } catch (e) { continue; }
      if (!rr || rr.height > SEND_MAX_H) { continue; }
      boxed.push({el: uniq[k], area: rr.width * rr.height});
    }
    boxed.sort(function(x, y) { return x.area - y.area; });
    var list = [];
    for (var m = 0; m < boxed.length; m++) { list.push(boxed[m].el); }
    return clickFirst(list, how, 0);
  }

  function findEditable(){
    var ae = document.activeElement;
    if (ae && (ae.tagName === "TEXTAREA" || ae.tagName === "INPUT" || ae.isContentEditable) && visible(ae)) {
      return ae;
    }
    var cands = q("textarea, [contenteditable='true'], input[type='text']");
    for (var i = cands.length - 1; i >= 0; i--) { if (visible(cands[i])) { return cands[i]; } }
    return null;
  }

  var tier1 = [];
  if (sel) { tier1.push(sel); }
  tier1 = tier1.concat([
    "button[type='submit']",
    "[data-testid='send-button']", "[data-testid*='send']",
    "button[aria-label*='发送']", "button[aria-label*='Send']",
    "button[aria-label*='send' i]",
    "[role='button'][aria-label*='发送']", "[role='button'][aria-label*='Send']",
    "[role='button'][aria-label*='send' i]"
  ]);
  for (var a = 0; a < tier1.length; a++) {
    var r1 = clickFirst(q(tier1[a]), "sel[" + tier1[a] + "]", 0);
    if (r1) { return r1; }
  }

  // DeepSeek / 豆包 这类站点用 div[role=button] + 自研 class，既没有 aria-label 也不是 submit。
  // 这里不按选择器顺序取第一个，而是把命中元素汇总后按面积取最小的那个：
  // 真正的发送键永远比"同样带 send 字样的外层容器"小。
  var tier2 = [
    "[role='button'][class*='send' i]", "button[class*='send' i]",
    "[role='button'][class*='submit' i]", "button[class*='submit' i]",
    "[class*='sendBtn' i]", "[class*='send-btn' i]", "[class*='send-button' i]",
    "[id*='send' i] button", "[id*='send' i][role='button']", "[id*='submit' i] button"
  ];
  var ed = findEditable();
  var r2 = clickSmallest(tier2, "cls", ed);
  if (r2) { return r2; }

  if (ed) {
    var node = ed, depth = 0;
    while (node && depth < 6) {
      var kids = [];
      try {
        kids = Array.prototype.slice.call(
          node.querySelectorAll("button, [role='button'], [class*='send' i], [class*='submit' i]"));
      } catch (e) { kids = []; }
      // 按面积从小到大排：发送键通常是一行里最小的那个可点元素
      var small = [];
      for (var k = 0; k < kids.length; k++) {
        // 排除输入框本身、输入框内部的节点，以及包着输入框的外层容器
        if (kids[k] === ed || (ed.contains && ed.contains(kids[k]))
            || (kids[k].contains && kids[k].contains(ed))) { continue; }
        var rr = null;
        try { rr = kids[k].getBoundingClientRect(); } catch (e) { continue; }
        if (!rr || rr.height > SEND_MAX_H) { continue; }
        small.push({el: kids[k], area: rr.width * rr.height});
      }
      small.sort(function(x, y) { return x.area - y.area; });
      var r3 = clickFirst(small.map(function(x) { return x.el; }), "near#" + depth, 0);
      if (r3) { return r3; }
      node = node.parentElement; depth++;
    }
    try {
      var ev = {key: "Enter", code: "Enter", keyCode: 13, which: 13, bubbles: true, cancelable: true};
      ed.dispatchEvent(new KeyboardEvent("keydown", ev));
      ed.dispatchEvent(new KeyboardEvent("keypress", ev));
      ed.dispatchEvent(new KeyboardEvent("keyup", ev));
      return "ok:enter";
    } catch (e) {}
  }
  return "not-found:" + tried;
})(%s);
"""


# 抓取网页内容并转成 Markdown。
#
# 取源优先级：网页里当前选中的内容 > 最后一条 AI 回答（复用 JS_SCRAPE_REPLY 的选择器链）。
# 转换成 Markdown 是为了保住代码块 / 列表 / 表格 / 标题这些结构——直接用 innerText 会把
# 它们揉成一坨丢格式的纯文本。
JS_SCRAPE_MARKDOWN = r"""
(function(sel){
  try {
    // 交互控件不该进正文，否则会在抓出来的内容末尾冒出一个「复制」之类的按钮文案
    var SKIP = {script:1, style:1, noscript:1, template:1,
                button:1, input:1, select:1, textarea:1, svg:1};
    var BLOCK = {p:1, div:1, section:1, article:1, figure:1, main:1, header:1, footer:1,
                 header_:0, pre:1, blockquote:1, ul:1, ol:1, table:1, h1:1, h2:1, h3:1,
                 h4:1, h5:1, h6:1};

    function picked(){
      try {
        var s = window.getSelection();
        if (!s || s.rangeCount === 0 || s.isCollapsed) return null;
        var r = s.getRangeAt(0);
        if (!r || !(r.toString() || "").trim()) return null;
        var wrap = document.createElement("div");
        wrap.appendChild(r.cloneContents());
        return wrap;
      } catch (e) { return null; }
    }

    function lastAnswer(){
      var sels = [];
      if (sel) sels.push(sel);
      sels = sels.concat([
        "[data-role='assistant']", "[data-message-author='assistant']",
        ".markdown-body", "article", "main .message",
        "div[class*='answer']", "div[class*='message-content']", "div[class*='assistant']"
      ]);
      for (var i = 0; i < sels.length; i++) {
        try {
          var nl = document.querySelectorAll(sels[i]);
          if (!nl || !nl.length) continue;
          for (var j = nl.length - 1; j >= 0; j--) {
            if ((nl[j].innerText || "").trim()) return nl[j];
          }
        } catch (e) {}
      }
      return null;
    }

    function fence(el){
      var code = el.querySelector("code");
      var src = code || el;
      var lang = "";
      if (code) {
        var mm = /language-([A-Za-z0-9_+-]+)/.exec(code.className || "");
        if (mm) lang = mm[1];
      }
      var txt = (src.textContent || "").replace(/\s+$/, "");
      return "```" + (lang || "") + "\n" + txt + "\n```";
    }

    // inlineNode: 给「元素自身」加上 Markdown 标记，内部文本交给 inline。
    // 必须分成两个函数——inline 只负责把子节点拼起来，不会给 el 自己加标记；
    // 而 blocks / listBlock 遍历到的是一个完整的元素，若不走这一层，选区模式下
    // <strong>、<code>、<a> 的标记就会整批丢失。
    function inlineNode(el){
      var tag = (el.tagName || "").toLowerCase();
      var inner = inline(el);
      if (tag === "strong" || tag === "b") return "**" + inner + "**";
      if (tag === "em" || tag === "i") return "*" + inner + "*";
      if (tag === "del" || tag === "s") return "~~" + inner + "~~";
      if (tag === "code") return "`" + (el.textContent || "").replace(/\n/g, " ") + "`";
      if (tag === "br") return "\n";
      // Markdown 没有上/下标语法，保留原标签，Anki 字段和多数渲染器都能正确显示
      if (tag === "sup" || tag === "sub") return "<" + tag + ">" + inner + "</" + tag + ">";
      if (tag === "a") {
        var h = el.getAttribute("href") || "";
        return (h && inner.trim()) ? ("[" + inner.trim() + "](" + h + ")") : (inner || h);
      }
      if (tag === "img") {
        var img = el.getAttribute("src") || "";
        return img ? ("![" + (el.getAttribute("alt") || "") + "](" + img + ")") : "";
      }
      return inner;
    }

    function inline(node){
      var s = "", kids = node.childNodes || [];
      for (var i = 0; i < kids.length; i++) {
        var el = kids[i];
        if (el.nodeType === 3) { s += el.nodeValue; continue; }
        if (el.nodeType !== 1) continue;
        var tag = (el.tagName || "").toLowerCase();
        if (SKIP[tag]) continue;
        s += inlineNode(el);
      }
      return s;
    }

    function listBlock(el, depth, ordered){
      var out = [], idx = 0, kids = el.children || [];
      for (var i = 0; i < kids.length; i++) {
        var li = kids[i];
        if ((li.tagName || "").toLowerCase() !== "li") continue;
        idx++;
        var own = "", cn = li.childNodes || [];
        for (var k = 0; k < cn.length; k++) {
          var c = cn[k];
          if (c.nodeType === 3) { own += c.nodeValue; continue; }
          if (c.nodeType !== 1) continue;
          var ct = (c.tagName || "").toLowerCase();
          if (ct === "ul" || ct === "ol") continue;
          if (SKIP[ct]) continue;
          own += inlineNode(c);
        }
        var pad = new Array(depth + 1).join("  ");
        out.push(pad + (ordered ? (idx + ". ") : "- ") + own.trim());
        var subs = li.querySelectorAll(":scope > ul, :scope > ol");
        for (var j = 0; j < subs.length; j++) {
          out.push(listBlock(subs[j], depth + 1,
                             (subs[j].tagName || "").toLowerCase() === "ol"));
        }
      }
      return out.join("\n");
    }

    function tableBlock(el){
      var rows = [], trs = el.querySelectorAll("tr");
      for (var i = 0; i < trs.length; i++) {
        var cells = trs[i].children, line = [];
        for (var j = 0; j < cells.length; j++) {
          line.push(inline(cells[j]).trim().replace(/\|/g, "\\|"));
        }
        if (!line.length) continue;
        rows.push("| " + line.join(" | ") + " |");
        if (i === 0) {
          var sep = [];
          for (var k = 0; k < line.length; k++) sep.push("---");
          rows.push("| " + sep.join(" | ") + " |");
        }
      }
      return rows.join("\n");
    }

    function blocks(node){
      var md = "", kids = node.childNodes || [];
      for (var i = 0; i < kids.length; i++) {
        var el = kids[i];
        if (el.nodeType === 3) {
          var raw = el.nodeValue || "";
          if (raw.trim()) md += raw.replace(/[ \t]+/g, " ");
          continue;
        }
        if (el.nodeType !== 1) continue;
        var tag = (el.tagName || "").toLowerCase();
        if (SKIP[tag]) continue;
        if (tag === "br") { md += "\n"; continue; }
        if (tag === "hr") { md += "\n\n---\n\n"; continue; }
        if (/^h[1-6]$/.test(tag)) {
          var lv = parseInt(tag.charAt(1), 10);
          md += "\n\n" + new Array(lv + 1).join("#") + " " + inline(el).trim() + "\n\n";
        } else if (tag === "pre") {
          md += "\n\n" + fence(el) + "\n\n";
        } else if (tag === "blockquote") {
          md += "\n\n" + inline(el).trim().split("\n").map(function(x){
            return "> " + x;
          }).join("\n") + "\n\n";
        } else if (tag === "ul" || tag === "ol") {
          md += "\n\n" + listBlock(el, 0, tag === "ol") + "\n\n";
        } else if (tag === "table") {
          md += "\n\n" + tableBlock(el) + "\n\n";
        } else if (tag === "p") {
          md += "\n\n" + inline(el).trim() + "\n\n";
        } else if (BLOCK[tag]) {
          md += "\n\n" + blocks(el).trim() + "\n\n";
        } else {
          md += inlineNode(el);
        }
      }
      return md;
    }

    var src = picked() || lastAnswer();
    if (!src) return "";
    // lastAnswer 拿到的是页面上的真实节点，必须先 clone 再清理，否则等于改坏用户的网页
    var root = src.cloneNode(true);
    var junk = root.querySelectorAll(
      "button, input, select, textarea, svg, [role='button'], [class*='copy'], [class*='toolbar']");
    for (var n = 0; n < junk.length; n++) {
      try { junk[n].parentNode.removeChild(junk[n]); } catch (e) {}
    }
    var out = blocks(root);
    out = out.replace(/\r\n/g, "\n").replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n");
    return out.trim();
  } catch (e) {
    return "";
  }
})(%s);
"""

# 抓取网页内容为富文本 HTML（保留原网页的渲染效果，直接能在 Anki 字段里正确显示）。
JS_SCRAPE_HTML = r"""
(function(sel){
  try {
    function picked(){
      try {
        var s = window.getSelection();
        if (!s || s.rangeCount === 0 || s.isCollapsed) return null;
        var r = s.getRangeAt(0);
        if (!r || !(r.toString() || "").trim()) return null;
        var wrap = document.createElement("div");
        wrap.appendChild(r.cloneContents());
        return wrap;
      } catch (e) { return null; }
    }
    function lastAnswer(){
      var sels = [];
      if (sel) sels.push(sel);
      sels = sels.concat([
        "[data-role='assistant']", "[data-message-author='assistant']",
        ".markdown-body", "article", "main .message",
        "div[class*='answer']", "div[class*='message-content']", "div[class*='assistant']"
      ]);
      for (var i = 0; i < sels.length; i++) {
        try {
          var nl = document.querySelectorAll(sels[i]);
          if (!nl || !nl.length) continue;
          for (var j = nl.length - 1; j >= 0; j--) {
            if ((nl[j].innerText || "").trim()) return nl[j];
          }
        } catch (e) {}
      }
      return null;
    }
    var root = picked() || lastAnswer();
    if (!root) return "";
    // 选区是 clone 出来的副本，改动不会影响页面本身
    var junk = root.querySelectorAll("button, svg, [role='button'], [class*='copy'], [class*='toolbar']");
    for (var i = 0; i < junk.length; i++) {
      try { junk[i].parentNode.removeChild(junk[i]); } catch (e) {}
    }
    return (root.innerHTML || "").trim();
  } catch (e) {
    return "";
  }
})(%s);
"""


class WebBackend(object):
    """
    模式 A：网页内嵌免费模式。
    本类只负责「生成脚本 / 管理预设」，真正的 WebView 由 ui/web_panel.py 提供，
    两者解耦，便于单独替换渲染层。
    """

    def __init__(self, cfg):
        self.cfg = cfg

    @staticmethod
    def normalize_url(url):
        """补全协议，避免用户只填域名导致加载失败。"""
        url = (url or "").strip()
        if not url:
            return ""
        if url.startswith(("http://", "https://", "file://", "about:")):
            return url
        return "https://" + url

    def inject_script(self, text, selector=""):
        return JS_INJECT_TEXT % (json.dumps(selector or ""), json.dumps(text))

    def scrape_script(self, selector=""):
        return JS_SCRAPE_REPLY % json.dumps(selector or "")

    def markdown_script(self, selector=""):
        """生成「抓取为 Markdown」脚本；有网页选区时抓选区，否则抓最后一条回复。"""
        return JS_SCRAPE_MARKDOWN % json.dumps(selector or "")

    def html_script(self, selector=""):
        """生成「抓取为富文本 HTML」脚本；取源规则同 markdown_script。"""
        return JS_SCRAPE_HTML % json.dumps(selector or "")

    def send_script(self, selector=""):
        return JS_CLICK_SEND % json.dumps(selector or "")


# ---------------------------------------------------------------------------
# 模式 B：OpenAI 兼容流式 API
# ---------------------------------------------------------------------------

class _StreamWorker(QThread):
    """在子线程中发起 HTTP 请求并解析 SSE，避免阻塞 Anki 主线程。"""

    chunk = pyqtSignal(str)     # 增量文本
    done = pyqtSignal(str)      # 完整文本（流式结束时也会发出）
    failed = pyqtSignal(str)    # 错误信息

    def __init__(self, endpoint, api_key, model, messages, temperature,
                 max_tokens, stream, timeout, parent=None):
        super().__init__(parent)
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model
        self.messages = messages
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.stream = stream
        self.timeout = timeout
        self._stop = False
        self._resp = None

    def stop(self):
        self._stop = True
        try:
            if self._resp is not None:
                self._resp.close()
        except Exception:
            pass

    # ---------------------------------------------------------------- 请求体
    def _payload(self):
        payload = {
            "model": self.model,
            "messages": self.messages,
            "temperature": self.temperature,
            "stream": bool(self.stream),
        }
        try:
            if int(self.max_tokens) > 0:
                payload["max_tokens"] = int(self.max_tokens)
        except Exception:
            pass
        return payload

    def _headers(self):
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.stream:
            headers["Accept"] = "text/event-stream"
        if self.api_key:
            headers["Authorization"] = "Bearer %s" % self.api_key
        return headers

    def _data(self):
        return json.dumps(self._payload(), ensure_ascii=False).encode("utf-8")

    # ---------------------------------------------------------------- SSE 解析
    @staticmethod
    def _parse_delta(obj):
        """兼容 OpenAI / DeepSeek / Moonshot 等常见的 chat.completions 返回结构。"""
        try:
            choices = obj.get("choices") or []
            if not choices:
                return ""
            first = choices[0] or {}
            delta = first.get("delta") or {}
            if isinstance(delta, dict) and delta.get("content"):
                return delta["content"]
            msg = first.get("message") or {}
            if isinstance(msg, dict) and msg.get("content"):
                return msg["content"]
            if first.get("text"):
                return first["text"]
        except Exception:
            pass
        return ""

    def _consume(self, lines_iter):
        buf = []
        for line in lines_iter:
            if self._stop:
                break
            if line is None:
                continue
            line = line.strip()
            if not line:
                continue
            if line.startswith(":"):        # SSE 心跳注释
                continue
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except Exception:
                continue
            txt = self._parse_delta(obj)
            if txt:
                buf.append(txt)
                self.chunk.emit(txt)
        return "".join(buf)

    # ---------------------------------------------------------------- 主流程
    def run(self):
        buf = ""
        try:
            data = self._data()
            headers = self._headers()

            try:
                import requests  # Anki 自带

                resp = requests.post(
                    self.endpoint, data=data, headers=headers,
                    timeout=(10, max(10, int(self.timeout))), stream=True,
                )
                self._resp = resp
                if resp.status_code >= 400:
                    try:
                        detail = resp.text[:400]
                    except Exception:
                        detail = ""
                    self.failed.emit("HTTP %s：%s" % (resp.status_code, detail))
                    self.done.emit("")
                    return
                if self.stream:
                    buf = self._consume(resp.iter_lines(decode_unicode=True))
                else:
                    obj = resp.json()
                    buf = self._parse_delta(obj) or ""
                    if buf:
                        self.chunk.emit(buf)
            except ImportError:
                # 兜底：标准库 urllib（同样支持流式读取）
                req = urllib.request.Request(self.endpoint, data=data, headers=headers,
                                             method="POST")
                with urllib.request.urlopen(req, timeout=max(10, int(self.timeout))) as resp:
                    self._resp = resp
                    if self.stream:
                        def _gen():
                            for raw in resp:
                                yield raw.decode("utf-8", "replace")
                        buf = self._consume(_gen())
                    else:
                        obj = json.loads(resp.read().decode("utf-8", "replace"))
                        buf = self._parse_delta(obj) or ""
                        if buf:
                            self.chunk.emit(buf)
            except Exception as e:
                # requests 存在但请求过程出错
                self.failed.emit(str(e))
                self.done.emit("")
                return

            self.done.emit(buf)
        except Exception as e:
            msg = str(e)
            if isinstance(e, urllib.error.HTTPError):
                try:
                    msg = "HTTP %s：%s" % (e.code, e.read().decode("utf-8", "replace")[:300])
                except Exception:
                    msg = "HTTP %s" % e.code
            self.failed.emit(msg)
            self.done.emit(buf)


class ApiBackend(QObject):
    """模式 B：OpenAI 兼容接口（同步/流式），对上层只暴露 Qt 信号。"""

    started = pyqtSignal()
    chunkReceived = pyqtSignal(str)
    finished = pyqtSignal(str)
    errorOccurred = pyqtSignal(str)

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._worker = None

    def is_busy(self):
        return self._worker is not None and self._worker.isRunning()

    def send(self, messages):
        """发起一次对话；返回是否成功启动。"""
        if self.is_busy():
            self.errorOccurred.emit("上一次请求仍在进行中")
            return False

        api = self.cfg.get("api", {}) or {}
        endpoint = (api.get("endpoint") or "").strip()
        if not endpoint:
            self.errorOccurred.emit("未配置 API 地址（设置 → API 模式）")
            return False
        if not (api.get("model") or "").strip():
            self.errorOccurred.emit("未配置模型名称（设置 → API 模式）")
            return False

        worker = _StreamWorker(
            endpoint=endpoint,
            api_key=(api.get("api_key") or "").strip(),
            model=(api.get("model") or "").strip(),
            messages=messages,
            temperature=float(api.get("temperature", 0.3) or 0.3),
            max_tokens=int(api.get("max_tokens", 2048) or 0),
            stream=bool(api.get("stream", True)),
            timeout=int(api.get("timeout", 120) or 120),
            parent=self,
        )
        worker.chunk.connect(self.chunkReceived)
        worker.failed.connect(self.errorOccurred)
        worker.done.connect(self._on_done)
        worker.finished.connect(self._cleanup)  # QThread.finished：线程结束，回收对象

        self._worker = worker
        self.started.emit()
        worker.start()
        return True

    def cancel(self):
        if self._worker is not None:
            self._worker.stop()

    def _on_done(self, text):
        self.finished.emit(text or "")

    def _cleanup(self):
        try:
            if self._worker is not None:
                self._worker.deleteLater()
        except Exception:
            pass
        self._worker = None
