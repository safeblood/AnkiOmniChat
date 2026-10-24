import json, os
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".dsprobe"),
        headless=True, args=["--disable-blink-features=AutomationControlled"])
    page = ctx.new_page()
    page.goto("https://chat.deepseek.com/", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(6000)
    print("URL:", page.url)
    print("TITLE:", page.title())
    r = page.evaluate("""() => {
        const out = [];
        const push = (el) => {
            const r = el.getBoundingClientRect();
            if (r.width < 8 || r.height < 8) return;
            out.push({
                tag: el.tagName, role: el.getAttribute('role'),
                aria: (el.getAttribute('aria-label')||'').slice(0,60),
                cls: (typeof el.className === 'string' ? el.className : '').slice(0,80),
                id: el.id || '', type: el.type || '',
                w: Math.round(r.width), h: Math.round(r.height),
                txt: (el.innerText||'').slice(0,20),
                disabled: !!el.disabled,
            });
        };
        document.querySelectorAll('button, [role=button], div[class*=send], div[class*=Send], textarea, [contenteditable=true]').forEach(push);
        return out;
    }""")
    print(json.dumps(r, ensure_ascii=False, indent=1)[:4000])
    ctx.close()
