# -*- mode: python ; coding: utf-8 -*-
# Bendo Lite: the five core tools (Internet Blocker, Shutdown Scheduler,
# Volume Mixer, Notes, Power) in a smaller portable exe. The runtime hook
# sets BENDO_LITE=1 so bendo.py hides the optional tabs, and the extra
# excludes compile out the libraries only those tabs used - which also
# drops the system tray (pystray needs Pillow) and the speed test.
# Build: python -m PyInstaller Bendo-Lite.spec


a = Analysis(
    ['bendo.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['lite_runtime_hook.py'],
    excludes=[
        # everything the regular build excludes...
        'winsdk',
        'PIL._avif', 'PIL.AvifImagePlugin',
        'PIL.ImageFont', 'PIL._imagingft', 'PIL.ImageQt', 'PIL._imagingcms',
        'unittest', 'pydoc', 'doctest', 'xmlrpc', 'lib2to3',
        'ensurepip', 'venv', 'tkinter.test',
        # ...plus the optional-tool libraries Lite compiles out entirely
        'PIL',        # drawpad/photo/converter/background images
        'pystray',    # system tray (requires PIL anyway)
        'winrt',      # media controller
        'speedtest',  # speed test
        'psutil',     # system stats
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
    name='Bendo-Lite',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
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
    version='Bendo_Lite_version_info.txt',
)
