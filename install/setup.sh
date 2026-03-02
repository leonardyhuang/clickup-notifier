#!/bin/bash
# ─── ClickUp Desktop Notifier — Setup Script ─────────────────────────────────
# One-command installer for macOS.
# Usage: bash install/setup.sh   (from the project root)
#
# What it does:
#   1. Asks for your ClickUp API token
#   2. Asks how often to check (15 / 30 / 60 / 120 min)
#   3. Asks what to notify about (tasks / chat / both)
#   4. Installs terminal-notifier via Homebrew (click-to-open support)
#   5. Copies the Python script to ~/Scripts/
#   6. Creates a launchd agent with your chosen settings
#   7. Starts the agent immediately

set -e

SCRIPT_DIR="$HOME/Scripts"
LOG_DIR="$SCRIPT_DIR/logs"
PLIST_NAME="com.clickup-notifier.plist"
PLIST_DEST="$HOME/Library/LaunchAgents/$PLIST_NAME"
SCRIPT_SRC="$(cd "$(dirname "$0")/.." && pwd)/clickup_notifier.py"
SCRIPT_DEST="$SCRIPT_DIR/clickup_notifier.py"
ACTUAL_USER=$(whoami)

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║       ClickUp Desktop Notifier — Setup          ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── Step 1: API Token ─────────────────────────────────────────────────────────
if [ -z "$CLICKUP_API_TOKEN" ]; then
    echo "Step 1: ClickUp API Token"
    echo "  To get your token:"
    echo "    1. Open ClickUp and click your avatar (bottom-left)"
    echo "    2. Go to Settings → Apps"
    echo "    3. Under 'API Token', click Generate (or copy your existing token)"
    echo "    4. The token starts with pk_"
    echo ""
    echo "  → https://app.clickup.com/settings/apps"
    echo ""
    read -r -p "  Paste your API token: " CLICKUP_API_TOKEN
    echo ""
fi

if [ -z "$CLICKUP_API_TOKEN" ]; then
    echo "✗ No API token provided. Aborting."
    exit 1
fi

echo "  ✓ API token set"
echo ""

# ── Step 2: Check interval ────────────────────────────────────────────────────
echo "Step 2: Check interval"
echo "  How often should the notifier check for new mentions and assignments?"
echo ""
echo "    1) Every 15 minutes"
echo "    2) Every 30 minutes  (recommended)"
echo "    3) Every 60 minutes"
echo "    4) Every 2 hours"
echo ""
read -r -p "  Enter choice [1-4, default 2]: " INTERVAL_CHOICE
echo ""

case "$INTERVAL_CHOICE" in
    1) START_INTERVAL=900;  INTERVAL_LABEL="15 minutes" ;;
    3) START_INTERVAL=3600; INTERVAL_LABEL="60 minutes" ;;
    4) START_INTERVAL=7200; INTERVAL_LABEL="2 hours"    ;;
    *) START_INTERVAL=1800; INTERVAL_LABEL="30 minutes" ;;
esac
echo "  ✓ Interval: $INTERVAL_LABEL"
echo ""

# ── Step 3: Notification scope ────────────────────────────────────────────────
echo "Step 3: Notification scope"
echo "  What do you want to be notified about?"
echo ""
echo "    1) Task @mentions and new assignments only"
echo "    2) Chat @mentions only"
echo "    3) Both task mentions/assignments AND chat  (recommended)"
echo ""
read -r -p "  Enter choice [1-3, default 3]: " SCOPE_CHOICE
echo ""

case "$SCOPE_CHOICE" in
    1) NOTIFY_TASKS=true;  NOTIFY_CHAT=false; SCOPE_LABEL="Task mentions & assignments only" ;;
    2) NOTIFY_TASKS=false; NOTIFY_CHAT=true;  SCOPE_LABEL="Chat mentions only"               ;;
    *) NOTIFY_TASKS=true;  NOTIFY_CHAT=true;  SCOPE_LABEL="Task + Chat"                      ;;
esac
echo "  ✓ Scope: $SCOPE_LABEL"
echo ""

# ── Step 4: terminal-notifier ─────────────────────────────────────────────────
echo "Step 4: terminal-notifier (click-to-open support)"
if [ -f "/opt/homebrew/bin/terminal-notifier" ] || [ -f "/usr/local/bin/terminal-notifier" ]; then
    echo "  ✓ Already installed"
elif command -v brew &>/dev/null; then
    echo "  → Installing via Homebrew..."
    brew install terminal-notifier
    echo "  ✓ Installed"
else
    echo "  ⚠ Homebrew not found. Notifications will still work"
    echo "    but clicking them won't open ClickUp."
    echo "    Fix later: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    echo "               brew install terminal-notifier"
fi
echo ""

# ── Step 5: Install script ────────────────────────────────────────────────────
echo "Step 5: Installing notifier script"
mkdir -p "$SCRIPT_DIR" "$LOG_DIR"
cp "$SCRIPT_SRC" "$SCRIPT_DEST"
chmod +x "$SCRIPT_DEST"
echo "  ✓ Script → $SCRIPT_DEST"
echo "  ✓ Logs   → $LOG_DIR/"
echo ""

# ── Step 6: Create launchd plist ──────────────────────────────────────────────
echo "Step 6: Configuring launchd agent"
cat > "$PLIST_DEST" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.clickup-notifier</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>CLICKUP_API_TOKEN</key>
        <string>${CLICKUP_API_TOKEN}</string>
        <key>NOTIFY_TASKS</key>
        <string>${NOTIFY_TASKS}</string>
        <key>NOTIFY_CHAT</key>
        <string>${NOTIFY_CHAT}</string>
    </dict>

    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/Users/${ACTUAL_USER}/Scripts/clickup_notifier.py</string>
    </array>

    <!-- Run every ${START_INTERVAL} seconds (${INTERVAL_LABEL}) -->
    <key>StartInterval</key>
    <integer>${START_INTERVAL}</integer>

    <key>StandardOutPath</key>
    <string>/Users/${ACTUAL_USER}/Scripts/logs/notifier.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/${ACTUAL_USER}/Scripts/logs/notifier_error.log</string>

    <!-- Run immediately on load -->
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
PLIST
echo "  ✓ Agent  → $PLIST_DEST"
echo ""

# ── Step 7: Start agent ───────────────────────────────────────────────────────
echo "Step 7: Starting agent"
if launchctl list 2>/dev/null | grep -q "com.clickup-notifier"; then
    echo "  → Restarting existing agent..."
    launchctl unload "$PLIST_DEST" 2>/dev/null || true
fi
launchctl load "$PLIST_DEST"
echo "  ✓ Running"
echo ""

# ── Done ──────────────────────────────────────────────────────────────────────
echo "╔══════════════════════════════════════════════════╗"
echo "║   All done! Here's what happens next:           ║"
echo "╠══════════════════════════════════════════════════╣"
echo "║  • First check runs right now                   ║"
echo "║  • Repeats every $INTERVAL_LABEL while your Mac is awake"
echo "║  • Scope: $SCOPE_LABEL"
echo "║  • Click a notification to open the task/chat   ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""
echo "Logs:    tail -f ~/Scripts/logs/notifier.log"
echo "Stop:    launchctl unload ~/Library/LaunchAgents/$PLIST_NAME"
echo "Restart: launchctl unload ~/Library/LaunchAgents/$PLIST_NAME && launchctl load ~/Library/LaunchAgents/$PLIST_NAME"
echo ""
