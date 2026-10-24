# -*- coding: utf-8 -*-
"""
chat_page.py —— 生成消息区的 HTML 页面（OmniChat 风格）。

页面以本地文件形式写入 数据目录/web/chat.html，再用 file:// 载入 QWebEngineView。
这样做的原因：相对路径引入本地 mathjax.js 在 file:// 同源下最稳定；同时 runJavaScript
可以正常调用。
"""

import os

from .latex import mathjax_config_script, prepare_mathjax, typeset_js
from ..config import data_dir

CSS = """
:root{
  --bg:#ffffff; --bg-soft:#f6f7f9; --fg:#22252a; --fg-dim:#7b818a;
  --border:#e3e6ea; --user:#e8f0fe; --user-fg:#1a2b4c; --ai:#f4f5f7; --ai-fg:#22252a;
  --accent:#4c8bf5; --code-bg:#f2f4f7; --danger:#d9534f;
}
body.night{
  --bg:#1f2125; --bg-soft:#23262b; --fg:#e6e8eb; --fg-dim:#9aa0a8;
  --border:#33383f; --user:#2d4a7a; --user-fg:#eaf1ff; --ai:#2a2d33; --ai-fg:#e6e8eb;
  --accent:#6ea8fe; --code-bg:#1b1d21; --danger:#e06c75;
}
*{box-sizing:border-box;}
html,body{margin:0;padding:0;background:var(--bg);color:var(--fg);}
body{
  font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Microsoft YaHei",
    "Helvetica Neue",Arial,sans-serif;
  font-size:14px;line-height:1.65;
}
#messages{padding:10px 12px 16px 12px;}
.msg{margin:0 0 14px 0;display:flex;flex-direction:column;}
.msg.user{align-items:flex-end;}
.msg.assistant{align-items:flex-start;}
.bubble{
  max-width:96%;padding:9px 12px;border-radius:12px;word-break:break-word;
  border:1px solid var(--border);
}
.msg.user .bubble{background:var(--user);color:var(--user-fg);border-top-right-radius:3px;}
.msg.assistant .bubble{background:var(--ai);color:var(--ai-fg);border-top-left-radius:3px;}
.msg.note .bubble{background:var(--bg-soft);color:var(--fg-dim);font-size:12px;}
.meta{font-size:11px;color:var(--fg-dim);margin:3px 4px 0 4px;}
.acts{display:flex;flex-wrap:wrap;gap:6px;margin:6px 4px 0 4px;}
.acts a{
  font-size:11px;text-decoration:none;color:var(--fg-dim);
  border:1px solid var(--border);border-radius:8px;padding:2px 8px;background:var(--bg-soft);
}
.acts a:hover{color:var(--accent);border-color:var(--accent);}
.streaming .bubble{border-color:var(--accent);}
#typing{padding:0 14px 10px 14px;color:var(--fg-dim);font-size:12px;display:none;}
#typing.on{display:block;}
/* 行内元素 */
p{margin:0 0 8px 0;}
p:last-child{margin-bottom:0;}
h1,h2,h3,h4,h5,h6{margin:10px 0 6px 0;font-size:15px;line-height:1.35;}
h1{font-size:18px;}h2{font-size:16px;}h3{font-size:15px;}
ul,ol{margin:6px 0 8px 0;padding-left:22px;}
li{margin:2px 0;}
blockquote{
  margin:6px 0;padding:4px 10px;border-left:3px solid var(--accent);
  color:var(--fg-dim);background:var(--bg-soft);
}
hr{border:none;border-top:1px solid var(--border);margin:10px 0;}
code{
  font-family:"JetBrains Mono",Consolas,"Courier New",monospace;
  background:var(--code-bg);padding:1px 4px;border-radius:4px;font-size:12px;
}
pre.aoc-code{
  background:var(--code-bg);border:1px solid var(--border);border-radius:8px;
  padding:8px 10px;overflow:auto;margin:8px 0;
}
pre.aoc-code code{background:none;padding:0;font-size:12px;line-height:1.5;}
table{border-collapse:collapse;margin:8px 0;font-size:13px;}
th,td{border:1px solid var(--border);padding:4px 8px;text-align:left;}
th{background:var(--bg-soft);}
a.aoc-link{color:var(--accent);}
.aoc-math{font-family:"Latin Modern Math",Cambria Math,serif;}
.aoc-math-block{display:block;margin:8px 0;text-align:center;}
del{color:var(--fg-dim);}
#empty{color:var(--fg-dim);font-size:12px;padding:14px 6px;}
"""

JS = """
(function(){
  var msgEl = document.getElementById('messages');
  var streamEl = null;
  var typingEl = document.getElementById('typing');

  function nearBottom(){
    return (msgEl.scrollHeight - msgEl.scrollTop - msgEl.clientHeight) < 140;
  }
  function toBottom(){
    try { msgEl.scrollTop = msgEl.scrollHeight; } catch(e){}
  }
  function typeset(root){
    try {
      if (window.MathJax && window.MathJax.typesetPromise) {
        window.MathJax.typesetPromise(root ? [root] : []).catch(function(){});
      } else if (window.MathJax && window.MathJax.Hub) {
        window.MathJax.Hub.Queue(['Typeset', window.MathJax.Hub, root || document.body]);
      }
    } catch(e){}
  }

  window.__aoc = {
    setMessages: function(html, emptyHint){
      var stick = nearBottom();
      msgEl.innerHTML = html || ('<div id="empty">' + (emptyHint || '') + '</div>');
      streamEl = null;
      typeset(msgEl);
      if (stick) { toBottom(); } else { toBottom(); }
    },
    setStream: function(html, done){
      var stick = nearBottom();
      if (!streamEl) {
        var d = document.createElement('div');
        d.className = 'msg assistant streaming';
        d.innerHTML = '<div class="bubble"></div>';
        msgEl.appendChild(d);
        streamEl = d.firstChild;
      }
      streamEl.innerHTML = html;
      if (done) { var m = document.getElementById('messages').lastChild; if (m) { m.className = 'msg assistant'; } }
      typeset(msgEl);
      if (stick) { toBottom(); } else { toBottom(); }
    },
    clearStream: function(){
      if (streamEl && streamEl.parentNode) { streamEl.parentNode.remove(); }
      streamEl = null;
    },
    setTyping: function(on){
      if (!typingEl) { return; }
      typingEl.className = on ? 'on' : '';
    },
    setTheme: function(night){
      try { document.body.classList.toggle('night', !!night); } catch(e){}
    },
    scrollToBottom: toBottom,
    ready: true
  };
})();
"""


def _html(night, script_src, local_mj):
    theme_class = "night" if night else ""
    fallback = "" if local_mj else """
<script>
window.addEventListener('error', function(e){
  if (e && e.target && e.target.tagName === 'SCRIPT') {
    var s = document.createElement('style');
    s.textContent = '.aoc-math{font-family:monospace;color:#888;}';
    document.head.appendChild(s);
  }
}, true);
</script>
"""
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>AnkiOmniChat</title>
<style>
%s
</style>
%s
</head>
<body class="%s">
<div id="messages"><div id="empty">还没有对话。按 Ctrl+Alt+I 注入当前卡片，然后开始提问。</div></div>
<div id="typing">正在生成…</div>
<script src="%s" onerror="window.__mjFailed=true;"></script>
<script>
%s
%s
</script>
%s
</body>
</html>
""" % (CSS, mathjax_config_script(), theme_class, script_src, typeset_js(), JS, fallback)


def ensure_chat_html(cfg, night=False):
    """
    生成（必要时覆盖）消息页面，返回其本地绝对路径。
    夜间模式只切换 class，不必重新生成文件。
    """
    web_dir = os.path.join(data_dir(cfg), "web")
    local_mj, script_src = prepare_mathjax(web_dir)
    path = os.path.join(web_dir, "chat.html")
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(_html(night, script_src, local_mj))
    except Exception:
        # 极端情况下（目录不可写）退回运行时 setHtml，由调用方处理
        return ""
    return path
