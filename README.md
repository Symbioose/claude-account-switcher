# Claude Account Switcher

![Claude Switcher screenshot](screenshot.png)

A lightweight macOS menu bar app that lets you switch between multiple Claude Code accounts instantly — and see your usage for each one.

## Why?

If you have multiple Claude Code subscriptions (personal, work, etc.), switching between them means running `claude auth logout` + `claude auth login` every time — opening a browser, logging in, waiting. When you hit your rate limit on one account and want to continue working on another, this friction kills your flow.

Claude Account Switcher saves your credentials securely in the macOS Keychain and lets you switch accounts with a single click. No logout, no login, no browser. Instant.

## Features

- **One-click account switching** — no logout/login, no browser
- **Live usage display** — shows 5-hour and 7-day utilization for each account directly in the menu
- **Secure credential storage** — credentials stored in macOS Keychain, never on disk
- **Auto-import** — detects your current Claude Code account on first launch
- **Full session switching** — swaps both OAuth tokens and Claude CLI state (`~/.claude.json`), so `claude auth status` always reflects the active account

## How it works

Claude Code stores its authentication in two places:

1. **macOS Keychain** — OAuth tokens (access + refresh) under the service `Claude Code-credentials`
2. **`~/.claude.json`** — account metadata (email, org, subscription type) in the `oauthAccount` field

When you add an account, the app:
1. Backs up the current credentials to a separate Keychain entry (`claude-switcher:{email}`)
2. Saves the `oauthAccount` metadata from `~/.claude.json` into its config
3. Runs `claude auth logout` + `claude auth login` for the new account
4. Imports the new account's credentials and metadata

When you switch accounts, the app:
1. Saves the current account's Keychain credentials and `oauthAccount` state
2. Restores the target account's OAuth token into `Claude Code-credentials`
3. Restores the target account's `oauthAccount` into `~/.claude.json`
4. All Claude Code sessions immediately use the new account

Usage data (5h/7d rate limits) is fetched via Anthropic's OAuth API using each account's stored token.

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│  macOS Keychain                                         │
│                                                         │
│  "Claude Code-credentials"     ← active account token   │
│  "claude-switcher:user1@…"     ← backup token account 1 │
│  "claude-switcher:user2@…"     ← backup token account 2 │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  ~/.claude.json                                         │
│                                                         │
│  oauthAccount: { emailAddress, orgId, ... }             │
│  ↑ swapped on each account switch                       │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│  ~/.config/claude-switcher/accounts.json  (mode 0600)   │
│                                                         │
│  Per account: email, subscription_type, org_name,       │
│  keychain_account, oauth_account (cached metadata)      │
└─────────────────────────────────────────────────────────┘
```

## Install

### Homebrew (recommended)

```bash
brew install --cask Symbioose/tap/claude-switcher
```

Then launch it from Spotlight or `/Applications/Claude Switcher.app`.

### Download the app

1. Go to [Releases](https://github.com/Symbioose/claude-account-switcher/releases/latest)
2. Download **Claude-Switcher.zip**
3. Unzip and drag **Claude Switcher.app** to `/Applications`
4. Launch it — the icon appears in your menu bar

> **Note:** On first launch, macOS may block the app because it's not signed. Go to **System Settings → Privacy & Security** and click **Open Anyway**.

## Usage

A menu bar icon appears. From there:

- **See your accounts** — each account shows email, subscription type, and live usage (5h / 7j)
- **Switch accounts** — click any account to activate it instantly
- **Refresh usage** — click "Rafraîchir usage" to update usage data
- **Add an account** — triggers `claude auth login` to authenticate a new account
- **Remove an account** — removes saved credentials from the Keychain

On first launch, the app automatically imports your currently logged-in Claude Code account.

### Verifying a switch

After switching, you can confirm in any terminal:

```bash
claude auth status
# Should show the newly activated account's email
```

## Security

- **Credentials are stored exclusively in the macOS Keychain** — never written to disk files
- **Config file** (`~/.config/claude-switcher/accounts.json`) stores only account metadata (email, org name, subscription type, cached `oauthAccount` state) with `0600` permissions
- **Config directory** has `0700` permissions
- **Email validation** prevents Keychain service name injection
- **No `shell=True`** in any subprocess call — no command injection possible
- **OAuth tokens** pass through `security` CLI arguments (brief `ps` visibility, inherent to macOS `security` tool)

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
