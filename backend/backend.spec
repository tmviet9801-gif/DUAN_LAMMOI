# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

hiddenimports = (
    collect_submodules("patchright")
    + collect_submodules("uvicorn")
    + collect_submodules("fastapi")
    + collect_submodules("pycaw")
    + collect_submodules("comtypes")
)

datas = (
    collect_data_files("patchright")
    + collect_data_files("uvicorn")
    + collect_data_files("fastapi")
    + collect_data_files("comtypes")
    + [("extension", "extension")]  # Chrome extension WS bridge (nhúng vào profile)
)

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "IPython"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="tab-manager-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
)
