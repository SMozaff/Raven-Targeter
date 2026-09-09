# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Raven-Targeter on macOS (one-file + .app bundle).

Build ON macOS (PyInstaller cannot cross-compile):
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -e ".[dev,packaging]"
    pyinstaller packaging/macos.spec
Output:
    dist/Raven-Targeter.app
"""

import os

# Run PyInstaller from the repository root; paths resolve against CWD.
ROOT = os.path.abspath(os.getcwd())

block_cipher = None


a = Analysis(
    [os.path.join(ROOT, "app.py")],
    pathex=[os.path.join(ROOT, "src")],
    binaries=[],
    datas=[],
    hiddenimports=[
        "raven_targeter",
        "raven_targeter.adapters",
        "raven_targeter.adapters.base",
        "raven_targeter.adapters.github",
        "raven_targeter.adapters.github_gists",
        "raven_targeter.config",
        "raven_targeter.config.aliases",
        "raven_targeter.config.settings",
        "raven_targeter.config.targets",
        "raven_targeter.core",
        "raven_targeter.core.date_validator",
        "raven_targeter.core.deduplicator",
        "raven_targeter.core.query_builder",
        "raven_targeter.core.sanitizer",
        "raven_targeter.core.scorer",
        "raven_targeter.database",
        "raven_targeter.database.database",
        "raven_targeter.database.models",
        "raven_targeter.database.repository",
        "raven_targeter.gui",
        "raven_targeter.gui.dashboard",
        "raven_targeter.gui.main_window",
        "raven_targeter.gui.result_detail",
        "raven_targeter.gui.results_page",
        "raven_targeter.gui.search_page",
        "raven_targeter.gui.settings_page",
        "raven_targeter.models",
        "raven_targeter.services",
        "raven_targeter.services.export_service",
        "raven_targeter.services.search_service",
        "raven_targeter.utils",
        "raven_targeter.utils.dates",
        "raven_targeter.utils.logging",
        "raven_targeter.utils.urls",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Raven-Targeter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Raven-Targeter",
)

app = BUNDLE(
    coll,
    name="Raven-Targeter.app",
    bundle_identifier="com.raventargeter.app",
)
