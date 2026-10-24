import json, os, time
from playwright.sync_api import sync_playwright
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
url = "https://ankiweb.net/shared/info/1939948095?cb=%d" % int(time.time()*1000)
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(user_data_dir=os.path.join(ROOT,".ankiweb_profile"), headless=True)
    page = ctx.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(4500)
    r = page.evaluate("""() => {
        const a = [...document.querySelectorAll('a')]
            .map(x => ({href:x.getAttribute('href'), text:(x.innerText||'').slice(0,40)}))
            .filter(x => x.href && (x.href.indexOf('jsdelivr')>=0 || x.href.indexOf('github.com/safeblood')>=0));
        const t = document.body.innerText || '';
        return { anchors: a, head: t.slice(t.indexOf('Description'), t.indexOf('Description')+700) };
    }""")
    print(json.dumps(r, ensure_ascii=False, indent=2))
    ctx.close()
