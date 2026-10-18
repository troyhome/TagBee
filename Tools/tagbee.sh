#!/bin/bash
# Install and update TagBee (same idea as MacBee's Tools/macbee.sh).
#
#   Tools/tagbee.sh install   build TagBee.app and put it in /Applications (then open it)
#   Tools/tagbee.sh update    get the newest version from GitHub and install it (skips if already installed)
#   Tools/tagbee.sh updater   (re)make the "Update TagBee" app in /Applications (one click = update)
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
    setup)
        "$0" update
        "$0" updater
        ;;
    *)
        echo "Usage: $0 install|update|updater|setup" >&2
        exit 1
        ;;
esac
