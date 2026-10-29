# -*- coding: utf-8 -*-
"""
qt_compat.py —— Qt5（PyQt5）/ Qt6（PyQt6）统一适配层。

为什么需要它
------------
Anki 2.1.60 ~ 2.1.65 用 PyQt5，2.1.66 及更新版本（含 23.10 / 24.x / 25.x / 26.x）用 PyQt6。
两者的关键差异：

    * PyQt5 的枚举是"非作用域"的：`Qt.RightDockWidgetArea`、`QEvent.Close`
    * PyQt6 的枚举是"作用域"的：`Qt.DockWidgetArea.RightDockWidgetArea`、`QEvent.Type.Close`

直接写 `Qt.RightDockWidgetArea` 在 PyQt6 上会抛 AttributeError。
本模块用"多候选取值"的方式把常用枚举解析成常量，业务代码只引用常量，
从而在 Qt5 / Qt6 上行为一致，且不需要散落各处的 try/except。

另外把 QtWebEngine 的导入与几个易变的 WebEngine 枚举也集中到这里。
"""

from aqt.qt import (
    QAbstractItemView, QDialogButtonBox, QDockWidget, QEvent, QHeaderView, QLineEdit,
    QMessageBox, Qt, QTextCursor,
)


def _pick(*getters):
    """按顺序尝试取值，返回第一个可用结果；全部失败返回 None。"""
    for getter in getters:
        try:
            value = getter()
            if value is not None:
                return value
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# Qt 命名空间下的常用枚举
# ---------------------------------------------------------------------------
KEY_RETURN = _pick(lambda: Qt.Key_Return, lambda: Qt.Key.Key_Return)
KEY_ENTER = _pick(lambda: Qt.Key_Enter, lambda: Qt.Key.Key_Enter)
CTRL_MOD = _pick(lambda: Qt.ControlModifier, lambda: Qt.KeyboardModifier.ControlModifier)
SHIFT_MOD = _pick(lambda: Qt.ShiftModifier, lambda: Qt.KeyboardModifier.ShiftModifier)

RIGHT_DOCK = _pick(lambda: Qt.RightDockWidgetArea,
                   lambda: Qt.DockWidgetArea.RightDockWidgetArea)
LEFT_DOCK = _pick(lambda: Qt.LeftDockWidgetArea,
                  lambda: Qt.DockWidgetArea.LeftDockWidgetArea)

HORIZONTAL = _pick(lambda: Qt.Horizontal, lambda: Qt.Orientation.Horizontal)
VERTICAL = _pick(lambda: Qt.Vertical, lambda: Qt.Orientation.Vertical)

TEXT_SELECTABLE = _pick(lambda: Qt.TextSelectableByMouse,
                        lambda: Qt.TextInteractionFlag.TextSelectableByMouse)

# QComboBox/QTableWidget 的按项 tooltip：Qt6 里同样搬进了 ItemDataRole
USER_ROLE = _pick(lambda: Qt.UserRole, lambda: Qt.ItemDataRole.UserRole)
TOOLTIP_ROLE = _pick(lambda: Qt.ToolTipRole, lambda: Qt.ItemDataRole.ToolTipRole)

# QLabel.setTextFormat 用：强制纯文本，防止卡片名里的 < > & 被当成 HTML 解析
PLAIN_TEXT = _pick(lambda: Qt.PlainText, lambda: Qt.TextFormat.PlainText)

APP_SHORTCUT = _pick(lambda: Qt.ApplicationShortcut,
                     lambda: Qt.ShortcutContext.ApplicationShortcut)
WIDGET_CHILDREN_SHORTCUT = _pick(lambda: Qt.WidgetWithChildrenShortcut,
                                 lambda: Qt.ShortcutContext.WidgetWithChildrenShortcut)

# ---------------------------------------------------------------------------
# 各控件自身的枚举
# ---------------------------------------------------------------------------
DOCK_CLOSABLE = _pick(lambda: QDockWidget.DockWidgetClosable,
                      lambda: QDockWidget.DockWidgetFeature.DockWidgetClosable)
DOCK_MOVABLE = _pick(lambda: QDockWidget.DockWidgetMovable,
                     lambda: QDockWidget.DockWidgetFeature.DockWidgetMovable)
DOCK_FLOATABLE = _pick(lambda: QDockWidget.DockWidgetFloatable,
                       lambda: QDockWidget.DockWidgetFeature.DockWidgetFloatable)

LINEEDIT_PASSWORD = _pick(lambda: QLineEdit.Password,
                          lambda: QLineEdit.EchoMode.Password)

HEADER_STRETCH = _pick(lambda: QHeaderView.Stretch,
                       lambda: QHeaderView.ResizeMode.Stretch)

# QTableWidget / QTableView 的选择与编辑行为
SELECT_ROWS = _pick(lambda: QAbstractItemView.SelectRows,
                    lambda: QAbstractItemView.SelectionBehavior.SelectRows)
SINGLE_SELECTION = _pick(lambda: QAbstractItemView.SingleSelection,
                         lambda: QAbstractItemView.SelectionMode.SingleSelection)
NO_EDIT_TRIGGERS = _pick(lambda: QAbstractItemView.NoEditTriggers,
                         lambda: QAbstractItemView.EditTrigger.NoEditTriggers)

TEXTCURSOR_END = _pick(lambda: QTextCursor.End,
                       lambda: QTextCursor.MoveOperation.End)

MSGBOX_YES = _pick(lambda: QMessageBox.Yes,
                   lambda: QMessageBox.StandardButton.Yes)
MSGBOX_NO = _pick(lambda: QMessageBox.No,
                  lambda: QMessageBox.StandardButton.No)

EVENT_CLOSE = _pick(lambda: QEvent.Close, lambda: QEvent.Type.Close)


def _std_button(name):
    """QDialogButtonBox 标准按钮：Qt5 用 Xxx.Ok，Qt6 用 Xxx.StandardButton.Ok。"""
    val = getattr(QDialogButtonBox, name, None)
    if val is None:
        enum = getattr(QDialogButtonBox, "StandardButton", None)
        if enum is not None:
            val = getattr(enum, name, None)
    return val


# ---------------------------------------------------------------------------
# QtWebEngine：模块导入（PyQt5 / PyQt6 路径不同，且不同 Anki 版本 aqt.qt 导出不一致）
# ---------------------------------------------------------------------------
def _import_webengine():
    """返回 (QWebEngineView, QWebEnginePage, QWebEngineProfile, QWebEngineSettings)。"""
    candidates = (
        lambda: __import__("aqt.qt", fromlist=["*"]),
    )
    for _ in candidates:
        try:
            from aqt.qt import (  # noqa: F401
                QWebEnginePage, QWebEngineProfile, QWebEngineSettings, QWebEngineView,
            )
            return QWebEngineView, QWebEnginePage, QWebEngineProfile, QWebEngineSettings
        except Exception:
            pass
    for mod in ("PyQt5.QtWebEngineWidgets", "PyQt6.QtWebEngineWidgets"):
        try:
            m = __import__(mod, fromlist=["*"])
            return (m.QWebEngineView, m.QWebEnginePage,
                    m.QWebEngineProfile, m.QWebEngineSettings)
        except Exception:
            continue
    # 极端情况：Qt6 把 Profile/Settings 放在 QtWebEngineCore
    try:
        w = __import__("PyQt6.QtWebEngineWidgets", fromlist=["*"])
        c = __import__("PyQt6.QtWebEngineCore", fromlist=["*"])
        return w.QWebEngineView, w.QWebEnginePage, c.QWebEngineProfile, c.QWebEngineSettings
    except Exception:
        return None, None, None, None


QWebEngineView, QWebEnginePage, QWebEngineProfile, QWebEngineSettings = _import_webengine()


def web_engine_available():
    return QWebEngineView is not None


def set_web_attr(settings, name, value=True):
    """设置 WebEngine 属性，兼容 Qt5 / Qt6 的枚举位置差异。"""
    if settings is None:
        return False
    attr = getattr(QWebEngineSettings, name, None) if QWebEngineSettings else None
    if attr is None and QWebEngineSettings is not None:
        enum = getattr(QWebEngineSettings, "WebAttribute", None)
        if enum is not None:
            attr = getattr(enum, name, None)
    if attr is None:
        return False
    try:
        settings.setAttribute(attr, value)
        return True
    except Exception:
        return False


def nav_type_link_clicked():
    """QWebEnginePage 的"链接点击"导航类型。"""
    if QWebEnginePage is None:
        return None
    value = getattr(QWebEnginePage, "NavigationTypeLinkClicked", None)
    if value is None:
        enum = getattr(QWebEnginePage, "NavigationType", None)
        if enum is not None:
            value = getattr(enum, "LinkClicked", None)
    return value


def persistent_cookie_policy():
    """允许持久 cookie 的策略枚举。"""
    if QWebEngineProfile is None:
        return None
    value = getattr(QWebEngineProfile, "AllowPersistentCookies", None)
    if value is None:
        enum = getattr(QWebEngineProfile, "PersistentCookiesPolicy", None)
        if enum is not None:
            value = getattr(enum, "AllowPersistentCookies", None)
    return value


CUSTOM_CONTEXT_MENU = _pick(lambda: Qt.CustomContextMenu,
                            lambda: Qt.ContextMenuPolicy.CustomContextMenu)


def web_action(name):
    """QWebEnginePage 的动作枚举：Qt5 用 Page.Copy，Qt6 用 Page.WebAction.Copy。"""
    if QWebEnginePage is None:
        return None
    value = getattr(QWebEnginePage, name, None)
    if value is None:
        enum = getattr(QWebEnginePage, "WebAction", None)
        if enum is not None:
            value = getattr(enum, name, None)
    return value
