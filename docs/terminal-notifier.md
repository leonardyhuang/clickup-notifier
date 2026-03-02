# terminal-notifier Installation Guide

`terminal-notifier` is a small macOS utility that enables clickable desktop notifications — when you click a notification, it opens the ClickUp task or chat link directly in your browser.

Without it, the notifier falls back to macOS `osascript` notifications, which still appear but are **not clickable** (they don't open the link).

---

## Install via Homebrew (recommended)

```bash
brew install terminal-notifier
```

That's it. The setup script does this automatically if Homebrew is available.

---

## Install Homebrew first (if not already installed)

Homebrew is the standard macOS package manager. Install it with:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Follow the on-screen instructions. On Apple Silicon Macs, Homebrew installs to `/opt/homebrew`; on Intel Macs to `/usr/local`.

After installing Homebrew, add it to your PATH if prompted, then run:

```bash
brew install terminal-notifier
```

---

## Verify the installation

```bash
terminal-notifier -message "Hello!" -title "Test"
```

You should see a macOS notification pop up.

---

## Where it's installed

| Mac type      | Path                                    |
|---------------|-----------------------------------------|
| Apple Silicon | `/opt/homebrew/bin/terminal-notifier`   |
| Intel         | `/usr/local/bin/terminal-notifier`      |

The notifier script checks both paths automatically — no configuration needed.

---

## After installing (if the agent was already running)

Restart the agent so it picks up `terminal-notifier`:

```bash
launchctl unload ~/Library/LaunchAgents/com.clickup-notifier.plist
launchctl load  ~/Library/LaunchAgents/com.clickup-notifier.plist
```

---

## Without Homebrew

If you can't or don't want to use Homebrew:

- Notifications will still work via `osascript`
- Clicking a notification will **not** open the ClickUp link
- All other functionality (mention detection, logging) is unaffected

You can always add `terminal-notifier` later and restart the agent.
