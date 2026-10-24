"""离线验证 JS_CLICK_SEND 的多层兜底。

用几个仿真的页面 DOM 跑真实的 JS：DeepSeek 风格（div[role=button] + ds- class，无 aria-label）、
传统 submit、按钮 disabled、以及完全找不到按钮（应落到 Enter 兜底）。
无头运行，不切用户屏幕。
"""
import json
import os
import re

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, "AnkiOmniChat", "backend.py")

src = open(BACKEND, encoding="utf-8").read()
m = re.search(r'JS_CLICK_SEND = """(.*?)"""', src, re.S)
if not m:
    raise SystemExit("没抠出 JS_CLICK_SEND")
JS = m.group(1)

CASES = {
    # DeepSeek 风格：div[role=button]，class 含 send，没有 aria-label，也不是 submit
    "deepseek-like": """
        <div class="input-wrap">
          <textarea id="chat-input">你好</textarea>
          <div class="composer">
            <div role="button" class="ds-button ds-icon-button ds-send-btn" id="send">
              <svg width="24" height="24"></svg>
            </div>
          </div>
        </div>
        <script>window.__clicked = [];
          document.getElementById('send').addEventListener('click', function(){ window.__clicked.push('send'); });
        </script>
    """,
    # 传统表单（preventDefault，免得提交导致页面重载、计数被清掉）
    "classic-submit": """
        <form onsubmit="return false"><textarea>hi</textarea>
        <button type="submit" aria-label="发送">go</button></form>
        <script>window.__clicked=[];
          document.querySelector('button').addEventListener('click',function(){window.__clicked.push('submit');});
        </script>
    """,
    # 发送按钮 disabled（输入框为空时的常见状态）—— 旧写法会直接 not-found
    "disabled-then-enter": """
        <div class="wrap">
          <textarea id="t"></textarea>
          <div role="button" class="ds-send" disabled>x</div>
        </div>
        <script>window.__clicked=[];
          document.getElementById('t').addEventListener('keydown',function(e){
            if(e.key==='Enter'){window.__clicked.push('enter');}});
        </script>
    """,
    # 只有输入框，没有任何按钮 —— 应落到 Enter 兜底
    "no-button": """
        <div><textarea id="t"></textarea></div>
        <script>window.__clicked=[];
          document.getElementById('t').addEventListener('keydown',function(e){
            if(e.key==='Enter'){window.__clicked.push('enter');}});
        </script>
    """,
    # 就近查找：按钮上没有 send 字样，但就在输入框的父容器里（真实的图标按钮尺寸）
    "near-only": """
        <div class="composer">
          <textarea id="t"></textarea>
          <div role="button" class="ad5f3" style="width:36px;height:36px">↑</div>
        </div>
        <script>window.__clicked=[];
          document.querySelectorAll('[role=button]')[0].addEventListener('click',function(){window.__clicked.push('near');});
        </script>
    """,
    # 块级 div 撑满整行（没有显式宽高）—— 早期被 160/200 的尺寸上限误杀
    "block-level-send": """
        <div class="composer">
          <textarea id="t"></textarea>
          <div role="button" class="ds-button ds-send"><svg width="24" height="24"></svg></div>
        </div>
        <script>window.__clicked=[];
          document.querySelectorAll('[role=button]')[0].addEventListener('click',function(){window.__clicked.push('block-send');});
        </script>
    """,
    # 容器也带 send 类名：应该点到里面那个小按钮，而不是整块容器
    "container-fake": """
        <div class="send-wrapper" role="button">
          <textarea id="t"></textarea>
          <div role="button" class="x9" style="width:32px;height:32px">↑</div>
        </div>
        <script>window.__clicked=[];
          document.querySelector('.send-wrapper').addEventListener('click',function(){window.__clicked.push('WRONG-container');});
          document.querySelector('.x9').addEventListener('click',function(){window.__clicked.push('real-send');});
        </script>
    """,
}

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=os.path.join(ROOT, ".sendsel_probe"), headless=True)
    page = ctx.new_page()
    results = {}
    for name, body in CASES.items():
        page.set_content("<html><body>%s</body></html>" % body, wait_until="domcontentloaded")
        page.wait_for_timeout(300)
        ret = page.evaluate("(js) => eval(js)", JS % json.dumps(""))
        clicked = page.evaluate("() => window.__clicked || []")
        results[name] = {"returned": ret, "clicked": clicked}
        print("%-20s -> %-28s clicked=%s" % (name, ret, clicked))
    ctx.close()

print()
print(json.dumps(results, ensure_ascii=False, indent=1))
