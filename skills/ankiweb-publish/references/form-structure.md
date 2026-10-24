# AnkiWeb 上传/编辑页表单结构

2026-10 实测（AnkiWeb 前端为 Svelte SPA），供改脚本时对照。站点可能改版，失效时先跑 `--dry-run` 重新 dump 表单。

## URL

| 用途 | 地址 |
|---|---|
| 登录 | `https://ankiweb.net/account/login` |
| 新建上传 | `https://ankiweb.net/shared/upload` |
| 公开页 | `https://ankiweb.net/shared/info/<id>` |
| 编辑/更新 | 从 info 页点 **Update** 链接进入（落到 `/shared/upload?id=<id>`） |

**注意**：`/shared/upload?id=<id>` 直接 goto 不会渲染 Branches 区，页面看着像空的。

## 上传/编辑页字段

| 字段 | 定位方式 | 备注 |
|---|---|---|
| Title | `input[placeholder^='Title']` | 必填 |
| Tags | `input[placeholder^='Tags']` | 空格分隔的小写词 |
| Support Page | `input[placeholder^='Support Page']` | 一般是 GitHub issues 页 |
| Description | `textarea` | 支持多行，纯文本，站点会保留换行 |
| Add New Branch | `button:has-text('Add New Branch')` | 新插件必须先点它才会出现分支区 |
| 文件上传 | `input[type=file]` | `application/x-zip-compressed` |
| min/max 版本 | 见下 | 分支区里的两个框 |
| Save | `button:has-text('Save')` | 提交按钮 |

## 版本范围输入框（最容易踩坑）

这两个框在 HTML 里**没有 `type` 属性**，且 value 由 Svelte 托管：

```html
<!-- 大致形态，注意没有 type=text -->
<input placeholder="" value="2.1.1">
<input placeholder="" value="2.1.1">
```

所以：

- ❌ `input[type=text]:not([placeholder])` —— 选不中
- ❌ `el.value = '2.1.60'` —— 框架不感知，提交时仍是旧值
- ✅ 按 DOM 属性筛（`el.type === 'text'` && 无 placeholder && 可见），再用原生 setter 赋值并派发事件

```javascript
const inputs = [...document.querySelectorAll('input')].filter(el => {
    if (el.type !== 'text') return false;
    if (el.getAttribute('placeholder')) return false;
    if (el.offsetParent === null && getComputedStyle(el).position !== 'fixed') return false;
    return true;
});
const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
function put(el, v) {
    setter.call(el, v);
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
}
put(inputs[0], minVersion);
put(inputs[1], maxVersion);
```

页面上同时还有其他文本框时（Title/Tags/Support），过滤后剩余的前两个就是 min/max；如顺序有变，改用 `--dry-run` 打印表单再调整。

## 版本格式

站点接受 `主.次.修订` 两段或三段。实测：

| 写法 | 结果 |
|---|---|
| `2.1.60` - `26.09` | ✅ 通过，公开页显示 `2.1.60 - 26.09.0` |
| `2.1.60` - `26.9.3` | ⚠️ 有时被拒 |
| `2.1.60` - `25.09` | ✅ 通过 |

被拒时页面顶部会出现 error / invalid 提示，脚本通过匹配 `(?i)(error|invalid|not allowed|must be)` 识别并换下一组候选。

## 登录态检测

不要用 UI 轮询（会打断用户输入）。用 context 自带的请求上下文做纯 HTTP 探测：

```python
r = ctx.request.get("https://ankiweb.net/shared/upload", timeout=30000)
logged_in = "/account/login" not in r.url and not re.search(r"\bLog In\b", r.text())
```

大小写敏感：页面上写的是 **Log In**（I 大写），早期脚本写成 `Log in` 导致一直判成未登录。

## 提交后的页面

保存成功后 URL 会跳到 `https://ankiweb.net/shared/info/<id>`，从中正则提取 ID 即可。若停在当前页且出现 error 字样，看 `.ankiweb/shots/*-after-save.txt`。

## 排查清单

1. `python scripts/ankiweb.py status` —— 确认配置读对了
2. 看 `dump_form` 打印的元素列表 —— 选择器是否还能选中
3. 看 `.ankiweb/shots/*.txt` —— 页面实际文案
4. 表单渲染不出 —— 提高 hydration 等待时间，或检查是否被站点判定为机器人（`--disable-blink-features=AutomationControlled` 已默认开启）
5. 文件上传后 Save 无效 —— 确认版本范围已真正写入（用 `--dry-run` 复查）
