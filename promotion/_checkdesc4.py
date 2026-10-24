import json, os
from playwright.sync_api import sync_playwright
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(user_data_dir=os.path.join(ROOT,".ankiweb_profile"), headless=True)
    page = ctx.new_page()
    page.goto("https://ankiweb.net/shared/info/1939948095", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(4000)
    r = page.evaluate("""() => {
        const out = {};
        out.anchors = [...document.querySelectorAll('a')]
            .map(a => ({href:a.getAttribute('href'), text:(a.innerText||'').slice(0,40)}))
            .filter(a => a.href && (a.href.indexOf('github.com')>=0 || a.href.indexOf('jsdelivr')>=0));
        const t = document.body.innerText || '';
        const i = t.indexOf('Source');
        out.tail = t.slice(Math.max(0,i-500), i+200);
        return out;
    }""")
    print(json.dumps(r, ensure_ascii=False, indent=2))
    ctx.close()
