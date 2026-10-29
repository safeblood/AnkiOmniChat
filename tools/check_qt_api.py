# -*- coding: utf-8 -*-
"""
check_qt_api.py —— Anki 插件的 Qt5/Qt6 API 静态校验器。

干什么的
--------
PyQt6 把大量枚举从"类/命名空间上直接挂"改成了"作用域枚举"：

    Qt5:  QComboBox.AdjustToContents      Qt.Key_Return      QAbstractItemView.SelectRows
    Qt6:  QComboBox.SizeAdjustPolicy.*    Qt.Key.*           QAbstractItemView.SelectionBehavior.*

老代码直接写 Qt5 那种，在 Qt6 的 Anki 上运行时抛 AttributeError —— 而且往往炸在
构造 UI 的地方，用户看到的就是"插件加载失败"，很难猜到根因。

本脚本扫描插件源码里所有形如 `SomeQtClass.attr` 的属性访问，逐个到真实 PyQt6 上
核实该属性是否存在；不存在时还会试着在常见的"作用域包皮"里找回正确的写法。

用法
----
    python check_qt_api.py <插件目录>
"""
import ast
import os
import sys

# Qt6 里各枚举常见的"作用域"包皮名（按 PySide6/PyQt6 的惯例整理）
SCOPE_NAMES = [
    "KeyboardModifier", "Modifier", "MouseButton", "Orientation", "FocusPolicy",
    "ContextMenuPolicy", "ItemDataRole", "AlignmentFlag", "Alignment", "Key",
    "TextInteractionFlag", "TextFormat", "ShortcutContext", "ToolButtonStyle",
    "SizeAdjustPolicy", "EchoMode", "ResizeMode", "SelectionBehavior", "SelectionMode",
    "EditTrigger", "MoveOperation", "StandardButton", "DockWidgetArea",
    "DockWidgetFeature", "Type", "WebAction", "NavigationType", "PersistentCookiesPolicy",
    "ScrollBarPolicy", "Shape", "Shadow", "WrapMode", "CursorMoveStyle", "LineWrapMode",
    "TabPosition", "ElideMode", "CheckState", "SortOrder", "CaseSensitivity",
    "ToolBarArea", "WindowType", "WindowState", "ArrowType", "BrushStyle", "PenStyle",
    "SizeMode", "LayoutDirection", "InputMethodHint", "DayOfWeek", "TimeSpec",
    "CursorShape", "TransformationMode", "ImageConversionFlag", "AspectRatioMode",
    "SliderAction", "ItemFlags", "DropAction", "ScrollHint", "Formats", "Constraint",
]


def qt_module_classes():
    """把 PyQt6 里所有 Q 开头的类收集成 {类名: 类对象}。"""
    classes = {}
    try:
        from PyQt6 import QtCore, QtGui, QtWidgets
    except Exception as exc:  # pragma: no cover
        print("无法导入 PyQt6：%s" % exc)
        sys.exit(2)
    for mod in (QtCore, QtGui, QtWidgets):
        for name in dir(mod):
            if name.startswith("Q") and name[1:2].isupper():
                classes[name] = getattr(mod, name)
    classes["Qt"] = QtCore.Qt
    return classes


def _pick_protected_lines(tree):
    """qt_compat 里 `_pick(lambda: QLineEdit.Password, ...)` 这种双写是刻意的。

    第一个 lambda 取 Qt5 写法、失败就退到第二个取 Qt6 写法，所以那些 Qt5 属性
    访问不该被当成"缺失"。这里把所有属于 _pick 实参的表达式行号收集起来跳过。
    """
    lines = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "_pick"):
            continue
        for arg in node.args:
            for sub in ast.walk(arg):
                if isinstance(sub, ast.Attribute):
                    lines.add(sub.lineno)
    return lines


def find_accesses(tree, known_classes, skip_lines=()):
    """产出 [(行号, 类名, 属性名)] —— 只关心 Qt 类上的属性访问。"""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute) or node.lineno in skip_lines:
            continue
        value = node.value
        if isinstance(value, ast.Name) and value.id in known_classes:
            out.append((node.lineno, value.id, node.attr))
        # Qt.Key.Key_Return 这类二级访问也算，一并交给下面的核实逻辑
        elif isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name) \
                and value.value.id in known_classes:
            out.append((node.lineno, "%s.%s" % (value.value.id, value.attr), node.attr))
    return out


def resolve(host, names):
    """顺着 a.b.c 逐级取属性；任一级不存在返回 (False, 已取到的层级)。"""
    current = host
    for name in names:
        if not hasattr(current, name):
            return False, current
        current = getattr(current, name)
    return True, current


def suggest(cls_obj, attr):
    """属性不在类上时，去常见作用域枚举里找回它该怎么写。"""
    for scope in SCOPE_NAMES:
        enum = getattr(cls_obj, scope, None)
        if enum is not None and hasattr(enum, attr):
            return "%s.%s.%s" % (cls_obj.__name__, scope, attr)
    # Qt.Key 这种：Qt6 挂到子枚举下，值形式统一
    base = getattr(cls_obj, attr.title().replace(" ", ""), None)
    if base is not None:
        return "%s.%s" % (cls_obj.__name__, attr.title())
    return None


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    known = qt_module_classes()
    problems, checked = [], 0
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for fn in filenames:
            if fn.endswith(".py"):
                files.append(os.path.join(dirpath, fn))

    for path in sorted(files):
        with open(path, "r", encoding="utf-8") as fh:
            source = fh.read()
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError as exc:
            problems.append((path, exc.lineno or 0, "语法错误", str(exc)))
            continue
        # 兼容层里 _pick 双写的 Qt5 常量属于刻意写法，跳过
        skip = _pick_protected_lines(tree) if os.path.basename(path) == "qt_compat.py" else set()
        for lineno, cls_expr, attr in find_accesses(tree, known, skip):
            if attr.startswith("_") or cls_expr.startswith("self"):
                continue
            checked += 1
            parts = cls_expr.split(".")
            ok, _ = resolve(known[parts[0]], parts[1:] + [attr])
            if not ok:
                host_labels = []
                for p in parts[:-1]:
                    host_labels.append("")
                host, _ = resolve(known[parts[0]], parts[1:])
                fix = suggest(host, attr) if host is not None else None
                problems.append((
                    os.path.relpath(path, root), lineno,
                    "%s.%s 在 PyQt6 上不存在" % (cls_expr, attr),
                    ("应写成 %s" % fix) if fix else "未找到对应写法，需人工确认",
                ))

    print("扫描 %d 个文件，核对 %d 处 Qt 属性访问。" % (len(files), checked))
    if not problems:
        print("全部通过，没有 Qt6 上的属性缺失。")
        return 0
    print("\n发现 %d 个问题：" % len(problems))
    for path, lineno, headline, detail in problems:
        print("  %s:%d  %s\n      -> %s" % (path, lineno, headline, detail))
    return 1


if __name__ == "__main__":
    sys.exit(main())
