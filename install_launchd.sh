#!/bin/bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
PLIST_SRC="$DIR/com.webmail.scraper.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/com.webmail.scraper.plist"

echo "Installing launchd plist to $PLIST_DEST"
mkdir -p "$HOME/Library/LaunchAgents"
cp "$PLIST_SRC" "$PLIST_DEST"
chmod 644 "$PLIST_DEST"

echo "Unloading existing job (if any)"
launchctl unload "$PLIST_DEST" 2>/dev/null || true

echo "Loading job into launchd"
launchctl load "$PLIST_DEST"

echo "Done. Logs will appear in: $DIR/logs"
echo "If you need to set credentials, create a file named .env in $DIR with lines like:"
echo "WEBMAIL_USER=jaipur.dcit.int"
echo "WEBMAIL_PWD=Arvind#2026"
echo "WEBMAIL_ADMIN_PWD=your_admin_password"
