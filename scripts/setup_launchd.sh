#!/bin/bash
# Setup launchd auto-start for macOS
# Usage: ./scripts/setup_launchd.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

mkdir -p "$LAUNCH_AGENTS_DIR"

for plist in com.tradingengine.scheduler com.tradingengine.dashboard; do
    src="$SCRIPT_DIR/$plist.plist"
    dst="$LAUNCH_AGENTS_DIR/$plist.plist"

    if [ -f "$dst" ]; then
        launchctl unload "$dst" 2>/dev/null || true
    fi

    sed "s|__HOME__|$HOME|g" "$src" > "$dst"
    launchctl load "$dst"
    echo "Loaded: $plist"
done

echo ""
echo "Done. Both services will auto-start on boot and restart on crash."
echo "Manual commands:"
echo "  launchctl stop com.tradingengine.scheduler"
echo "  launchctl start com.tradingengine.scheduler"
echo "  launchctl unload ~/Library/LaunchAgents/com.tradingengine.scheduler.plist"
