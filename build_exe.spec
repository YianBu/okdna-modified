# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.getcwd()
sys.path.insert(0, os.path.join(ROOT, "vendor"))

datas = []
binaries = []
hiddenimports = []

# 需要连同数据/子模块一起收进来的第三方库
for pkg in ["ok", "onnxocr", "pyappify", "openvino", "qfluentwidgets", "pynput", "pycaw", "comtypes"]:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as e:
        print("collect_all failed:", pkg, e)

# pywin32 / 系统库
hiddenimports += [
    "win32api", "win32con", "win32gui", "win32process", "win32event", "win32timezone",
    "win32com", "win32com.client", "pythoncom", "pywintypes",
    "comtypes.stream", "comtypes.client",
]

# 显式列出 src 下所有模块（命名空间包 + 任务类靠字符串动态加载）
src_mods = []
for root, dirs, files in os.walk(os.path.join(ROOT, "src")):
    dirs[:] = [d for d in dirs if d != "__pycache__"]
    for f in files:
        if f.endswith(".py"):
            rel = os.path.relpath(os.path.join(root, f), ROOT)
            mod = rel[:-3].replace(os.sep, ".")
            if mod.endswith(".__init__"):
                mod = mod[: -len(".__init__")]
            src_mods.append(mod)
hiddenimports += src_mods
print("SRC_MODULES:", len(src_mods), src_mods[:5], "...")

# 运行期数据
datas += [
    ("assets", "assets"),
    ("icons", "icons"),
    ("i18n", "i18n"),
    ("mod", "mod"),
]

a = Analysis(
    ["main.py"],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tensorflow", "scipy", "pandas", "sklearn", "matplotlib", "IPython", "notebook"],
    noarchive=False,
)

# 打包机的 PATH 里若混进了工具链自带的原生依赖（例如本机 Codex 运行时的 libheif / poppler），
# PyInstaller 会顺着 PATH 把它们当成依赖收进来。这些 DLL（icudt78/icuuc、libcrypto-3-x64、
# api-ms-win-*、ucrtbase …）会和 Qt / 系统的同名库打架 —— 实测 Qt6Core 直接加载失败
# （ImportError: DLL load failed while importing QtCore: 找不到指定的程序）。
# 这里把来源在工具链目录里的二进制统一剔掉，只保留 Python 环境自己的依赖。
LEAK_MARKERS = ("codex-runtimes",)


def _not_leaked(entry):
    source = str(entry[1])
    return not any(marker in source for marker in LEAK_MARKERS)


_dropped = [str(e[0]) for e in a.binaries if not _not_leaked(e)]
a.binaries = [e for e in a.binaries if _not_leaked(e)]
a.datas = [e for e in a.datas if _not_leaked(e)]
print("DROPPED_LEAKED_BINARIES:", len(_dropped), sorted(_dropped))

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="ok-dna-mod",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="ok-dna-mod",
)
