# Claude Account Switcher

A lightweight macOS menu bar app that lets you switch between multiple Claude Code accounts instantly — and see your usage for each one.

## Why?

If you have multiple Claude Code subscriptions (personal, work, etc.), switching between them means running `claude auth logout` + `claude auth login` every time — opening a browser, logging in, waiting. When you hit your rate limit on one account and want to continue working on another, this friction kills your flow.

Claude Account Switcher saves your credentials securely in the macOS Keychain and lets you switch accounts with a single click. No logout, no login, no browser. Instant.

## Features

- **One-click account switching** — no logout/login, no browser
- **Live usage display** — shows 5-hour and 7-day utilization for each account directly in the menu
- **Secure credential storage** — credentials stored in macOS Keychain, never on disk
- **Auto-import** — detects your current Claude Code account on first launch

## How it works

1. Your Claude Code credentials live in the macOS Keychain under `Claude Code-credentials`
2. The app saves a copy of each account's credentials in separate Keychain entries
3. When you switch, it overwrites the official entry with the target account's credentials — all Claude Code sessions immediately use the new account
4. Usage is fetched via Anthropic's OAuth API using each account's stored token

## Install

### Download the app (recommended)

1. Go to [Releases](https://github.com/emilejouannet/claude-account-switcher/releases/latest)
2. Download **Claude-Switcher.zip**
3. Unzip and drag **Claude Switcher.app** to `/Applications`
4. Launch it — the icon appears in your menu bar

> **Note:** On first launch, macOS may block the app because it's not signed. Go to **System Settings → Privacy & Security** and click **Open Anyway**.

### Install with pip

```bash
pip install git+https://github.com/emilejouannet/claude-account-switcher.git
claude-switcher
```

## Usage

A menu bar icon appears. From there:

- **See your accounts** — each account shows email, subscription type, and live usage (5h / 7j)
- **Switch accounts** — click any account to activate it instantly
- **Refresh usage** — click "Rafraîchir usage" to update usage data
- **Add an account** — triggers `claude auth login` to authenticate a new account
- **Remove an account** — removes saved credentials from the Keychain

On first launch, the app automatically imports your currently logged-in Claude Code account.

## Requirements

- macOS 12+
- [Claude Code](https://claude.ai/code) installed and accessible via `claude` CLI

## Build from source

```bash
git clone https://github.com/emilejouannet/claude-account-switcher.git
cd claude-account-switcher
python3 -m venv .venv && source .venv/bin/activate
pip install -e . && pip install py2app pytest
```

Run directly:
```bash
claude-switcher
```

Build the standalone `.app`:
```bash
bash build_app.sh
# Output: dist/Claude Switcher.app
```

Run tests:
```bash
pytest tests/ -v
```

## License

MIT
