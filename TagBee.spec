# PyInstaller spec - builds TagBee.app. Used by build_app.command.
import os

exts = ["flac", "m4a", "m4b", "mp4", "mp3", "ogg", "opus", "wav", "aif", "aiff"]
icon = "icon.icns" if os.path.exists("icon.icns") else None

a = Analysis(["tagbee.py"], pathex=["."], datas=[("icon.png", "."), ("icons", "icons")], excludes=["tkinter", "unittest", "pydoc"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="TagBee", console=False,
          argv_emulation=False)
coll = COLLECT(exe, a.binaries, a.datas, name="TagBee")
app = BUNDLE(
    coll, name="TagBee.app", icon=icon, bundle_identifier="local.tagbee.app",
    info_plist={
        "CFBundleName": "TagBee",
        "CFBundleDisplayName": "TagBee",
        "CFBundleShortVersionString": "1.1",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "11.0",
        "CFBundleDocumentTypes": [{
            "CFBundleTypeName": "Audio file",
            "CFBundleTypeRole": "Editor",
            "LSHandlerRank": "Alternate",       # offered under 'Open With', doesn't steal defaults
            "CFBundleTypeExtensions": exts,
        }],
    },
)
