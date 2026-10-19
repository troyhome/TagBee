#!/bin/bash
# Install and update TagBee (same idea as MacBee's Tools/macbee.sh).
#
#   Tools/tagbee.sh install   build TagBee.app and put it in /Applications (then open it)
#   Tools/tagbee.sh update    get the newest version from GitHub and install it (skips if already installed)
#   Tools/tagbee.sh updater   (re)make the "Update TagBee" app in /Applications (one click = update)
#   Tools/tagbee.sh release [version]   new version number (or the given one), a .dmg, and a GitHub Release
#
# First time on a Mac (Terminal):
#   git clone https://github.com/troyhome/TagBee ~/Projects/TagBee && ~/Projects/TagBee/Tools/tagbee.sh setup
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAMP="$HOME/Library/Application Support/TagBee/installed-commit"

case "${1:-}" in
    install)
        TAGBEE_QUIET=1 "$ROOT/Install TagBee.command" </dev/null
        ;;
    update)
        cd "$ROOT"
        git pull --ff-only
        COMMIT="$(git rev-parse HEAD)"
        if [[ -d /Applications/TagBee.app && -f "$STAMP" && "$(cat "$STAMP")" == "$COMMIT" ]]; then
            echo "TagBee is already up to date."
            exit 0
        fi
        "$0" install
        mkdir -p "$(dirname "$STAMP")"
        echo "$COMMIT" > "$STAMP"
        echo "TagBee updated."
        ;;
    updater)
        # The "Update TagBee" app: runs `tagbee.sh update` and says how it went. Made per Mac (not in Git).
        SCRIPT="$(mktemp -t update-tagbee).applescript"
        cat > "$SCRIPT" <<APPLESCRIPT
-- Update TagBee: gets the newest version from GitHub and installs it.
display notification "Checking GitHub for a new version. This can take a few minutes." with title "Updating TagBee"
try
	set result to do shell script "L=\$HOME/Library/Logs/TagBee-update.log; '$ROOT/Tools/tagbee.sh' update > \"\$L\" 2>&1 || { tail -5 \"\$L\" >&2; exit 1; }; tail -1 \"\$L\""
	if result contains "already up to date" then
		display dialog "TagBee is already up to date." buttons {"OK"} default button 1 with title "Update TagBee"
	else
		display dialog "TagBee has been updated and reopened." buttons {"OK"} default button 1 with title "Update TagBee"
	end if
on error errorText
	display dialog "The update didn't work:" & return & return & errorText buttons {"OK"} default button 1 with title "Update TagBee" with icon caution
end try
APPLESCRIPT
        rm -rf "/Applications/Update TagBee.app"
        osacompile -o "/Applications/Update TagBee.app" "$SCRIPT"
        rm -f "$SCRIPT"
        echo "Made /Applications/Update TagBee.app"
        ;;
    release)
        # One step: version number, build, .dmg on the Desktop, and a GitHub Release with the .dmg attached.
        GH="$(command -v gh || ls "$HOME/.local/bin/gh" /usr/local/bin/gh /opt/homebrew/bin/gh 2>/dev/null | head -1 || true)"
        if [ ! -x "$GH" ] || ! "$GH" auth status >/dev/null 2>&1; then
            echo "First install GitHub's tool and sign in (once):  brew install gh && gh auth login" >&2
            exit 1
        fi
        cd "$ROOT"
        if [ -n "$(git status --porcelain)" ]; then
            echo "There are unsaved changes in the project. Commit them first." >&2
            exit 1
        fi
        git pull --ff-only -q
        SPEC="$ROOT/TagBee.spec"
        CURRENT="$(sed -nE 's/.*"CFBundleShortVersionString": "([^"]+)".*/\1/p' "$SPEC")"
        if git rev-parse -q --verify "refs/tags/v$CURRENT" >/dev/null; then
            NEW="${2:-$(echo "$CURRENT" | awk -F. '{ $NF = $NF + 1; print }' OFS=.)}"   # 1.0 -> 1.1
        else
            NEW="${2:-$CURRENT}"                                                       # first release
        fi
        if git rev-parse -q --verify "refs/tags/v$NEW" >/dev/null; then
            echo "Version $NEW was already released. Give a newer one: $0 release <version>" >&2
            exit 1
        fi
        sed -i '' -E "s/(\"CFBundleShortVersionString\": \")[^\"]+/\1$NEW/" "$SPEC"
        "$0" install
        APP="$ROOT/dist.nosync/TagBee.app"
        STAGE="$(mktemp -d)"
        ditto "$APP" "$STAGE/TagBee.app"
        ln -s /Applications "$STAGE/Applications"
        DMG="$HOME/Desktop/TagBee-$NEW.dmg"
        rm -f "$DMG"
        hdiutil create -quiet -volname "TagBee $NEW" -srcfolder "$STAGE" -format UDZO "$DMG"
        rm -rf "$STAGE"
        git diff --quiet "$SPEC" || git commit -qm "TagBee $NEW" "$SPEC"
        git tag "v$NEW"
        git push -q origin main "v$NEW"
        "$GH" release create "v$NEW" "$DMG" --title "TagBee $NEW" --generate-notes
        mkdir -p "$(dirname "$STAMP")"; git rev-parse HEAD > "$STAMP"
        echo "Released TagBee $NEW."
        ;;
    setup)
        "$0" update
        "$0" updater
        ;;
    *)
        echo "Usage: $0 install|update|updater|release|setup" >&2
        exit 1
        ;;
esac
