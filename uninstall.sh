#!/bin/sh
set -eu
UID_NUM="$(id -u)"
launchctl bootout "gui/$UID_NUM/local.haas.proxy" 2>/dev/null || true
launchctl bootout "gui/$UID_NUM/local.haas.speech-serve" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/local.haas.proxy.plist" \
      "$HOME/Library/LaunchAgents/local.haas.speech-serve.plist"
echo "Stopped and removed LaunchAgents."
