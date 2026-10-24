# -*- coding: utf-8 -*-
"""
ankiweb.py —— AnkiWeb 插件发布 / 更新的统一命令行工具。

把反复踩坑后沉淀下来的流程固化成一个脚本，支持任意 Anki 插件，
除了 playwright 之外不依赖任何第三方库（`pack` 子命令连库都不需要）。

子命令
------
    pack          把插件目录打成 .ankiaddon（纯标准库）
    login         打开浏览器让你登录一次，登录态存到本地 profile 长期复用
    new           首次发布：填基本信息 -> 新建分支 -> 传包 -> 版本范围 -> 保存
    update        更新已发布插件：进编辑页 -> 传包 -> 保存
    fix-versions  单独修正已发布插件的分支版本范围（必要时重传包）
    verify        只读校验：版本范围 / 上传框 / 公开页状态
    status        打印当前配置与上次结果

配置优先级：命令行参数 > publish.json > 内置默认值。
所有路径默认相对当前工作目录。

用法示例
--------
    python ankiweb.py status
    python ankiweb.py pack
    python ankiweb.py login
    python ankiweb.py new  --dry-run     # 填好表单但不提交，先看看对不对
    python ankiweb.py new
    python ankiweb.py update
    python ankiweb.py verify
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

LOGIN_URL = "https://ankiweb.net/account/login"
UPLOAD_URL = "https://ankiweb.net/shared/upload"

# 打包时要剔除的目录/文件（插件用户的本地数据与缓存不该进包）
EXCLUDE_DIRS = {"__pycache__", "user_files", ".git", ".idea", ".vscode",
                "node_modules", ".mypy_cache", ".pytest_cache"}
EXCLUDE_FILES = {".gitignore", ".DS_Store", "Thumbs.db", ".ankiweb_profile"}


# ------------------------------------------------------------------ 基础工具
def log(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def die(msg, code=1):
    log("错误：%s" % msg)
    sys.exit(code)


def load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {} if default is None else default


def save_json(path, data):
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_config(args):
    """合并配置：publish.json 打底，命令行参数覆盖。"""
    cfg_path = args.config
    cfg = load_json(cfg_path, {}) if cfg_path and os.path.exists(cfg_path) else {}
    if cfg_path and not os.path.exists(cfg_path):
        log("提示：未找到配置文件 %s，将全部依赖命令行参数" % cfg_path)

    def pick(key, cli_val, default=""):
        if cli_val not in (None, ""):
            return cli_val
        v = cfg.get(key, default)
        return "" if v is None else v

    def pick_int(key, cli_val, default):
        return cli_val if cli_val else int(cfg.get(key, default) or default)

    out = {
        "addon_dir": pick("addon_dir", getattr(args, "addon_dir", None), ""),
        "zip": pick("zip", getattr(args, "zip", None), ""),
        "profile": pick("profile", getattr(args, "profile", None), ".ankiweb_profile"),
        "work_dir": pick("work_dir", getattr(args, "work_dir", None), ".ankiweb"),
        "addon_id": pick("addon_id", getattr(args, "addon_id", None), ""),
        "title": pick("title", getattr(args, "title", None), ""),
        "tags": pick("tags", getattr(args, "tags", None), ""),
        "support": pick("support", getattr(args, "support", None), ""),
        "description": pick("description", getattr(args, "description", None), ""),
        "description_file": pick("description_file", getattr(args, "description_file", None), ""),
        "min_version": pick("min_version", getattr(args, "min_version", None), "2.1.60"),
        "max_version": pick("max_version", getattr(args, "max_version", None), "26.09"),
        "headless": bool(getattr(args, "headless", False) or cfg.get("headless", False)),
        "wait_login": pick_int("wait_login", getattr(args, "wait_login", None), 900),
    }
    if not out["zip"] and out["addon_dir"]:
        out["zip"] = out["addon_dir"].rstrip("\\/") + ".ankiaddon"
    if out["description_file"] and os.path.exists(out["description_file"]):
        try:
            with open(out["description_file"], "r", encoding="utf-8") as f:
                out["description"] = f.read()
        except Exception as e:
            log("读取 description_file 失败：%s" % e)
    out["_cfg_path"] = cfg_path
    return out


def ensure_dirs(cfg):
    os.makedirs(cfg["work_dir"], exist_ok=True)
    os.makedirs(os.path.join(cfg["work_dir"], "shots"), exist_ok=True)


def state_path(cfg):
    return os.path.join(cfg["work_dir"], "state.json")


def result_path(cfg):
    return os.path.join(cfg["work_dir"], "result.json")


# ------------------------------------------------------------------ pack
def cmd_pack(cfg, args):
    addon_dir = cfg["addon_dir"]
    if not addon_dir or not os.path.isdir(addon_dir):
        die("请指定插件目录（--addon-dir 或 publish.json 的 addon_dir）")
    zip_path = cfg["zip"] or (addon_dir.rstrip("\\/") + ".ankiaddon")

    meta_path = os.path.join(addon_dir, "meta.json")
    if not os.path.exists(meta_path):
        log("警告：插件目录下没有 meta.json，AnkiWeb 可能拒绝该包")

    names = []
    import zipfile
    base = os.path.abspath(addon_dir)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIRS]
            for f in files:
                if f in EXCLUDE_FILES or f.endswith((".pyc", ".pyo")):
                    continue
                p = os.path.join(root, f)
                arc = os.path.relpath(p, base)
                z.write(p, arc)
                names.append(arc)

    bad = [n for n in names if n.startswith(os.path.basename(base) + os.sep)
           or n.startswith(os.path.basename(base) + "/")]
    log("打包完成：%s（%d 个文件，%.0f KB）"
        % (zip_path, len(names), os.path.getsize(zip_path) / 1024.0))
    if bad:
        die("包结构非法：zip 内不能再套一层插件目录（发现 %s）" % bad[0])
    with zipfile.ZipFile(zip_path) as z:
        top = sorted({n.split("/")[0].split("\\")[0] for n in z.namelist()})
    log("顶层条目：%s" % ", ".join(top[:12]))
    if not names:
        die("打包结果为空，请检查 addon_dir 是否填错")

    # 可选：本地语法校验，避免把有明显语法错误的包传上去
    if not args.no_check:
        check_python_syntax(addon_dir)

    save_json(state_path(cfg), {
        "packed": True, "zip": os.path.abspath(zip_path),
        "files": len(names), "at": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    return 0


def check_python_syntax(addon_dir):
    try:
        r = subprocess.run(
            [sys.executable, "-m", "compileall", "-q", addon_dir],
            capture_output=True, text=True, timeout=120)
        if r.returncode == 0:
            log("语法检查通过")
        else:
            log("语法检查发现问题：\n%s" % (r.stderr or r.stdout)[:800])
    except Exception as e:
        log("跳过语法检查：%s" % e)


# ------------------------------------------------------------------ playwright 相关
def require_playwright():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except ImportError:
        log("缺少 playwright。安装：")
        log("  pip install playwright && playwright install chromium")
        die("playwright 不可用", 3)
    from playwright.sync_api import sync_playwright
    return sync_playwright


def launch(sync_playwright, cfg):
    os.makedirs(cfg["profile"], exist_ok=True)
    ctx = sync_playwright.chromium.launch_persistent_context(
        cfg["profile"],
        headless=cfg["headless"],
        viewport={"width": 1280, "height": 960},
        args=["--disable-blink-features=AutomationControlled"],
    )
    ctx.set_default_timeout(25000)
    ctx.on("dialog", lambda d: (log("对话框 %s：%s" % (d.type, d.message[:120])), d.accept()))
    return ctx


def snapshot(page, cfg, name):
    try:
        shots = os.path.join(cfg["work_dir"], "shots")
        os.makedirs(shots, exist_ok=True)
        page.screenshot(path=os.path.join(shots, name + ".png"), full_page=True)
        with open(os.path.join(shots, name + ".txt"), "w", encoding="utf-8") as f:
            f.write(page.url + "\n\n" + page.inner_text("body")[:3000])
        log("快照已保存 %s" % name)
    except Exception as e:
        log("快照失败：%s" % e)


def dump_form(page, tag=""):
    """列出页面上所有 input/button/textarea/select，便于排查选择器失效。"""
    try:
        info = page.evaluate("""() => {
            const out = [];
            document.querySelectorAll('input,button,textarea,select').forEach(el => {
                const cs = getComputedStyle(el);
                const r = el.getBoundingClientRect();
                out.push({
                    tag: el.tagName, type: el.type || '', name: el.name || '',
                    id: el.id || '', ph: el.placeholder || '',
                    text: (el.innerText || el.value || '').slice(0, 60),
                    hidden: cs.display === 'none' || cs.visibility === 'hidden',
                    vis: (r.width > 0 || r.height > 0),
                });
            });
            return out;
        }""")
    except Exception as e:
        log("dump_form 失败：%s" % e)
        return []
    log("---- 页面元素 %s ----" % tag)
    for it in info:
        log("  %(tag)s type=%(type)s vis=%(vis)s hidden=%(hidden)s ph=[%(ph)s] text=[%(text)s]" % it)
    log("---- 元素结束 ----")
    return info


def set_versions(page, min_v, max_v):
    """
    填写分支版本范围的两个输入框。

    坑记录：AnkiWeb 是 Svelte SPA，这两个框在 HTML 里**没有 type 属性**，
    CSS 选择器 `input[type=text]` 抓不到；而且它们的 value 由框架托管，
    直接赋值不触发更新。必须走原生 setter + 派发 input/change 事件。
    """
    info = page.evaluate("""([minV, maxV]) => {
        const inputs = [...document.querySelectorAll('input')].filter(el => {
            if (el.type !== 'text') return false;
            if (el.getAttribute('placeholder')) return false;
            if (el.offsetParent === null && getComputedStyle(el).position !== 'fixed') return false;
            return true;
        });
        if (inputs.length < 2) return {ok: false, n: inputs.length};
        const setter = Object.getOwnPropertyDescriptor(
            HTMLInputElement.prototype, 'value').set;
        function put(el, v) {
            setter.call(el, v);
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
        }
        put(inputs[0], minV);
        put(inputs[1], maxV);
        return {ok: true, n: inputs.length, v0: inputs[0].value, v1: inputs[1].value};
    }""", [min_v, max_v])
    log("版本框填写：%s" % info)
    page.wait_for_timeout(800)
    return bool(info.get("ok")) and info.get("v0") == min_v and info.get("v1") == max_v


def read_versions(page):
    try:
        return page.evaluate("""() => [...document.querySelectorAll('input')]
            .filter(el => el.type === 'text' && !el.getAttribute('placeholder')
                          && el.offsetParent !== null)
            .map(el => el.value)""")
    except Exception as e:
        log("读取版本框失败：%s" % e)
        return []


def click_any(page, selectors, label):
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible():
                loc.click(timeout=8000)
                log("已点击 %s（%s）" % (label, sel))
                return True
        except Exception:
            continue
    log("点击 %s 失败" % label)
    return False


def fill_first(page, selectors, value, label):
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() and loc.is_visible():
                loc.fill(value, timeout=6000)
                log("已填 %s" % label)
                return True
        except Exception:
            continue
    log("填写 %s 失败" % label)
    return False


def upload_and_save(page, cfg, dry_run=False, tag="save"):
    """公共部分：等待上传框 -> 传包 -> 设置版本范围 -> 保存。返回 (ok, addon_id)。"""
    zip_path = cfg["zip"]
    if not zip_path or not os.path.exists(zip_path):
        die("找不到插件包 %s，先跑 `pack`" % zip_path, 4)
    zip_path = os.path.abspath(zip_path)

    try:
        page.wait_for_selector("input[type=file]", timeout=25000)
    except Exception as e:
        log("等待上传框超时：%s" % str(e)[:150])
        snapshot(page, cfg, tag + "-no-file-input")
        return False, None

    page.set_input_files("input[type=file]", zip_path, timeout=20000)
    log("已选择文件：%s" % os.path.basename(zip_path))
    page.wait_for_timeout(1500)

    set_versions(page, cfg["min_version"], cfg["max_version"])
    snapshot(page, cfg, tag + "-before-save")

    if dry_run:
        log("dry-run：表单已填好，**未提交**。快照见 %s" % os.path.join(cfg["work_dir"], "shots"))
        dump_form(page, "dry-run")
        return True, None

    if not click_any(page, ["button:has-text('Save')", "button[type=submit]",
                            "button:has-text('Update')"], "保存"):
        snapshot(page, cfg, tag + "-no-save-btn")
        return False, None

    page.wait_for_timeout(5000)
    log("提交后 URL：%s" % page.url)
    snapshot(page, cfg, tag + "-after-save")
    body = page.inner_text("body")
    log("页面文本：%s" % body[:400].replace("\n", " | "))

    bad = re.search(r"(?i)(error|invalid|not allowed|must be|too large)", body)
    mid = re.search(r"/shared/info/(\d+)", page.url) or re.search(r"\b(\d{6,10})\b", body)
    addon_id = mid.group(1) if mid else None
    if bad and not addon_id:
        log("页面出现错误提示，请查看快照")
        return False, None
    if addon_id:
        log("成功！add-on ID = %s" % addon_id)
    return True, addon_id


# ------------------------------------------------------------------ 登录
def logged_in(ctx):
    """用 context 自带的请求上下文探测登录态 —— 纯 HTTP，不碰 UI、不会跳页面。"""
    try:
        r = ctx.request.get(UPLOAD_URL, timeout=30000)
        final = getattr(r, "url", "") or UPLOAD_URL
        if "/account/login" in final:
            return False
        txt = r.text() or ""
        # 未登录的上传页会提示先登录（注意大小写：页面上是 "Log In"）
        if re.search(r"\bLog In\b", txt) or re.search(r"\bSign Up\b", txt):
            return False
        return True
    except Exception as e:
        log("登录态探测异常：%s" % str(e)[:120])
        return False


def ensure_login(ctx, cfg):
    if logged_in(ctx):
        log("已检测到登录态，跳过登录流程")
        return True
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(LOGIN_URL, wait_until="domcontentloaded")
    log("=" * 60)
    log("请在弹出的浏览器窗口中登录 AnkiWeb（没有账号就点 Sign Up 注册）。")
    log("脚本只做 HTTP 层面的登录态检测，**不会刷新或跳转你正在操作的页面**。")
    log("=" * 60)
    deadline = time.time() + int(cfg["wait_login"])
    while time.time() < deadline:
        if logged_in(ctx):
            log("登录成功")
            return True
        time.sleep(5)
    log("等待登录超时（%s 秒）" % cfg["wait_login"])
    return False


def cmd_login(cfg, args):
    sync_playwright = require_playwright()
    with sync_playwright() as p:
        ctx = launch(p, cfg)
        try:
            ok = ensure_login(ctx, cfg)
            log("登录态保持目录：%s" % os.path.abspath(cfg["profile"]))
            return 0 if ok else 5
        finally:
            try:
                ctx.close()
            except Exception:
                pass


# ------------------------------------------------------------------ new
def cmd_new(cfg, args):
    sync_playwright = require_playwright()
    need = ["title", "tags", "support", "description"]
    missing = [k for k in need if not cfg.get(k)]
    if missing:
        die("首次发布缺少必填项：%s（写在 publish.json 或用命令行传）" % ", ".join(missing))

    with sync_playwright() as p:
        ctx = launch(p, cfg)
        try:
            if not ensure_login(ctx, cfg):
                return 5
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            page.goto(UPLOAD_URL, wait_until="domcontentloaded")
            try:
                page.wait_for_selector("input[placeholder^='Title']", timeout=25000)
            except Exception:
                log("表单未按时渲染，等待更久一点")
                page.wait_for_timeout(4000)
            dump_form(page, "基本信息")

            fill_first(page, ["input[placeholder^='Title']", "input[placeholder*='title' i]"],
                       cfg["title"], "Title")
            fill_first(page, ["input[placeholder^='Tags']", "input[placeholder*='tag' i]"],
                       cfg["tags"], "Tags")
            fill_first(page, ["input[placeholder^='Support Page']",
                              "input[placeholder*='support' i]"], cfg["support"], "Support Page")
            fill_first(page, ["textarea"], cfg["description"], "Description")
            page.wait_for_timeout(800)

            if not click_any(page,
                             ["button:has-text('Add New Branch')",
                              "text=Add New Branch"], "Add New Branch"):
                snapshot(page, cfg, "new-branch-btn-failed")
                return 6
            page.wait_for_timeout(2500)
            dump_form(page, "分支表单")
            snapshot(page, cfg, "new-branch-form")

            ok, addon_id = upload_and_save(page, cfg, dry_run=args.dry_run, tag="new")
            res = {"addon_id": addon_id,
                   "url": ("https://ankiweb.net/shared/info/%s" % addon_id) if addon_id else None,
                   "dry_run": bool(args.dry_run),
                   "at": time.strftime("%Y-%m-%d %H:%M:%S")}
            save_json(result_path(cfg), res)
            if addon_id:
                log("插件地址：https://ankiweb.net/shared/info/%s" % addon_id)
                log("建议把 addon_id 写回 publish.json 和插件的 meta.json 的 ankiweb_id 字段")
            return 0 if ok else 7
        finally:
            try:
                ctx.close()
            except Exception:
                pass


# ------------------------------------------------------------------ update / fix
def open_edit_page(page, cfg, addon_id):
    """
    坑记录：直接 goto /shared/upload?id=<id> **不会渲染 Branches 区**，
    必须先打开 info 页，再点页面上的 Update 链接进入编辑页。
    """
    info_url = "https://ankiweb.net/shared/info/" + str(addon_id)
    page.goto(info_url, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)
    try:
        page.get_by_role("link", name=re.compile("^Update$", re.I)).first.click(timeout=10000)
    except Exception as e:
        log("点击 Update 链接失败：%s" % str(e)[:150])
        snapshot(page, cfg, "no-update-link")
        return False
    page.wait_for_load_state("domcontentloaded", timeout=30000)
    page.wait_for_timeout(2000)
    log("已进入编辑页：%s" % page.url)
    return True


def cmd_update(cfg, args):
    addon_id = cfg["addon_id"] or args.addon_id
    if not addon_id:
        die("缺少 addon_id（--addon-id 或 publish.json 的 addon_id）")
    sync_playwright = require_playwright()
    with sync_playwright() as p:
        ctx = launch(p, cfg)
        try:
            if not ensure_login(ctx, cfg):
                return 5
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            if not open_edit_page(page, cfg, addon_id):
                return 8
            before = read_versions(page)
            log("更新前版本范围：%s" % before)
            ok, got_id = upload_and_save(page, cfg, dry_run=args.dry_run, tag="update")
            after = read_versions(page)
            log("更新后版本范围：%s" % after)
            save_json(result_path(cfg), {
                "addon_id": addon_id, "ok": ok,
                "versions_before": before, "versions_after": after,
                "dry_run": bool(args.dry_run),
                "at": time.strftime("%Y-%m-%d %H:%M:%S")})
            return 0 if ok else 7
        finally:
            try:
                ctx.close()
            except Exception:
                pass


def cmd_fix_versions(cfg, args):
    """版本范围格式被拒绝时，依次尝试候选组合直到保存成功。"""
    addon_id = cfg["addon_id"] or args.addon_id
    if not addon_id:
        die("缺少 addon_id")
    pairs = [(cfg["min_version"], cfg["max_version"])]
    if args.alt_versions:
        for pair in args.alt_versions:
            if "-" in pair:
                a, b = pair.split("-", 1)
                pairs.append((a.strip(), b.strip()))
    # 常见写法兜底
    pairs += [("2.1.60", "26.9.3"), ("2.1.60", "26.09"), ("2.1.60", "25.09")]

    sync_playwright = require_playwright()
    with sync_playwright() as p:
        ctx = launch(p, cfg)
        try:
            if not ensure_login(ctx, cfg):
                return 5
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            seen = set()
            for mn, mx in pairs:
                if (mn, mx) in seen:
                    continue
                seen.add((mn, mx))
                if not open_edit_page(page, cfg, addon_id):
                    continue
                if not set_versions(page, mn, mx):
                    log("版本框填写失败，尝试下一组")
                    continue
                ok, _ = upload_and_save(page, cfg, dry_run=args.dry_run,
                                        tag="fix-%s" % mn.replace(".", "_"))
                if ok:
                    log("版本范围 %s - %s 保存成功" % (mn, mx))
                    save_json(result_path(cfg), {"addon_id": addon_id, "min": mn,
                                                 "max": mx, "ok": True,
                                                 "at": time.strftime("%Y-%m-%d %H:%M:%S")})
                    return 0
                log("版本范围 %s - %s 被拒绝，换下一组" % (mn, mx))
            log("所有候选组合都失败了，请查看快照里的页面提示")
            return 9
        finally:
            try:
                ctx.close()
            except Exception:
                pass


# ------------------------------------------------------------------ verify / status
def cmd_verify(cfg, args):
    addon_id = cfg["addon_id"] or args.addon_id
    if not addon_id:
        die("缺少 addon_id")
    sync_playwright = require_playwright()
    info_url = "https://ankiweb.net/shared/info/" + str(addon_id)
    with sync_playwright() as p:
        ctx = launch(p, cfg)
        try:
            if not ensure_login(ctx, cfg):
                return 5
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            if not open_edit_page(page, cfg, addon_id):
                return 8
            res = page.evaluate("""() => {
                const inputs = [...document.querySelectorAll('input')].filter(
                    el => el.type === 'text' && !el.getAttribute('placeholder')
                          && el.offsetParent !== null);
                return {
                    versionBoxes: inputs.map(el => el.value),
                    hasFileInput: !!document.querySelector('input[type=file]'),
                    branchText: (document.body.innerText.match(/Branch[\\s\\S]{0,80}/) || [''])[0],
                };
            }""")
            log("编辑页状态：%s" % res)
            snapshot(page, cfg, "verify")

            page.goto(info_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2000)
            body = page.inner_text("body")
            log("公开页：%s" % body[:400].replace("\n", " | "))
            out = {"addon_id": addon_id, "url": info_url, "edit_state": res,
                   "public_text_head": body[:400],
                   "at": time.strftime("%Y-%m-%d %H:%M:%S")}
            save_json(result_path(cfg), out)
            log(json.dumps(out, ensure_ascii=False, indent=2))
            return 0
        finally:
            try:
                ctx.close()
            except Exception:
                pass


def cmd_status(cfg, args):
    pretty = {k: v for k, v in cfg.items() if not k.startswith("_")}
    pretty["description"] = (cfg["description"][:60] + "...") if len(cfg.get("description", "")) > 60 else cfg.get("description", "")
    print(json.dumps(pretty, ensure_ascii=False, indent=2))
    for name, path in (("state", state_path(cfg)), ("result", result_path(cfg))):
        if os.path.exists(path):
            print("\n--- %s (%s) ---" % (name, path))
            print(open(path, "r", encoding="utf-8").read())
    return 0


# ------------------------------------------------------------------ 入口
def build_parser():
    ap = argparse.ArgumentParser(
        prog="ankiweb.py",
        description="AnkiWeb 插件发布 / 更新工具",
        formatter_class=argparse.RawDescriptionHelpFormatter)

    def common(sp):
        sp.add_argument("--config", default="publish.json", help="配置文件路径（默认 ./publish.json）")
        sp.add_argument("--addon-dir", help="插件目录，如 AnkiOmniChat")
        sp.add_argument("--zip", help="输出的 .ankiaddon 路径")
        sp.add_argument("--profile", help="浏览器登录态目录")
        sp.add_argument("--work-dir", help="工作产物目录（快照/state/result）")
        sp.add_argument("--addon-id", help="AnkiWeb add-on ID")
        sp.add_argument("--min-version", help="支持的最低 Anki 版本，如 2.1.60")
        sp.add_argument("--max-version", help="支持的最高 Anki 版本，如 26.09")
        sp.add_argument("--headless", action="store_true", help="无头模式（有验证码时不要用）")

    sub = ap.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("pack", help="打包插件目录为 .ankiaddon")
    common(sp)
    sp.add_argument("--no-check", action="store_true", help="跳过语法检查")

    sp = sub.add_parser("login", help="登录 AnkiWeb 并保存登录态")
    common(sp)
    sp.add_argument("--wait-login", type=int, help="等待登录的秒数")

    sp = sub.add_parser("new", help="首次发布插件")
    common(sp)
    sp.add_argument("--title")
    sp.add_argument("--tags")
    sp.add_argument("--support", help="支持页 / issue 页 URL")
    sp.add_argument("--description", help="插件介绍正文")
    sp.add_argument("--description-file", help="从文件读取介绍正文")
    sp.add_argument("--wait-login", type=int)
    sp.add_argument("--dry-run", action="store_true", help="填好表单但不提交")

    sp = sub.add_parser("update", help="更新已发布插件")
    common(sp)
    sp.add_argument("--wait-login", type=int)
    sp.add_argument("--dry-run", action="store_true")

    sp = sub.add_parser("fix-versions", help="修正分支版本范围")
    common(sp)
    sp.add_argument("--alt-versions", nargs="*", help="候选版本范围，如 2.1.60-26.9.3")
    sp.add_argument("--dry-run", action="store_true")

    sp = sub.add_parser("verify", help="只读校验插件状态")
    common(sp)
    sp.add_argument("--wait-login", type=int)

    sp = sub.add_parser("status", help="查看当前配置与上次结果")
    common(sp)
    return ap


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    cfg = load_config(args)
    if args.cmd != "status":
        ensure_dirs(cfg)
    handlers = {
        "pack": lambda: cmd_pack(cfg, args),
        "login": lambda: cmd_login(cfg, args),
        "new": lambda: cmd_new(cfg, args),
        "update": lambda: cmd_update(cfg, args),
        "fix-versions": lambda: cmd_fix_versions(cfg, args),
        "verify": lambda: cmd_verify(cfg, args),
        "status": lambda: cmd_status(cfg, args),
    }
    return handlers[args.cmd]()


if __name__ == "__main__":
    sys.exit(main())
