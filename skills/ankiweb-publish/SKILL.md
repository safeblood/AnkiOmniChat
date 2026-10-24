---
name: ankiweb-publish
display_name: AnkiWeb 插件发布
display_name_en: AnkiWeb Add-on Publisher
description: "把写好的 Anki 插件打包并发布到 AnkiWeb 官方插件站，已发布的插件也能一键推送更新包。当用户要求「发布插件」「上传 AnkiWeb」「更新插件版本」「推新版 .ankiaddon」，或需要把本地 addons21 里的插件打包成 .ankiaddon 时使用。"
description_zh: "Anki 插件写好了要给别人用？这条流水线把打包、登录、填表、传包、设版本范围、校验全打通：一条命令打出合规 .ankiaddon，首次登录后登录态长期复用，配置文件 publish.json 统一管理所有参数。AnkiWeb 那些暗坑——动态 SPA 表单、版本框没有 type 属性、必须点 Update 链接才渲染分支区——都已在脚本里处理。"
description_en: "Publish an Anki add-on to AnkiWeb and push updates later, end to end: pack a spec-compliant .ankiaddon, reuse a persistent login profile, fill Title/Tags/Support/Description, upload the file, set the branch version range, and verify. All the known traps are pre-solved: dynamic Svelte form, version inputs without a type attribute, and the fact that the edit page only renders its branch section when reached via the Update link."
category: development
author: WorkBuddy
version: 1.0.0
examples:
  - "帮我把这个 Anki 插件发布到 AnkiWeb"
  - "插件改完了，推个新版到 AnkiWeb"
  - "把 addons21 里的插件目录打包成 ankiaddon"
  - "AnkiWeb 上的版本范围填错了，改一下"
---

# AnkiWeb 插件发布 · ankiweb-publish

一条命令完成「打包 → 登录 → 填表 → 传包 → 设兼容版本 → 发布」。踩过的坑都写在脚本里了，照流程走基本一次成功。

## 前置条件

- Python 3.8+，`pip install playwright && playwright install chromium`（只有涉及浏览器的子命令需要）
- 一个 AnkiWeb 账号（没有就在浏览器里点 Sign Up 注册）
- 插件目录里必须有 `meta.json`

## 快速流程

### 1. 写配置

在项目根目录放 `publish.json`（参考同目录 `publish.example.json`）：

```json
{
  "addon_dir": "AnkiOmniChat",
  "zip": "AnkiOmniChat.ankiaddon",
  "profile": ".ankiweb_profile",
  "work_dir": ".ankiweb",
  "addon_id": "1939948095",
  "title": "AnkiOmniChat: AI Chat Side Panel (OmniChat style)",
  "tags": "ai chat llm assistant study",
  "support": "https://github.com/safeblood/AnkiOmniChat/issues",
  "description_file": "ANKIWEB.md",
  "min_version": "2.1.60",
  "max_version": "26.09"
}
```

`addon_id` 首次发布时留空，跑完 `new` 会把拿到的 ID 写进 `.ankiweb/result.json`，再回填到 `publish.json` 和插件 `meta.json` 的 `ankiweb_id` 字段，之后就能走 `update` 了。

### 2. 打包

```bash
python scripts/ankiweb.py pack
```

会剔除 `__pycache__/`、`user_files/`、`.git/` 等不该进包的目录，校验 zip 根目录没多套一层文件夹，并顺手跑一遍 `compileall`。**包结构错误是 AnkiWeb 拒收最常见的原因。**

### 3. 登录（只需一次）

```bash
python scripts/ankiweb.py login
```

浏览器打开后你手动登录，脚本用 HTTP 方式检测登录态，**不会刷新或跳转你正在操作的页面**。登录 cookie 存在 `profile` 目录，长期复用。

### 4. 发布 / 更新

```bash
python scripts/ankiweb.py new --dry-run   # 先填好不提交，确认无误
python scripts/ankiweb.py new             # 正式发布

python scripts/ankiweb.py update          # 改完代码推新版（保持标题和版本范围）
python scripts/ankiweb.py verify          # 只读校验当前线上状态
python scripts/ankiweb.py fix-versions    # 版本范围填错或被拒时单独修
```

## 关键命令

| 命令 | 作用 | 备注 |
|---|---|---|
| `pack` | 打包 `.ankiaddon` | 零第三方依赖，标准库即可 |
| `login` | 建立持久登录态 | `--wait-login` 调整等待秒数，默认 900 |
| `new` | 首次发布 | 必填 title/tags/support/description |
| `update` | 推更新包 | 需要 `addon_id` |
| `fix-versions` | 修版本范围 | 会依次尝试候选写法直到通过 |
| `verify` | 只读检查 | 输出版本范围与公开页摘要 |
| `status` | 看配置与上次结果 | 排障先看这个 |

所有子命令都支持 `--dry-run`（填表但不提交）和 `--config` 指定别的配置文件。

## 已知坑（脚本已处理，改动脚本时别踩回去）

1. **别用 UI 轮询测登录**。早期版本每隔几秒把同一个标签页导航到上传页，用户填到一半的登录表单被冲掉。现在改用 `context.request` 做 HTTP 探测，完全不碰 DOM。
2. **版本输入框没有 `type` 属性**。`input[type=text]` 选不中它们；而且 value 由 Svelte 托管，直接赋值不生效。必须取 `HTMLInputElement.prototype` 的原生 setter 再派发 `input` / `change` 事件。
3. **编辑页必须点进去**。直接 `goto /shared/upload?id=<id>` 不会渲染 Branches 区，得先开 info 页再点页面上的 **Update** 链接。
4. **版本号格式挑剔**。`2.1.60` / `26.09` 能通过，`26.9.3` 这类写法有时会被拒。`fix-versions` 内置多组候选依次尝试。
5. **zip 根目录不能多套一层**。必须直接是 `meta.json`、`*.py`，不能是 `AnkiOmniChat/meta.json`。
6. **SPA 要等 hydration**。表单可能晚于 `domcontentloaded` 才出现，等待与超时重试的时间要留够（脚本默认 `wait_for_selector` 25 秒，失败再兜 4 秒）。

详细表单字段与排查手法见 `references/form-structure.md`。

## 产出物

- `<配置 zip>`：可直接交给用户安装的包
- `.ankiweb/shots/*.png|txt`：每一步的截图与页面文本，出错先看这里
- `.ankiweb/result.json`：上次结果（含 add-on ID、版本范围前后对比）
- `.ankiweb/state.json`：打包记录

## 安全

- 账号密码只在用户自己的浏览器里输入，脚本从不接触
- 登录态 cookie 落在本地 `profile` 目录，建议加进 `.gitignore`
- 发布前务必确认包里没有 API Key、cookie、个人笔记等敏感数据
