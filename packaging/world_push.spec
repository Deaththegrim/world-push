# One-file build of World Push. Run from the repo root: pyinstaller packaging/world_push.spec
from pathlib import Path

root = Path(SPECPATH).parent
a = Analysis([str(root / "packaging/launcher.py")], pathex=[str(root)],
             datas=[(str(root / "world_push/assets/theme.qss"), "world_push/assets")],
             hiddenimports=["world_push.assets"],
             excludes=["PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtNetwork", "PySide6.QtOpenGL", "PySide6.QtPdf", "PySide6.QtSvg", "tkinter"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="WorldPush", console=False, upx=False)
