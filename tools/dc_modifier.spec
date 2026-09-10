# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


ROOT = Path(SPECPATH).resolve().parent
ASM6 = (
    ROOT
    / "tools"
    / "vendor"
    / "famistudio-4.5.3"
    / "Tools"
    / "asm6_fixed.exe"
)

a = Analysis(
    [str(ROOT / "tools" / "run_dc_modifier.py")],
    pathex=[str(ROOT / "src")],
    binaries=[
        (
            str(ASM6),
            "tools/vendor/famistudio-4.5.3/Tools",
        )
    ],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

# The Codex desktop PATH also contains Poppler's ICU 78 build. PyInstaller can
# mistake those version-suffixed exports for Windows' unversioned ICU shim,
# making Qt6Core fail with ERROR_PROC_NOT_FOUND. Qt uses the Windows system ICU.
excluded_binaries = {"icuuc.dll", "icudt78.dll"}
a.binaries = [
    item for item in a.binaries if Path(item[0]).name.lower() not in excluded_binaries
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="新DC篇完整修改器",
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
