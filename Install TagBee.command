#!/bin/bash
# Double-click to install TagBee as a normal Mac app (Applications folder, Launchpad, Dock).
cd "$(dirname "$0")" || exit 1
SRC="$PWD"
LOG="$HOME/Library/Logs/TagBee-install.log"
mkdir -p "$(dirname "$LOG")"
exec > >(tee "$LOG") 2>&1
export PYTHONIOENCODING=utf-8
APP_SUPPORT="$HOME/Library/Application Support/TagBee"

step() { echo; echo "=== $1"; }
die() {
  echo; echo "!!! $1"
  echo "A full log was saved to: $LOG"
  echo "If you ask Claude for help, attach that file (it's selected in Finder now)."
  open -R "$LOG" 2>/dev/null
  read -p "Press Return to close"; exit 1
}

# ---- 1. Python
step "1/6  Looking for Python 3"
PY=""
for c in /opt/homebrew/bin/python3 /usr/local/bin/python3 \
         /Library/Frameworks/Python.framework/Versions/Current/bin/python3 "$(command -v python3)"; do
  [ -n "$c" ] && [ -x "$c" ] && PY="$c" && break
done
[ -n "$PY" ] || die "Python 3 wasn't found. Install it from https://www.python.org/downloads/macos/ and run this again."
echo "Using $PY ($("$PY" --version 2>&1))"

# ---- 2. private environment with the libraries
step "2/6  Preparing libraries (first time: a few minutes, ~430 MB download)"
if ! .venv.nosync/bin/python -c "import PySide6, mutagen" >/dev/null 2>&1; then
  rm -rf .venv.nosync
  "$PY" -m venv .venv.nosync \
    && .venv.nosync/bin/python -m pip install --quiet --upgrade pip \
    && .venv.nosync/bin/python -m pip install --no-compile -r requirements.txt || die "Couldn't install the libraries."
fi
.venv.nosync/bin/python -c "import sys; sys.path.insert(0,'.'); import tagio, theme, tagbee; print('App code loads fine')" \
  || die "The app code failed to load."

# ---- 3. icon
step "3/6  Making the icon"
if [ -f icon.png ] && command -v iconutil >/dev/null; then
  rm -rf icon.iconset icon.icns && mkdir icon.iconset
  for s in 16 32 128 256 512; do
    sips -z $s $s icon.png --out icon.iconset/icon_${s}x${s}.png >/dev/null
    sips -z $((s*2)) $((s*2)) icon.png --out icon.iconset/icon_${s}x${s}@2x.png >/dev/null
  done
  iconutil -c icns icon.iconset -o icon.icns && echo "icon.icns created"
  rm -rf icon.iconset
fi

# ---- 4. build the app (method A: self-contained; method B: lightweight launcher)
APP=""
build_standalone() {
  .venv.nosync/bin/python -m pip install --quiet --no-compile pyinstaller || return 1
  rm -rf build.nosync dist.nosync
  .venv.nosync/bin/python -m PyInstaller --noconfirm --clean --workpath build.nosync --distpath dist.nosync TagBee.spec || return 1
  [ -x dist.nosync/TagBee.app/Contents/MacOS/TagBee ] || return 1
  codesign --force --deep --sign - dist.nosync/TagBee.app >/dev/null 2>&1
  # smoke test: it must stay running for a few seconds
  dist.nosync/TagBee.app/Contents/MacOS/TagBee >build.nosync/smoke.log 2>&1 &
  local pid=$!; sleep 7
  if kill -0 "$pid" 2>/dev/null; then kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null; return 0; fi
  echo "The built app quit right after starting. Its output:"; cat build.nosync/smoke.log; return 1
}

build_launcher() {
  rm -rf dist.nosync/TagBee.app; mkdir -p dist.nosync/TagBee.app/Contents/MacOS dist.nosync/TagBee.app/Contents/Resources
  mkdir -p "$APP_SUPPORT"
  cp tagbee.py tagio.py theme.py requirements.txt icon.png "$APP_SUPPORT/"
  "$PY" -m venv "$APP_SUPPORT/.venv" \
    && "$APP_SUPPORT/.venv/bin/python" -m pip install --quiet --upgrade pip \
    && "$APP_SUPPORT/.venv/bin/python" -m pip install --no-compile -r "$APP_SUPPORT/requirements.txt" || return 1
  [ -f icon.icns ] && cp icon.icns dist.nosync/TagBee.app/Contents/Resources/icon.icns
  cat > dist.nosync/TagBee.app/Contents/MacOS/TagBee <<'LAUNCH'
#!/bin/bash
S="$HOME/Library/Application Support/TagBee"
exec "$S/.venv/bin/python" "$S/tagbee.py" "$@"
LAUNCH
  chmod +x dist.nosync/TagBee.app/Contents/MacOS/TagBee
  cat > dist.nosync/TagBee.app/Contents/Info.plist <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
 <key>CFBundleName</key><string>TagBee</string>
 <key>CFBundleDisplayName</key><string>TagBee</string>
 <key>CFBundleIdentifier</key><string>local.tagbee.launcher</string>
 <key>CFBundleExecutable</key><string>TagBee</string>
 <key>CFBundleIconFile</key><string>icon</string>
 <key>CFBundlePackageType</key><string>APPL</string>
 <key>CFBundleShortVersionString</key><string>1.0</string>
 <key>NSHighResolutionCapable</key><true/>
 <key>CFBundleDocumentTypes</key><array><dict>
   <key>CFBundleTypeName</key><string>Audio file</string>
   <key>CFBundleTypeRole</key><string>Editor</string>
   <key>LSHandlerRank</key><string>Alternate</string>
   <key>CFBundleTypeExtensions</key><array>
     <string>flac</string><string>m4a</string><string>m4b</string><string>mp4</string><string>mp3</string>
     <string>ogg</string><string>opus</string><string>wav</string><string>aif</string><string>aiff</string>
   </array></dict></array>
</dict></plist>
PLIST
  [ -x dist.nosync/TagBee.app/Contents/MacOS/TagBee ]
}

step "4/6  Building TagBee.app (a few minutes)"
mkdir -p build.nosync
if build_standalone; then
  APP="dist.nosync/TagBee.app"; echo "Built the self-contained app."
else
  echo; echo "Self-contained build didn't work - switching to the lightweight app instead."
  build_launcher || die "Couldn't build the app either way."
  APP="dist.nosync/TagBee.app"; echo "Built the lightweight app."
fi

# ---- 5. install
step "5/6  Installing"
INSTALLED=""
for DEST in /Applications "$HOME/Applications"; do
  mkdir -p "$DEST" 2>/dev/null
  if [ -w "$DEST" ]; then
    rm -rf "$DEST/TagBee.app"
    if ditto "$APP" "$DEST/TagBee.app" 2>/dev/null && [ -x "$DEST/TagBee.app/Contents/MacOS/TagBee" ]; then
      xattr -cr "$DEST/TagBee.app" 2>/dev/null
      INSTALLED="$DEST/TagBee.app"; break
    fi
  fi
done
[ -n "$INSTALLED" ] || die "Couldn't copy the app into Applications."

# The app used to be called TagForge: move the old copy to the Trash (recoverable) so only TagBee remains.
for OLD in /Applications/TagForge.app "$HOME/Applications/TagForge.app"; do
  if [ -d "$OLD" ]; then
    osascript -e 'quit app "TagForge"' >/dev/null 2>&1
    mv "$OLD" "$HOME/.Trash/TagForge $(date '+%Y-%m-%d %H.%M.%S').app" && echo "Moved the old TagForge app to the Trash."
  fi
done

# ---- 6. finish
step "6/6  Done"
echo "TagBee is installed at: $INSTALLED"
echo "Open it from Launchpad, Spotlight (type TagBee), or the Applications folder."
echo "Tip: once it's open, right-click its Dock icon > Options > Keep in Dock."
open -R "$INSTALLED"
sleep 1
open "$INSTALLED"
echo
read -p "Press Return to close this window"
