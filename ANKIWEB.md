![AnkiOmniChat](https://cdn.jsdelivr.net/gh/safeblood/AnkiOmniChat@master/docs/logo.png)

![AnkiOmniChat demo: review a card, the panel auto-loads it, one click asks the AI](https://cdn.jsdelivr.net/gh/safeblood/AnkiOmniChat@master/docs/demo.gif)

**[Demo GIF (full size)](https://cdn.jsdelivr.net/gh/safeblood/AnkiOmniChat@master/docs/demo.gif)** — flip to the answer, the side panel auto-switches to that card's session and injects every field, then one click asks the AI.

In-Anki AI chat side panel, inspired by Obsidian OmniChat.

**New in 1.1.5**

- **Prompt presets**: 8 built-in ways to ask about the same card — default Q&A, explain the underlying principle, examples & analogies, contrast with confusable concepts, quiz me, critique my card, mnemonics, English-to-English definitions. Switch with the panel drop-down or **Ctrl+Alt+P**; add, edit, copy and reorder your own in Settings. A custom prefix/suffix from before 1.1.5 is kept automatically as "My prompt".
- **Right-click to grab from the web page**: select text in the embedded chat page (or use the last AI reply) and append it to a card field as **Markdown** or as rich HTML. Code blocks, lists, tables, headings, quotes, links and inline marks survive the trip.
- **Field writes no longer eat your text**: Anki fields are HTML, so things like `<stdio.h>` or `a<b` used to silently disappear. Choose source Markdown (default), rendered HTML, or raw HTML in Settings.
- **Fixes**: writing to a field during review no longer skips the current card; switching profiles no longer mixes up chat histories; repeated reviews of one card no longer pile up duplicate context; **Qt6 (Anki 23.10+ / 25.x / 26.x) loading failure fixed**.

**Features**

- Dockable/collapsible side panel in both the Reviewer and Browse windows
- Per-note context: session key = Note ID, chat history isolated per card
- One-click injection of all card fields (hotkey or on flip)
- **Mode A (default, free)**: embedded WebView of Doubao / Kimi / DeepSeek web apps; log in once and cookies persist locally; text is pasted into the web input box but **never auto-sent**
- **Mode B**: OpenAI-compatible `/v1/chat/completions` with SSE streaming
- Markdown + Anki's bundled MathJax rendering (`$...$`, `$$...$$`)
- Action buttons under each AI reply: append to field / overwrite field / copy
- Sessions saved as local JSON (atomic write), survive restarts

Zero third-party pip dependencies. Works on Anki 2.1.60-2.1.66 (Qt5) and 23.10+/25.x/26.x (Qt6); PyQt5/PyQt6 differences handled by a compat layer.

Source / screenshots / install from GitHub: [github.com/safeblood/AnkiOmniChat](https://github.com/safeblood/AnkiOmniChat#0-%E6%BC%94%E7%A4%BA)
