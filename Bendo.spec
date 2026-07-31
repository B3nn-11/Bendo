# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['bendo.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # superseded by the modular winrt-* packages (same API); its single
        # _winrt.pyd is ~38 MB unpacked / ~11 MB in the exe
        'winsdk',
        # PIL pieces Bendo never touches: AVIF codec (~4 MB), text/font
        # rendering (~1 MB; the drawpad only draws lines), color management
        'PIL._avif', 'PIL.AvifImagePlugin',
        'PIL.ImageFont', 'PIL._imagingft', 'PIL.ImageQt', 'PIL._imagingcms',
        # stdlib bulk nothing imports at runtime
        'unittest', 'pydoc', 'doctest', 'xmlrpc', 'lib2to3',
        'ensurepip', 'venv', 'tkinter.test',
    ],
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
    name='Bendo',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # UPX-packed exes trip antivirus/SmartScreen heuristics far more often;
    # the size saving isn't worth it for a distributed build.
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
    icon=['Bendo.ico'],
    version='Bendo_version_info.txt',
)
