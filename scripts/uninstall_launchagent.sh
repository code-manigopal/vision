#!/bin/bash
DEST="$HOME/Library/LaunchAgents/ai.vision.plist"
launchctl bootout "gui/$(id -u)" "$DEST" 2>/dev/null || true
rm -f "$DEST"
echo "VISION auto-start removed."
