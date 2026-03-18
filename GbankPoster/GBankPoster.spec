# GBankPoster.spec
# PyInstaller spec file — run via: build.bat

import os
from tkinterdnd2 import TkinterDnD

block_cipher = None

# tkinterdnd2 ships its own Tcl/Tk extension DLL that must be bundled
_tkdnd_path = os.path.join(os.path.dirname(TkinterDnD.__file__), "tkdnd")

a = Analysis(
    ['app.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        # Addon files bundled inside the EXE
        ('..\\Addons\\GBankExporter.toc',     'addon_files'),
        ('..\\Addons\\GBankExporterAddon.lua', 'addon_files'),
        # tkinterdnd2 native extension (drag-and-drop support)
        (_tkdnd_path, 'tkinterdnd2/tkdnd'),
        # Uncomment to bundle a custom tray icon:
        # ('icon.ico', '.'),
    ],
    hiddenimports=[
        'tkinter',
        'tkinter.ttk',
        'tkinter.filedialog',
        'tkinter.messagebox',
        'tkinter.scrolledtext',
        'tkinter.colorchooser',
        'PIL',
        'PIL.Image',
        'PIL.ImageDraw',
        'PIL.ImageFont',
        'PIL.ImageGrab',
        'PIL.ImageTk',
        'pystray',
        'pystray._win32',
        'tkinterdnd2',
        'winreg',
        'colorsys',
        'ctypes',
        'ctypes.wintypes',
        'json',
        'threading',
        'queue',
        'tempfile',
        'shutil',
        'urllib.request',
        'urllib.error',
        're',
        'io',
        'core',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'numpy', 'pandas', 'scipy',
        'PyQt5', 'PyQt6', 'PySide2', 'PySide6',
        'wx', 'gi',
        'unittest', 'pydoc', 'doctest',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='GBankPoster',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon='icon.ico',
)
