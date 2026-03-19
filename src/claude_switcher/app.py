"""macOS menu bar application using rumps."""

import threading
from pathlib import Path

import rumps
from claude_switcher.config import load_accounts, get_active_account, DEFAULT_CONFIG_PATH
from claude_switcher.core import (
    check_claude_cli,
    import_current_account,
    switch_account,
    add_new_account,
    remove_saved_account,
)
from claude_switcher.usage import fetch_usage_for_account, fetch_active_usage, format_usage


class ClaudeSwitcherApp(rumps.App):
    def __init__(self):
        icon_path = Path(__file__).parent / "resources" / "icon.png"
        super().__init__("", icon=str(icon_path), template=True, quit_button=None)
        self.config_path = DEFAULT_CONFIG_PATH
        self._usage_cache = {}   # email -> formatted usage string
        self._usage_items = {}   # email -> MenuItem reference
        self._first_launch()
        self._rebuild_menu()
        self._fetch_all_usage()

    def _first_launch(self):
        """Import existing account on first launch if no config exists."""
        if not self.config_path.exists():
            if not check_claude_cli():
                rumps.alert(
                    title="Claude CLI introuvable",
                    message="Installez Claude Code avant d'utiliser Claude Switcher.",
                )
                return
            imported = import_current_account(self.config_path)
            if imported:
                rumps.notification(
                    title="Claude Switcher",
                    subtitle="Compte importé",
                    message=f"{imported.email} ({imported.subscription_type})",
                )

    def _rebuild_menu(self):
        """Rebuild the menu from current account state."""
        accounts = load_accounts(self.config_path)
        active = get_active_account(self.config_path)

        self.menu.clear()

        # Active account header
        if active:
            header = rumps.MenuItem(f"Actif : {active.email} ({active.subscription_type})")
            header.set_callback(None)
            self.menu.add(header)
            self.menu.add(rumps.separator)

        # Account items — validate Keychain entries exist
        from claude_switcher import keychain
        for acc in accounts:
            has_creds = keychain.read_credentials(f"claude-switcher:{acc.email}") is not None
            if has_creds:
                prefix = "\u2713 " if acc.active else "   "
                label = f"{prefix}{acc.email} ({acc.subscription_type})"
                item = rumps.MenuItem(label, callback=self._on_account_click)
            else:
                label = f"   {acc.email} (indisponible)"
                item = rumps.MenuItem(label, callback=None)
            item._email = acc.email
            self.menu.add(item)

            # Usage sub-label (placeholder, filled async)
            if has_creds:
                cached = self._usage_cache.get(acc.email, "Loading...")
                usage_label = rumps.MenuItem(f"      {cached}", callback=None)
                usage_label._email = acc.email
                self._usage_items[acc.email] = usage_label
                self.menu.add(usage_label)

        self.menu.add(rumps.separator)

        # Add account
        self.menu.add(rumps.MenuItem("Ajouter un compte...", callback=self._on_add_account))

        # Refresh usage
        self.menu.add(rumps.MenuItem("Rafraîchir usage", callback=self._on_refresh_usage))

        # Remove account submenu
        if accounts:
            remove_menu = rumps.MenuItem("Supprimer un compte")
            for acc in accounts:
                remove_item = rumps.MenuItem(acc.email, callback=self._on_remove_account)
                remove_item._email = acc.email
                remove_menu.add(remove_item)
            self.menu.add(remove_menu)

        self.menu.add(rumps.separator)
        self.menu.add(rumps.MenuItem("Quitter", callback=rumps.quit_application))

    def _on_account_click(self, sender):
        """Switch to the clicked account."""
        email = sender._email
        active = get_active_account(self.config_path)
        if active and active.email == email:
            return  # Already active

        try:
            switch_account(email, self.config_path)
            rumps.notification(
                title="Claude Switcher",
                subtitle="Compte activé",
                message=email,
            )
        except Exception as e:
            rumps.alert(title="Erreur", message=str(e))

        self._rebuild_menu()

    def _on_add_account(self, _):
        """Add a new account via claude auth login."""
        if not check_claude_cli():
            rumps.alert(
                title="Claude CLI introuvable",
                message="Installez Claude Code avant d'ajouter un compte.",
            )
            return

        try:
            result = add_new_account(self.config_path)
            if result:
                rumps.notification(
                    title="Claude Switcher",
                    subtitle="Compte ajouté",
                    message=f"{result.email} ({result.subscription_type})",
                )
            else:
                rumps.notification(
                    title="Claude Switcher",
                    subtitle="Ajout annulé",
                    message="Le login a été annulé ou a échoué.",
                )
        except Exception as e:
            rumps.alert(title="Erreur", message=str(e))
        self._rebuild_menu()

    def _fetch_all_usage(self):
        """Fetch usage for all accounts in a background thread."""
        accounts = load_accounts(self.config_path)
        active = get_active_account(self.config_path)

        def _fetch():
            for acc in accounts:
                if active and acc.email == active.email:
                    usage = fetch_active_usage()  # fresh token from CLAUDE_SERVICE
                else:
                    usage = fetch_usage_for_account(acc.email)
                self._usage_cache[acc.email] = format_usage(usage)
            self._update_usage_labels()

        threading.Thread(target=_fetch, daemon=True).start()

    def _update_usage_labels(self):
        """Update usage labels in the menu from cache."""
        for email, item in self._usage_items.items():
            usage_text = self._usage_cache.get(email, "Usage indisponible")
            item.title = f"      {usage_text}"

    def _on_refresh_usage(self, _):
        """Refresh usage data for all accounts."""
        self._fetch_all_usage()

    def _on_remove_account(self, sender):
        """Remove a saved account."""
        email = sender._email
        active = get_active_account(self.config_path)

        if active and active.email == email:
            rumps.alert(
                title="Impossible",
                message="Vous ne pouvez pas supprimer le compte actif. Changez de compte d'abord.",
            )
            return

        remove_saved_account(email, self.config_path)
        rumps.notification(
            title="Claude Switcher",
            subtitle="Compte supprimé",
            message=email,
        )
        self._rebuild_menu()


def main():
    ClaudeSwitcherApp().run()


if __name__ == "__main__":
    main()
