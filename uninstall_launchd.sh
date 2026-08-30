#!/bin/bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_DEST="$HOME/Library/LaunchAgents/com.webmail.scraper.plist"

echo "Unloading job"
launchctl unload "$PLIST_DEST" 2>/dev/null || true

echo "Removing plist: $PLIST_DEST"
rm -f "$PLIST_DEST"

echo "Uninstalled. The process may still be running; check Activity Monitor or use ps to find any leftover python app.py instances and terminate them."
