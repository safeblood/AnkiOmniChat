"""只读检查 AnkiWeb 公开页上描述区到底渲染成了什么（尤其是 GIF 的 img 标签）。

无头模式，不打开可见窗口，不切用户的屏幕。
"""
import json
import os
import sys

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE = os.path.join(ROOT, ".ankiweb_profile")
URL = "https://ankiweb.net/shared/info/1939948095"

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=PROFILE, headless=True, args=["--disable-blink-features=AutomationControlled"]
    )
    page = ctx.new_page()
    page.goto(URL, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(4000)

    info = page.evaluate("""() => {
        // 找到包含描述的容器：SvelteKit 页面里描述通常在某个 div/blockquote 下
        const imgs = [...document.querySelectorAll('img')].map(el => ({
            src: el.getAttribute('src'),
            w: el.naturalWidth, h: el.naturalHeight,
            clientW: el.clientWidth,
            alt: el.getAttribute('alt'),
        }));
        const bodyText = document.body.innerText || '';
        // 描述区：抓整个 body 的 innerHTML 里是否出现 cdn.jsdelivr
        const html = document.body.innerHTML;
        return {
            imgs: imgs,
            hasCdn: html.indexOf('cdn.jsdelivr') >= 0,
            escaped: html.indexOf('&lt;img') >= 0 || html.indexOf('&lt;p&gt;') >= 0,
            textHasImgTag: bodyText.indexOf('<img') >= 0,
            head: bodyText.slice(0, 400),
        };
    }""")
    print(json.dumps(info, ensure_ascii=False, indent=2))
    ctx.close()
