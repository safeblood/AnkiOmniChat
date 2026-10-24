# -*- coding: utf-8 -*-
"""
latex.py —— 复用 Anki 自带的 MathJax 渲染 $...$ / $$...$$ 公式。

思路：Anki 自带的 web 资源里包含 MathJax。我们在插件数据目录里生成消息页面时，把找到的
MathJax 文件（MathJax3 的合并发行版）复制一份到本地 web 目录，用相对路径 <script> 引入，
既离线可用又不依赖 CDN，也不需要任何第三方库。

找不到本地 MathJax 时的降级顺序：
    1) 本地 MathJax（首选）
    2) CDN（联网时可用）
    3) 原样显示 TeX 源码（等宽字体 + 提示），保证插件绝不因此崩溃
"""

import os
import shutil

_CACHE = {"checked": False, "path": None, "version": None}

# MathJax 3 的"单文件合并发行版"，复制一个文件即可工作
MJ3_NAMES = ("tex-mml-chtml.js", "tex-chtml.js", "tex-svg.js", "tex-mml-svg.js",
             "chtml.js", "svg.js")
CDN_URL = "https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js"

MAX_WALK_DEPTH = 5


def _aqt_dir():
    try:
        import aqt
        return os.path.dirname(os.path.abspath(aqt.__file__))
    except Exception:
        return None


def find_mathjax():
    """返回 (本地绝对路径 or None, 版本号 "3" or None)。结果会被缓存。"""
    if _CACHE["checked"]:
        return _CACHE["path"], _CACHE["version"]
    _CACHE["checked"] = True

    base = _aqt_dir()
    if not base:
        return None, None
    data_root = os.path.join(base, "data")
    if not os.path.isdir(data_root):
        return None, None

    fallback = None
    for root, dirs, files in os.walk(data_root):
        depth = root[len(data_root):].count(os.sep)
        if depth > MAX_WALK_DEPTH:
            dirs[:] = []
            continue
        for name in files:
            low = name.lower()
            if not low.endswith(".js"):
                continue
            if name in MJ3_NAMES:
                _CACHE["path"] = os.path.join(root, name)
                _CACHE["version"] = "3"
                return _CACHE["path"], "3"
            # 老版本 MathJax 2（MathJax.js）：需要额外配置文件，仅作兜底记录
            if low == "mathjax.js" and fallback is None:
                fallback = os.path.join(root, name)
        # 目录名含 mathjax 时，优先看目录内是否有合并发行版
        if "mathjax" in os.path.basename(root).lower():
            for name in files:
                if name in MJ3_NAMES:
                    _CACHE["path"] = os.path.join(root, name)
                    _CACHE["version"] = "3"
                    return _CACHE["path"], "3"

    _CACHE["path"] = fallback
    _CACHE["version"] = "2" if fallback else None
    return _CACHE["path"], _CACHE["version"]


def prepare_mathjax(web_dir):
    """
    把可用的 MathJax 放到 web_dir/mathjax.js。
    返回 (是否本地可用, script_src)。script_src 可能是相对路径或 CDN URL。
    """
    try:
        os.makedirs(web_dir, exist_ok=True)
    except Exception:
        return False, CDN_URL

    dst = os.path.join(web_dir, "mathjax.js")
    src, version = find_mathjax()

    if src and version == "3":
        try:
            need_copy = True
            if os.path.exists(dst):
                need_copy = os.path.getsize(dst) != os.path.getsize(src)
            if need_copy:
                shutil.copyfile(src, dst)
            return True, "mathjax.js"
        except Exception:
            pass

    # MathJax 2 需要整套目录，复制成本高且易缺失文件 —— 直接走 CDN
    return False, CDN_URL


def mathjax_config_script():
    """MathJax 全局配置：必须在引入 mathjax.js 之前执行。"""
    return """
<script>
window.MathJax = {
  tex: {
    inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
    displayMath: [['$$', '$$'], ['\\\\[', '\\\\]']],
    processEscapes: true
  },
  options: {
    skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'],
    ignoreHtmlClass: 'aoc-nomath'
  },
  startup: { typeset: false }
};
</script>
"""


def typeset_js():
    """触发一次排版（MathJax 3 与 2 都兼容）。"""
    return """
function aocTypeset(root){
  try {
    if (window.MathJax && window.MathJax.typesetPromise) {
      window.MathJax.typesetPromise(root ? [root] : []).catch(function(){});
    } else if (window.MathJax && window.MathJax.Hub) {
      window.MathJax.Hub.Queue(['Typeset', window.MathJax.Hub, root || document.body]);
    }
  } catch (e) {}
}
"""
