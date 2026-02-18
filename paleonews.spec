# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['/home/jikhanjung/projects/paleonews/entry.py'],
    pathex=['/home/jikhanjung/projects/paleonews'],
    binaries=[],
    datas=[],
    hiddenimports=['paleonews.config', 'paleonews.db', 'paleonews.fetcher', 'paleonews.filter', 'paleonews.summarizer', 'paleonews.dispatcher.telegram', 'paleonews.dispatcher.base'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='paleonews',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
