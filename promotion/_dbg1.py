from playwright.sync_api import sync_playwright
html = """<html><body><div class="composer">
<textarea id="t"></textarea>
<div role="button" class="ds-button ds-icon-button ds-send-btn" id="send"><svg width="24" height="24"></svg></div>
</div></body></html>"""
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    pg = b.new_page()
    pg.set_content(html, wait_until="domcontentloaded")
    r = pg.evaluate("""() => {
      const el = document.querySelector("[role='button'][class*='send' i]");
      if (!el) return {found:false};
      const r = el.getBoundingClientRect();
      const cs = getComputedStyle(el);
      return {found:true, tag:el.tagName, cls:el.className, w:r.width, h:r.height,
              display:cs.display, vis:cs.visibility, op:cs.opacity, disabled:el.disabled};
    }""")
    print(r)
    b.close()
