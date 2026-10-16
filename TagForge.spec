# PyInstaller spec - builds TagForge.app. Used by build_app.command.
import os

exts = ["flac", "m4a", "m4b", "mp4", "mp3", "ogg", "opus", "wav", "aif", "aiff"]
icon = "icon.icns" if os.path.exists("icon.icns") else None

a = Analysis(["tagforge.py"], pathex=["."], datas=[("icon.png", ".")], excludes=["tkinter", "unittest", "pydoc"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="TagForge", console=False,
          argv_emulation=False)
coll = COLLECT(exe, a.binaries, a.datas, name="TagForge")
app = BUNDLE(
    coll, name="TagForge.app", icon=icon, bundle_identifier="local.tagforge.app",
    info_plist={
        "CFBundleName": "TagForge",
        "CFBundleDisplayName": "TagForge",
        "CFBundleShortVersionString": "1.0",
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
