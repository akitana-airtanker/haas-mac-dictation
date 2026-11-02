#!/bin/sh
set -eu

SPEECH_BIN="${SPEECH_BIN:-$HOME/.local/bin/speech}"
INSTALL_DIR="$HOME/.local/share/haas-dictation"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

if [ ! -x "$SPEECH_BIN" ]; then
  echo "Installing speech.cpp..."
  curl -fsSL https://raw.githubusercontent.com/nyosegawa/speech.cpp/main/install.sh | sh
fi

"$SPEECH_BIN" pull haas-ja-v1.0
"$SPEECH_BIN" pull silero-vad

mkdir -p "$INSTALL_DIR" "$LAUNCH_AGENTS"
cp "$SCRIPT_DIR/proxy.py" "$INSTALL_DIR/proxy.py"
chmod +x "$INSTALL_DIR/proxy.py"
if [ ! -f "$INSTALL_DIR/keywords.txt" ]; then
  cp "$SCRIPT_DIR/keywords.txt" "$INSTALL_DIR/keywords.txt"
fi

cat > "$LAUNCH_AGENTS/local.haas.speech-serve.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>local.haas.speech-serve</string>
  <key>ProgramArguments</key><array>
    <string>$SPEECH_BIN</string><string>serve</string>
    <string>haas-ja-v1.0</string><string>silero-vad</string>
    <string>--host</string><string>127.0.0.1</string><string>--port</string><string>8080</string>
  </array>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>StandardErrorPath</key><string>$INSTALL_DIR/serve.log</string>
  <key>StandardOutPath</key><string>$INSTALL_DIR/serve.log</string>
</dict></plist>
PLIST

cat > "$LAUNCH_AGENTS/local.haas.proxy.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>local.haas.proxy</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/python3</string><string>$INSTALL_DIR/proxy.py</string>
  </array>
  <key>RunAtLoad</key><true/><key>KeepAlive</key><true/>
  <key>StandardErrorPath</key><string>$INSTALL_DIR/proxy.log</string>
  <key>StandardOutPath</key><string>$INSTALL_DIR/proxy.log</string>
</dict></plist>
PLIST

UID_NUM="$(id -u)"
launchctl bootout "gui/$UID_NUM/local.haas.speech-serve" 2>/dev/null || true
launchctl bootout "gui/$UID_NUM/local.haas.proxy" 2>/dev/null || true
launchctl bootstrap "gui/$UID_NUM" "$LAUNCH_AGENTS/local.haas.speech-serve.plist"
launchctl bootstrap "gui/$UID_NUM" "$LAUNCH_AGENTS/local.haas.proxy.plist"

echo "Done. Endpoint for OpenWhispr (Self-hosted): http://127.0.0.1:8081/v1 (model: Haas-ja-v1.0)"
