"""摸清 AnkiWeb 描述区的渲染规则：URL 是否自动成链、markdown 加粗是否生效。无头只读。"""
import json
import os

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
        const out = {};
        // 所有外链
        out.anchors = [...document.querySelectorAll('a')]
            .map(a => ({href: a.getAttribute('href'), text: (a.innerText||'').slice(0,50)}))
            .filter(a => a.href && a.href.indexOf('http') === 0);
        // 反引号/星号是否原样出现（说明不支持 markdown）
        const t = document.body.innerText || '';
        out.hasStars = t.indexOf('**') >= 0;
        // 找到描述容器：取 innerText 最长且含 'Mode A' 的块
        let best = null, bestLen = 0;
        document.querySelectorAll('div,section,article,p,td').forEach(el => {
            const txt = el.innerText || '';
            if (txt.indexOf('Mode A') >= 0 && txt.length > bestLen) { bestLen = txt.length; best = el; }
        });
        if (best) {
            out.descTag = best.tagName + '.' + (best.className || '');
            out.descHtmlHead = best.innerHTML.slice(0, 1200);
            out.descText = (best.innerText || '').slice(0, 900);
        }
        return out;
    }""")
    print(json.dumps(info, ensure_ascii=False, indent=2))
    ctx.close()
