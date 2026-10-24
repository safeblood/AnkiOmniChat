# Reddit / 官方论坛发帖稿

> 按 r/Anki 2026-02 新规撰写：作者身份声明、pricing + license 标注、AI 参与披露都已内置。
> 发帖前替换 `[链接]` 占位符。**不要删掉披露段落**——这是 Rule 6 的硬性要求。

---

## 版本 A：r/Anki（英文主帖）

**Title（二选一，建议第一个）**
```
I built a side-panel AI chat for Anki that reads the card you're reviewing — no API key needed
```
```
AnkiOmniChat: ask questions about the card you're stuck on, without leaving the reviewer (free, MIT)
```

**Body**

```
I kept hitting the same wall while reviewing: I'd get a card I half-understood, want to ask
one clarifying question, and that meant alt-tabbing to a browser, copying the card text over,
losing my place, then coming back.

So I made a side panel that already knows which card you're on.

[SCREENSHOT / GIF — see GIF_SCRIPT.md]

**What it does**

- Dockable side panel in both the Reviewer and the Browse window
- One hotkey injects all fields of the current card as context (or auto-injects on flip)
- Chat history is keyed to the Note ID — switch cards, and you get that card's own
  conversation back. Different cards never bleed into each other.
- **Mode A (default, free)**: an embedded WebView of Doubao / Kimi / DeepSeek. You log in
  once in the panel, cookies persist locally, and the card text is pasted into the web input
  box — **it never auto-sends**. You stay in control of what goes out.
- Mode B: any OpenAI-compatible endpoint with SSE streaming, typewriter-style output
- Markdown + Anki's bundled MathJax, so `$...$` and `$$...$$` render
- Under each reply: append to field / overwrite field / copy

**Cost / license**

Free, no account, no paywall, no telemetry. MIT licensed. Mode A uses the free web tiers of
the providers you already have. Mode B needs your own API key and you pay your provider
directly — I never see it.

**Disclosure**

I'm the author. Development was substantially AI-assisted (I used AI coding tools to write
most of the code); I use it daily for my own reviews and I read and test everything, but I
want to be upfront about it rather than have you find out later.

**Links**

AnkiWeb: [链接]   (add-on ID `1939948095`, or search "AnkiOmniChat" in Get Add-ons)
Source: https://github.com/safeblood/AnkiOmniChat

Works on Anki 2.1.60–26.09 (Qt5 and Qt6). Zero third-party pip dependencies.

Happy to answer anything about how it works or how the per-note sessions are stored.
If this isn't a fit for the sub, mods feel free to remove — I'll repost in r/AnkiAI.
```

---

## 版本 B：r/AnkiAI（英文，语气可更随意）

**Title**
```
Built an Anki add-on that gives every card its own AI chat history — free web mode, no API key
```

**Body**

Shorter is fine here. Keep: the opening pain point, the GIF, the feature bullets, then:

```
Free / MIT. Mode A = embedded Doubao / Kimi / DeepSeek web apps (no API key, never auto-sends);
Mode B = OpenAI-compatible streaming with your own key.

Disclosure: I'm the author, and this was largely AI-assisted to build.

AnkiWeb ID 1939948095 · https://github.com/safeblood/AnkiOmniChat
```

---

## 版本 C：forums.ankiweb.net（Add-ons 板块）

官方论坛鼓励作者开帖做支持，这篇是**长期维护帖**，语气更平实、技术细节更多。

**Title**
```
AnkiOmniChat — per-note AI chat side panel (Reviewer + Browse)
```

**Body**

```
Hi all,

I'd like to share an add-on I've been using daily for a while, and I'll use this thread for
support and updates.

**The problem.** Reviewing a card I only half understand, I wanted to ask one question. That
meant leaving Anki, re-typing the card, and losing my place.

**What it does.** A dockable side panel that treats one Note as the document. Session key is
the Note ID, so each card keeps its own chat history and switching cards switches conversations.
A hotkey (or auto-inject on flip) pushes all fields of the current card in as context.

Two backends:
- Web mode (default): embedded WebView of Doubao / Kimi / DeepSeek. Log in once, cookies
  persist locally. Card text is written into the web input box but **never auto-sent**.
- API mode: OpenAI-compatible `/v1/chat/completions`, SSE streaming, stoppable.

Replies render Markdown and use Anki's bundled MathJax for `$...$` / `$$...$$`.
Each AI reply has append-to-field / overwrite-field / copy buttons.

**Compatibility.** Anki 2.1.60 through 26.09. Qt5/PyQt5 and Qt6/PyQt6 are both handled via a
compat layer (verified on Anki 26.9.3 + PyQt6 + Python 3.13). No third-party pip dependencies.

**Cost / license.** Free and MIT licensed.

**Disclosure.** I'm the author. The code was written with substantial AI assistance;
I test everything myself but want to be transparent about it.

AnkiWeb: [链接] (ID 1939948095)
Source: https://github.com/safeblood/AnkiOmniChat

Feedback and bug reports very welcome — I'll keep this thread updated.
```

---

## 版本 D：中文圈（B站简介 / 知乎 / 公众号开头）

```
复习时遇到一张卡，答案看不懂，想多问一句——
以前：切出去开网页 → 手动复制卡片内容 → 问完再切回来，复习节奏全断了。

做了个 Anki 插件：右侧常驻一个 AI 对话面板，它知道你当前在看哪张卡。

· 一键把当前卡片所有字段丢进去当上下文（快捷键，或翻卡自动注入）
· 每张卡有独立的对话历史，切卡片自动切换，互不串味
· 默认走网页模式：内嵌豆包 / Kimi / DeepSeek，登录一次就行，不用 API Key，
  文本只写进输入框，不会自动发送
· 也支持 OpenAI 兼容接口，流式逐字输出
· 回答支持 Markdown 和公式；一键把答案追加或覆盖回卡片字段

免费，MIT 开源，零第三方依赖，Anki 2.1.60 到 26.09 都能用。
（说明：这个插件是我在 AI 辅助下写的，我自己每天都在用。）

AnkiWeb 插件 ID：1939948095
源码：https://github.com/safeblood/AnkiOmniChat
```

---

## 发帖检查清单

- [ ] 所有 `[链接]` 已替换
- [ ] **AI 参与披露段落保留**（Rule 6，删了可能被判为隐瞒）
- [ ] 明确写了 free + MIT（Rule 3 要求 pricing 和 license）
- [ ] 明确写了「我是作者」
- [ ] GIF / 截图已上传（不是外链到需要登录的网盘）
- [ ] 同一内容不在多个 subreddit 同日群发（会被判 spam）
- [ ] 发完 24 小时内回来回评论——前几小时的互动决定帖子能不能上热门
