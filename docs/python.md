# Python Installation Guide

The ClickUp Desktop Notifier requires **Python 3.6+**. macOS ships with Python 3 pre-installed, so most users don't need to do anything.

---

## Check if Python 3 is already installed

Open Terminal and run:

```bash
python3 --version
```

If you see something like `Python 3.x.x`, you're all set.

---

## macOS built-in Python (recommended — no install needed)

macOS 12.3+ ships with Python 3 at `/usr/bin/python3`. The notifier uses this path by default.

If you see a prompt to install Xcode Command Line Tools the first time you run `python3`, click **Install** and wait for it to finish (~5 minutes). Python 3 will then be available.

---

## Installing Python 3 via Homebrew (optional)

If you prefer to manage Python yourself:

```bash
# Install Homebrew first if you haven't already
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Then install Python
brew install python
```

Homebrew Python installs to `/opt/homebrew/bin/python3` (Apple Silicon) or `/usr/local/bin/python3` (Intel).

> **Note:** If you use Homebrew Python, update the plist's `ProgramArguments` to point to the correct path:
> ```xml
> <string>/opt/homebrew/bin/python3</string>
> ```
> Then restart the agent: `launchctl unload` then `launchctl load` the plist.

---

## Installing Python 3 via python.org

Download the official installer from [python.org/downloads](https://www.python.org/downloads/) and run the `.pkg` file. The installer places Python at `/usr/local/bin/python3`.

---

## No third-party packages required

The notifier uses only Python standard library modules (`json`, `os`, `re`, `subprocess`, `urllib`). No `pip install` needed.
