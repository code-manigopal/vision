#!/bin/bash
# Starts VISION at login and restarts it if it ever crashes (each restart = boot roll call).
set -e
cd "$(dirname "$0")/.."
HOME_DIR="$(pwd)"
DEST="$HOME/Library/LaunchAgents/ai.vision.plist"
mkdir -p "$HOME/Library/LaunchAgents" logs
sed "s#__VISION_HOME__#${HOME_DIR}#g" launchd/ai.vision.plist > "$DEST"
launchctl bootout "gui/$(id -u)" "$DEST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$DEST"
echo "VISION auto-start installed. Dashboard: http://127.0.0.1:8765"
echo "Stop:     launchctl bootout gui/$(id -u) $DEST"
echo "Restart:  launchctl kickstart -k gui/$(id -u)/ai.vision"
