# -*- coding: utf-8 -*-
"""
backend.py —— 双后端。

模式 A（web，默认）：WebView 内嵌免费网页版（豆包 / Kimi / DeepSeek）。
    · 只提供官方入口 URL，用户在内置浏览器里自行登录，cookie 由 QtWebEngine 自己的
      profile 持久化保存，插件不读取、不上传任何凭证，也不调用付费 API。
    · 提供「粘贴到网页输入框」能力：优先用 JS 原生事件写入（兼容 React/Vue 受控组件），
      失败则退回剪贴板；默认只粘贴、不发送。
    · 「抓取网页最后一条回复」为尽力而为（best effort）功能，依赖可配置选择器；抓不到时
      用户可在网页里自行复制后粘贴回输入框。

模式 B（api）：OpenAI 兼容 chat/completions 接口，SSE 流式解析，工作线程中请求，
    通过 Qt 信号把增量文本送回主线程，不阻塞 UI。

依赖说明：优先使用 Anki 自带的 requests；若不存在则用标准库 urllib，全程零第三方依赖。
"""

import json
import urllib.request
import urllib.error

from aqt.qt import QObject, QThread, pyqtSignal

# ---------------------------------------------------------------------------
# 网页注入 / 抓取脚本（在 WebView 中执行）
# ---------------------------------------------------------------------------

# 把文本写入网页输入框：textarea/input 用原生 setter + input 事件；
# contenteditable 用 execCommand('insertText') 触发受控组件的 onChange。
JS_INJECT_TEXT = """
(function(sel, text){
  try {
    var list = [];
    if (sel) { try { list = Array.prototype.slice.call(document.querySelectorAll(sel)); } catch(e) {} }
    if (!list.length) {
      var sels = ["textarea", "div[contenteditable='true']", "div[contenteditable]",
                  "[role='textbox']", "input[type='text']"];
      for (var i = 0; i < sels.length && !list.length; i++) {
        try { list = Array.prototype.slice.call(document.querySelectorAll(sels[i])); } catch(e) {}
      }
    }
    list = list.filter(function(el){
      var r = el.getBoundingClientRect();
      return r.width > 40 && r.height > 8;
    });
    if (!list.length) { return "no-input"; }
    list.sort(function(a, b){
      var ra = a.getBoundingClientRect(), rb = b.getBoundingClientRect();
      return (rb.width * rb.height) - (ra.width * ra.height);
    });
    var el = list[0];
    el.focus();
    var tag = (el.tagName || "").toLowerCase();
    if (tag === "textarea" || tag === "input") {
      var proto = (tag === "textarea") ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
      var desc = Object.getOwnPropertyDescriptor(proto, "value");
      if (desc && desc.set) { desc.set.call(el, text); }
      else { el.value = text; }
      el.dispatchEvent(new Event("input", { bubbles: true }));
      return "ok";
    } else {
      var s = window.getSelection(), r = document.createRange();
      r.selectNodeContents(el); r.collapse(false);
      s.removeAllRanges(); s.addRange(r);
      var ok = false;
      try { ok = document.execCommand("insertText", false, text); } catch(e) { ok = false; }
      if (!ok) { el.textContent = text; el.dispatchEvent(new Event("input", { bubbles: true })); }
      return "ok";
    }
  } catch (e) {
    return "error:" + ((e && e.message) ? e.message : String(e));
  }
})(%s, %s);
"""

# 尽力抓取网页上"最后一条"回复文本；选择器可在设置中配置，抓不到返回空串。
JS_SCRAPE_REPLY = """
(function(sel){
  try {
    var sels = [];
    if (sel) { sels.push(sel); }
    sels = sels.concat([
      "[data-role='assistant']", "[data-message-author='assistant']",
      ".markdown-body", "article", "main .message", "div[class*='answer']",
      "div[class*='message-content']", "div[class*='assistant']"
    ]);
    for (var i = 0; i < sels.length; i++) {
      try {
        var nl = document.querySelectorAll(sels[i]);
        if (nl && nl.length) {
          var txt = (nl[nl.length - 1].innerText || "").trim();
          if (txt) { return txt; }
        }
      } catch(e) {}
    }
    return "";
  } catch (e) { return ""; }
})(%s);
"""

# 点击发送按钮（仅在用户明确开启 auto_send 时使用；不推荐开启）
JS_CLICK_SEND = """
(function(sel){
  try {
    var list = [];
    if (sel) { try { list = Array.prototype.slice.call(document.querySelectorAll(sel)); } catch(e) {} }
    if (!list.length) {
      var sels = ["button[type='submit']", "button[aria-label*='发送']", "button[aria-label*='Send']",
                  "div[role='button'][aria-label*='发送']"];
      for (var i = 0; i < sels.length && !list.length; i++) {
        try { list = Array.prototype.slice.call(document.querySelectorAll(sels[i])); } catch(e) {}
      }
    }
    for (var j = 0; j < list.length; j++) {
      var el = list[j], r = el.getBoundingClientRect();
      if (r.width > 10 && r.height > 10 && !el.disabled) { el.click(); return "ok"; }
    }
    return "not-found";
  } catch (e) { return "error"; }
})(%s);
"""


class WebBackend(object):
    """
    模式 A：网页内嵌免费模式。
    本类只负责「生成脚本 / 管理预设」，真正的 WebView 由 ui/web_panel.py 提供，
    两者解耦，便于单独替换渲染层。
    """

    def __init__(self, cfg):
        self.cfg = cfg

    @staticmethod
    def normalize_url(url):
        """补全协议，避免用户只填域名导致加载失败。"""
        url = (url or "").strip()
        if not url:
            return ""
        if url.startswith(("http://", "https://", "file://", "about:")):
            return url
        return "https://" + url

    def inject_script(self, text, selector=""):
        return JS_INJECT_TEXT % (json.dumps(selector or ""), json.dumps(text))

    def scrape_script(self, selector=""):
        return JS_SCRAPE_REPLY % json.dumps(selector or "")

    def send_script(self, selector=""):
        return JS_CLICK_SEND % json.dumps(selector or "")


# ---------------------------------------------------------------------------
# 模式 B：OpenAI 兼容流式 API
# ---------------------------------------------------------------------------

class _StreamWorker(QThread):
    """在子线程中发起 HTTP 请求并解析 SSE，避免阻塞 Anki 主线程。"""

    chunk = pyqtSignal(str)     # 增量文本
    done = pyqtSignal(str)      # 完整文本（流式结束时也会发出）
    failed = pyqtSignal(str)    # 错误信息

    def __init__(self, endpoint, api_key, model, messages, temperature,
                 max_tokens, stream, timeout, parent=None):
        super().__init__(parent)
        self.endpoint = endpoint
        self.api_key = api_key
        self.model = model
        self.messages = messages
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.stream = stream
        self.timeout = timeout
        self._stop = False
        self._resp = None

    def stop(self):
        self._stop = True
        try:
            if self._resp is not None:
                self._resp.close()
        except Exception:
            pass

    # ---------------------------------------------------------------- 请求体
    def _payload(self):
        payload = {
            "model": self.model,
            "messages": self.messages,
            "temperature": self.temperature,
            "stream": bool(self.stream),
        }
        try:
            if int(self.max_tokens) > 0:
                payload["max_tokens"] = int(self.max_tokens)
        except Exception:
            pass
        return payload

    def _headers(self):
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.stream:
            headers["Accept"] = "text/event-stream"
        if self.api_key:
            headers["Authorization"] = "Bearer %s" % self.api_key
        return headers

    def _data(self):
        return json.dumps(self._payload(), ensure_ascii=False).encode("utf-8")

    # ---------------------------------------------------------------- SSE 解析
    @staticmethod
    def _parse_delta(obj):
        """兼容 OpenAI / DeepSeek / Moonshot 等常见的 chat.completions 返回结构。"""
        try:
            choices = obj.get("choices") or []
            if not choices:
                return ""
            first = choices[0] or {}
            delta = first.get("delta") or {}
            if isinstance(delta, dict) and delta.get("content"):
                return delta["content"]
            msg = first.get("message") or {}
            if isinstance(msg, dict) and msg.get("content"):
                return msg["content"]
            if first.get("text"):
                return first["text"]
        except Exception:
            pass
        return ""

    def _consume(self, lines_iter):
        buf = []
        for line in lines_iter:
            if self._stop:
                break
            if line is None:
                continue
            line = line.strip()
            if not line:
                continue
            if line.startswith(":"):        # SSE 心跳注释
                continue
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except Exception:
                continue
            txt = self._parse_delta(obj)
            if txt:
                buf.append(txt)
                self.chunk.emit(txt)
        return "".join(buf)

    # ---------------------------------------------------------------- 主流程
    def run(self):
        buf = ""
        try:
            data = self._data()
            headers = self._headers()

            try:
                import requests  # Anki 自带

                resp = requests.post(
                    self.endpoint, data=data, headers=headers,
                    timeout=(10, max(10, int(self.timeout))), stream=True,
                )
                self._resp = resp
                if resp.status_code >= 400:
                    try:
                        detail = resp.text[:400]
                    except Exception:
                        detail = ""
                    self.failed.emit("HTTP %s：%s" % (resp.status_code, detail))
                    self.done.emit("")
                    return
                if self.stream:
                    buf = self._consume(resp.iter_lines(decode_unicode=True))
                else:
                    obj = resp.json()
                    buf = self._parse_delta(obj) or ""
                    if buf:
                        self.chunk.emit(buf)
            except ImportError:
                # 兜底：标准库 urllib（同样支持流式读取）
                req = urllib.request.Request(self.endpoint, data=data, headers=headers,
                                             method="POST")
                with urllib.request.urlopen(req, timeout=max(10, int(self.timeout))) as resp:
                    self._resp = resp
                    if self.stream:
                        def _gen():
                            for raw in resp:
                                yield raw.decode("utf-8", "replace")
                        buf = self._consume(_gen())
                    else:
                        obj = json.loads(resp.read().decode("utf-8", "replace"))
                        buf = self._parse_delta(obj) or ""
                        if buf:
                            self.chunk.emit(buf)
            except Exception as e:
                # requests 存在但请求过程出错
                self.failed.emit(str(e))
                self.done.emit("")
                return

            self.done.emit(buf)
        except Exception as e:
            msg = str(e)
            if isinstance(e, urllib.error.HTTPError):
                try:
                    msg = "HTTP %s：%s" % (e.code, e.read().decode("utf-8", "replace")[:300])
                except Exception:
                    msg = "HTTP %s" % e.code
            self.failed.emit(msg)
            self.done.emit(buf)


class ApiBackend(QObject):
    """模式 B：OpenAI 兼容接口（同步/流式），对上层只暴露 Qt 信号。"""

    started = pyqtSignal()
    chunkReceived = pyqtSignal(str)
    finished = pyqtSignal(str)
    errorOccurred = pyqtSignal(str)

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._worker = None

    def is_busy(self):
        return self._worker is not None and self._worker.isRunning()

    def send(self, messages):
        """发起一次对话；返回是否成功启动。"""
        if self.is_busy():
            self.errorOccurred.emit("上一次请求仍在进行中")
            return False

        api = self.cfg.get("api", {}) or {}
        endpoint = (api.get("endpoint") or "").strip()
        if not endpoint:
            self.errorOccurred.emit("未配置 API 地址（设置 → API 模式）")
            return False
        if not (api.get("model") or "").strip():
            self.errorOccurred.emit("未配置模型名称（设置 → API 模式）")
            return False

        worker = _StreamWorker(
            endpoint=endpoint,
            api_key=(api.get("api_key") or "").strip(),
            model=(api.get("model") or "").strip(),
            messages=messages,
            temperature=float(api.get("temperature", 0.3) or 0.3),
            max_tokens=int(api.get("max_tokens", 2048) or 0),
            stream=bool(api.get("stream", True)),
            timeout=int(api.get("timeout", 120) or 120),
            parent=self,
        )
        worker.chunk.connect(self.chunkReceived)
        worker.failed.connect(self.errorOccurred)
        worker.done.connect(self._on_done)
        worker.finished.connect(self._cleanup)  # QThread.finished：线程结束，回收对象

        self._worker = worker
        self.started.emit()
        worker.start()
        return True

    def cancel(self):
        if self._worker is not None:
            self._worker.stop()

    def _on_done(self, text):
        self.finished.emit(text or "")

    def _cleanup(self):
        try:
            if self._worker is not None:
                self._worker.deleteLater()
        except Exception:
            pass
        self._worker = None
