# -*- coding: utf-8 -*-
"""
ui 包 —— 界面层。

    markdown.py   极简 Markdown 渲染器（零第三方依赖，支持流式增量重绘）
    latex.py      定位 Anki 自带的 MathJax 资源，用于渲染 $...$ 公式
    chat_page.py  生成消息区的 HTML/CSS/JS 页面（OmniChat 风格布局）
    chat_view.py  QWebEngineView 封装：渲染会话、流式追加、动作按钮事件回调
    web_panel.py  模式 A 的网页视图（独立持久化 profile，复用网页 cookie）
    panel.py      侧边面板主体：标题栏 / 模式切换 / 输入区 / 状态栏
    actions.py    AI 消息动作：追加到卡片字段 / 覆盖卡片字段 / 复制
    settings.py   设置对话框
"""
