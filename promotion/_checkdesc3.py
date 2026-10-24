import json, os
from playwright.sync_api import sync_playwright
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(user_data_dir=os.path.join(ROOT,".ankiweb_profile"), headless=True)
    page = ctx.new_page()
    page.goto("https://ankiweb.net/shared/info/1939948095", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(4000)
    r = page.evaluate("""() => {
        const t = document.body.innerText || '';
        const i = t.indexOf('Source:');
        // 找到包含 Source: 文本的最后一个元素
        let el = null;
        document.querySelectorAll('*').forEach(e => {
            const s = e.innerText || '';
            if (s.indexOf('Source:') >= 0 && s.length < 400) el = e;
        });
        return { tail: t.slice(i, i+120), tag: el ? el.tagName : null,
                 html: el ? el.innerHTML.slice(0,300) : null };
    }""")
    print(json.dumps(r, ensure_ascii=False, indent=2))
    ctx.close()
