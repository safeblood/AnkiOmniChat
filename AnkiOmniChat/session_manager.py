# -*- coding: utf-8 -*-
"""
session_manager.py —— 会话历史的持久化与读写。

核心规则
--------
* 以「单张 Note」为文档上下文，会话 key = "note:<note_id>"；无绑定卡片时为 "free"。
* 不同卡片（不同 key）的聊天历史完全隔离。
* 所有历史以本地 JSON 文件保存（默认在当前 profile 目录下），重启 Anki 不丢失。
* 写入采用「临时文件 + os.replace」的原子替换，异常时自动备份损坏文件，绝不因历史文件
  损坏导致插件崩溃。
"""

import json
import os
import time
import uuid

from aqt.qt import QObject, QTimer, pyqtSignal

from .config import data_dir

SESSION_FILE_VERSION = 1
SESSION_FILE_NAME = "sessions.json"

FREE_KEY = "free"


def note_key(note_id):
    """Note ID -> 会话 key（会话隔离的粒度）。"""
    return "note:%s" % note_id


def _now():
    return time.time()


def _new_session(key, title=""):
    return {
        "key": key,
        "title": title or "",
        "created": _now(),
        "updated": _now(),
        "messages": [],
    }


class SessionManager(QObject):
    """会话存储：内存 dict + 定时落盘的 JSON 文件。"""

    sessionChanged = pyqtSignal(str)  # 参数：会话 key

    def __init__(self, cfg, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self._data = {"version": SESSION_FILE_VERSION, "sessions": {}, "order": []}
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(600)
        self._timer.timeout.connect(self.flush)
        self.load()

    # ------------------------------------------------------------------ 文件
    def path(self):
        return os.path.join(data_dir(self.cfg), SESSION_FILE_NAME)

    def load(self):
        """载入历史；文件损坏则备份并新建，保证插件可用。"""
        path = self.path()
        if not os.path.exists(path):
            return self
        try:
            with open(path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if not isinstance(raw, dict) or not isinstance(raw.get("sessions"), dict):
                raise ValueError("会话文件结构不合法")
            raw.setdefault("order", [])
            raw.setdefault("version", SESSION_FILE_VERSION)
            # 清洗：剔除结构异常的会话，避免渲染时报错
            clean = {}
            for key, sess in raw["sessions"].items():
                if isinstance(sess, dict) and isinstance(sess.get("messages"), list):
                    sess["messages"] = [
                        m for m in sess["messages"]
                        if isinstance(m, dict) and "role" in m and "content" in m
                    ]
                    clean[key] = sess
            raw["sessions"] = clean
            self._data = raw
        except Exception:
            try:
                os.replace(path, path + ".corrupt.bak")
            except Exception:
                pass
            self._data = {"version": SESSION_FILE_VERSION, "sessions": {}, "order": []}
        return self

    def reload(self):
        """切换到另一个 profile 后重新读盘。

        两件事缺一不可：

        1. 先停掉待触发的写盘定时器 —— flush 的目标是「当前」路径（由 data_dir 算出），
           晚一步执行就会把上一个 profile 的会话写进别人的 sessions.json。
        2. 先把内存清干净再 load() —— load() 在目标文件不存在时会提前返回自保，
           不清的话新 profile 一上来就「继承」了旧 profile 的全部历史。
        """
        try:
            self._timer.stop()
        except Exception:
            pass
        self._data = {"version": SESSION_FILE_VERSION, "sessions": {}, "order": []}
        return self.load()

    def flush(self):
        """原子写入磁盘。"""
        path = self.path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, path)
        except Exception:
            pass

    def _schedule_flush(self):
        self._timer.start()

    # ------------------------------------------------------------------ 会话
    def get(self, key, create=True):
        key = key or FREE_KEY
        sessions = self._data["sessions"]
        if key not in sessions:
            if not create:
                return None
            sessions[key] = _new_session(key)
            if key not in self._data["order"]:
                self._data["order"].append(key)
            self._schedule_flush()
        return sessions[key]

    def keys(self):
        return list(self._data["sessions"].keys())

    def title(self, key):
        sess = self.get(key, create=False)
        return (sess or {}).get("title", "") or ""

    def set_title(self, key, title):
        sess = self.get(key)
        sess["title"] = title or ""
        sess["updated"] = _now()
        self._schedule_flush()

    def messages(self, key):
        return self.get(key).get("messages", [])

    def last_messages(self, key, limit=None):
        msgs = self.messages(key)
        if limit and limit > 0:
            return msgs[-limit:]
        return list(msgs)

    # ------------------------------------------------------------------ 消息
    def add_message(self, key, role, content, meta=None):
        """追加一条消息，返回该消息 dict（含唯一 id，供动作按钮定位）。"""
        sess = self.get(key)
        msg = {
            "id": uuid.uuid4().hex[:12],
            "role": role,               # user / assistant / system / note(上下文提示)
            "content": content or "",
            "ts": _now(),
            "meta": meta or {},
        }
        sess["messages"].append(msg)
        sess["updated"] = _now()

        # 控制单会话体积，避免 JSON 无限膨胀
        max_keep = 200
        try:
            max_keep = int(self.cfg.get("general.max_messages_per_session", 200))
        except Exception:
            pass
        if max_keep > 0 and len(sess["messages"]) > max_keep:
            sess["messages"] = sess["messages"][-max_keep:]

        self._schedule_flush()
        return msg

    def upsert_context(self, key, content, meta=None):
        """
        写入「卡片上下文」类消息（role=note）。

        与 add_message 的区别在于幂等：上下文代表"这张卡现在的内容"，重复注入同一份
        （同一张卡反复复习、按 Again 回到原题再翻答案）不该在会话里堆出一串相同的大段
        文本，否则真正有价值的问答会被 max_messages_per_session 挤出历史窗口。

        规则：上一条正好是 note 就覆盖内容与时间戳；否则追加一条。
        """
        sess = self.get(key)
        msgs = sess.setdefault("messages", [])
        if msgs and msgs[-1].get("role") == "note":
            msgs[-1]["content"] = content or ""
            msgs[-1]["ts"] = _now()
            if meta:
                msgs[-1]["meta"] = meta
            sess["updated"] = _now()
            self._schedule_flush()
            return msgs[-1]
        return self.add_message(key, "note", content, meta=meta)

    def message_by_id(self, key, msg_id):
        for m in self.messages(key):
            if m.get("id") == msg_id:
                return m
        return None

    def update_message(self, key, msg_id, content):
        m = self.message_by_id(key, msg_id)
        if m is None:
            return False
        m["content"] = content
        m["ts"] = _now()
        self._schedule_flush()
        return True

    def delete_message(self, key, msg_id):
        sess = self.get(key, create=False)
        if not sess:
            return False
        before = len(sess["messages"])
        sess["messages"] = [m for m in sess["messages"] if m.get("id") != msg_id]
        if len(sess["messages"]) != before:
            self._schedule_flush()
            return True
        return False

    def clear(self, key):
        """清空某个会话的消息，但保留会话本身（标题等）。"""
        sess = self.get(key, create=False)
        if sess:
            sess["messages"] = []
            sess["updated"] = _now()
            self._schedule_flush()
            return True
        return False

    def remove(self, key):
        self._data["sessions"].pop(key, None)
        if key in self._data["order"]:
            self._data["order"].remove(key)
        self._schedule_flush()

    def clear_all(self):
        self._data["sessions"] = {}
        self._data["order"] = []
        self.flush()

    # ------------------------------------------------------------------ 导出
    def export_markdown(self, key):
        """把会话导出为 Markdown 文本（便于复制到笔记软件）。"""
        sess = self.get(key, create=False)
        if not sess:
            return ""
        lines = ["# %s" % (sess.get("title") or key), ""]
        for m in sess["messages"]:
            who = "我" if m.get("role") == "user" else "AI"
            lines.append("**%s**（%s）" % (who, time.strftime("%Y-%m-%d %H:%M", time.localtime(m.get("ts", 0)))))
            lines.append("")
            lines.append(m.get("content", ""))
            lines.append("")
        return "\n".join(lines)
