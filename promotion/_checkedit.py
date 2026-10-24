import json, os
from playwright.sync_api import sync_playwright
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(user_data_dir=os.path.join(ROOT,".ankiweb_profile"), headless=True)
    page = ctx.new_page()
    # 先开 info 页再点 Update（skill 说明：直接 goto upload 不渲染 Branches）
    page.goto("https://ankiweb.net/shared/info/1939948095", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(3000)
    page.goto("https://ankiweb.net/shared/upload?id=1939948095", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(4000)
    r = page.evaluate("""() => {
        const ta = document.querySelector('textarea');
        return { found: !!ta, value: ta ? ta.value.slice(0, 1200) : null };
    }""")
    print(json.dumps(r, ensure_ascii=False, indent=2))
    ctx.close()
