# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_submodules
_extra_hidden = collect_submodules("scipy.signal") + ["soxr", "soxr.cysoxr"]

a = Analysis(
    ['src/voice_task_board/__main__.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('frontend/dist', 'frontend/dist'),
        ('src/voice_task_board/resources', 'resources'),
    ],
    hiddenimports=[
        'pystray._win32',
        'sounddevice',
        'pycaw',
        'pycaw.pycaw',
        'comtypes',
        'comtypes.client',
        'windows_toasts',
        'winrt.windows.ui.notifications',
        'winrt.windows.data.xml.dom',
        'winrt.windows.foundation',
        *_extra_hidden,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludedimports=[],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=None)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='VoiceTaskBoard',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='VoiceTaskBoard',
)
