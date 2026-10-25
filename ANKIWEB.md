![AnkiOmniChat](https://cdn.jsdelivr.net/gh/safeblood/AnkiOmniChat@master/docs/logo.png)

![AnkiOmniChat demo: review a card, the panel auto-loads it, one click asks the AI](https://cdn.jsdelivr.net/gh/safeblood/AnkiOmniChat@master/docs/demo.gif)

**[Demo GIF (full size)](https://cdn.jsdelivr.net/gh/safeblood/AnkiOmniChat@master/docs/demo.gif)** — flip to the answer, the side panel auto-switches to that card's session and injects every field, then one click asks the AI.

In-Anki AI chat side panel, inspired by Obsidian OmniChat.

- Dockable/collapsible side panel in both the Reviewer and Browse windows
- Per-note context: session key = Note ID, chat history isolated per card
- One-click injection of all card fields (hotkey or on flip)
- **Mode A (default, free)**: embedded WebView of Doubao / Kimi / DeepSeek web apps; log in once and cookies persist locally; text is pasted into the web input box but **never auto-sent**
- **Mode B**: OpenAI-compatible `/v1/chat/completions` with SSE streaming
- Markdown + Anki's bundled MathJax rendering (`$...$`, `$$...$$`)
- Action buttons under each AI reply: append to field / overwrite field / copy
- Sessions saved as local JSON (atomic write), survive restarts

Zero third-party pip dependencies. Works on Anki 2.1.60-2.1.66 (Qt5) and 25.x/26.x (Qt6); PyQt5/PyQt6 differences handled by a compat layer.

Source / screenshots / install from GitHub: [github.com/safeblood/AnkiOmniChat](https://github.com/safeblood/AnkiOmniChat#0-%E6%BC%94%E7%A4%BA)
