# ClickUp Desktop Notifier

A macOS background service that periodically checks ClickUp and sends native desktop notifications for:

- **@mentions** in task comments (repeats until you reply or the task is closed)
- **@mentions** in space chat channels (repeats until you reply in that channel)
- **New task assignments** (notifies once)

Clicking a notification opens the task or chat channel directly in your browser.

---

## Requirements

| Requirement | Notes |
|---|---|
| macOS | Tested on macOS 13+ |
| Python 3 | Pre-installed on macOS — [details](docs/python.md) |
| ClickUp account | Team/workspace member |
| Homebrew + terminal-notifier | For click-to-open support — [details](docs/terminal-notifier.md) |

---

## Getting your ClickUp API Token

1. Open ClickUp → click your avatar (bottom-left) → **Settings**
2. Go to **Apps** in the left sidebar
3. Under **API Token**, click **Generate** (or copy your existing token)
4. Copy the token — it starts with `pk_`

---

## Installation

### Automated (recommended)

Clone or download this folder, then run from the project root:

```bash
bash install/setup.sh
```

The script will interactively ask you for:

1. **API token** — with instructions on where to find it
2. **Check interval** — 15 min / 30 min / 60 min / 2 hours
3. **Notification scope** — task mentions+assignments / chat mentions / both

Then it will:
- Install `terminal-notifier` via Homebrew (enables click-to-open)
- Copy the notifier script to `~/Scripts/`
- Register a launchd agent with your chosen settings
- Start the agent immediately

### Manual

If you prefer step by step:

```bash
# 1. Install terminal-notifier (see docs/terminal-notifier.md)
brew install terminal-notifier

# 2. Copy the script
mkdir -p ~/Scripts/logs
cp clickup_notifier.py ~/Scripts/clickup_notifier.py
chmod +x ~/Scripts/clickup_notifier.py

# 3. Edit the plist template
#    Copy install/com.clickup-notifier.plist to ~/Library/LaunchAgents/
#    Replace YOUR_API_TOKEN_HERE and YOUR_USERNAME with real values
#    Set NOTIFY_TASKS and NOTIFY_CHAT to true or false as needed
#    Set StartInterval in seconds (900=15m, 1800=30m, 3600=1h, 7200=2h)

# 4. Load the agent
launchctl load ~/Library/LaunchAgents/com.clickup-notifier.plist
```

---

## How It Works

Every check interval (while your Mac is awake):

1. Calls the ClickUp API with your token
2. Scans tasks updated in the **last 3 days** across your workspace
3. Checks comments on each task for `@mentions` of your user ID
4. Scans space chat channels for `@mentions`
5. Sends one desktop notification per active mention/assignment

**Reply = cleared.** If you've replied to a task comment thread or posted in a chat channel after the mention, the notifier considers it handled and stops notifying for that mention. For tasks, closing the task also stops notifications.

---

## Notification Behaviour

| Event | Repeats? | Clears when |
|---|---|---|
| Task @mention | Yes, every interval | You reply in the task, or the task is closed |
| Chat @mention | Yes, every interval | You post in that channel after the mention |
| New assignment | No (once only) | — |

---

## Files

```
clickup_notifier.py          Main script
install/
  setup.sh                   One-command installer
  com.clickup-notifier.plist launchd agent template
docs/
  python.md                  Python installation guide
  terminal-notifier.md       terminal-notifier installation guide
logs/
  notifier.log               stdout — every run is logged here
  notifier_error.log         stderr — Python errors
```

---

## Management

```bash
# Watch logs live
tail -f ~/Scripts/logs/notifier.log

# Trigger an immediate run (without waiting for the interval)
launchctl kickstart -k gui/$(id -u)/com.clickup-notifier

# Stop the notifier
launchctl unload ~/Library/LaunchAgents/com.clickup-notifier.plist

# Start it again
launchctl load ~/Library/LaunchAgents/com.clickup-notifier.plist

# Check if it's running
launchctl list | grep clickup
```

---

## Rotating your API token

1. Get a new token from ClickUp Settings → Apps
2. Edit the plist:
   ```bash
   open ~/Library/LaunchAgents/com.clickup-notifier.plist
   ```
   Update the `CLICKUP_API_TOKEN` value.
3. Restart the agent:
   ```bash
   launchctl unload ~/Library/LaunchAgents/com.clickup-notifier.plist
   launchctl load ~/Library/LaunchAgents/com.clickup-notifier.plist
   ```

---

## Changing settings after install

To change the interval or notification scope, edit the plist directly:

```bash
open ~/Library/LaunchAgents/com.clickup-notifier.plist
```

- **Interval:** update `StartInterval` (seconds: 900=15m, 1800=30m, 3600=1h, 7200=2h)
- **Scope:** set `NOTIFY_TASKS` and/or `NOTIFY_CHAT` to `true` or `false`

Then restart the agent for changes to take effect.

---

## Troubleshooting

**No notifications showing up**
- Check the log: `tail -f ~/Scripts/logs/notifier.log`
- Check for errors: `cat ~/Scripts/logs/notifier_error.log`
- Confirm the agent is loaded: `launchctl list | grep clickup`

**Clicking a notification opens the wrong place**
- Make sure `terminal-notifier` is installed — see [docs/terminal-notifier.md](docs/terminal-notifier.md)
- The agent must be restarted after installing it

**Getting notified about something you already handled**
- Reply to the task comment or post in the chat channel — the notifier uses your reply as the "cleared" signal
- Closing the task also stops task mention notifications

**Agent stops running after reboot**
- Re-run `bash install/setup.sh` or run:
  ```bash
  launchctl load ~/Library/LaunchAgents/com.clickup-notifier.plist
  ```
  launchd agents loaded this way persist across reboots automatically.

**Python not found**
- See [docs/python.md](docs/python.md) for installation options.
