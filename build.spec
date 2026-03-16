# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for WeChat PC Agent — portable one-folder build.

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        # WeChat automation + decryption (lazy-loaded, PyInstaller won't auto-detect)
        'wxauto',
        'wdecipher',
        'pyautogui',
        # Networking
        'websockets',
        'websockets.legacy',
        'websockets.legacy.client',
        'httpx',
        'httpx._transports',
        'httpx._transports.default',
        # Data validation
        'pydantic',
        'pydantic.json_schema',
        'pydantic._internal',
        # PyQt6 (usually auto-detected, but be safe)
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Not used — keep the bundle small
        'tkinter',
        'matplotlib',
        'numpy',
        'scipy',
        'PIL',
        'cv2',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,  # one-folder mode (COLLECT handles binaries)
    name='WeChat-Agent',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,                           # windowed GUI app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    manifest='resources/app.manifest',       # UAC admin elevation
    # icon='resources/app.ico',              # Uncomment when icon is available
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='WeChat-Agent',
)
