# -*- mode: python ; coding: utf-8 -*-

with open("VERSION") as _f:
    _version = _f.read().strip()

a = Analysis(
    ["src/streammanager/main.py"],
    pathex=["src"],
    binaries=[],
    datas=[
        ("assets/icon.png", "assets"),
    ],
    hiddenimports=[
        "google.auth.transport.requests",
        "google_auth_oauthlib.flow",
        "googleapiclient.discovery",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="StreamManager",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/icon.icns",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="StreamManager",
)

app = BUNDLE(
    coll,
    name="StreamManager.app",
    icon="assets/icon.icns",
    bundle_identifier="com.streammanager.app",
    version=_version,
)
