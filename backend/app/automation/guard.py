"""Places Jarvis must never press, type or click in: password managers,
System Settings, terminals, banking and crypto sites. Editable in Settings →
Permissions (control.blocked_apps / control.blocked_sites)."""
from __future__ import annotations

from ..config import settings

DEFAULT_APPS = ["1Password", "Bitwarden", "Dashlane", "LastPass", "Keeper", "Passwords",
                "Keychain Access", "System Settings", "System Preferences", "Terminal",
                "iTerm", "iTerm2", "Warp", "Ghostty", "Wallet"]
# Matched as plain words/fragments in the page address.
DEFAULT_SITES = ["bank", "paypal", "revolut", "monzo", "starling", "wise.com", "coinbase",
                 "binance", "kraken", "stripe.com", "accounts.google.com", "appleid.apple.com",
                 "icloud.com/settings", "1password.com", "bitwarden.com"]
BROWSERS = ("Safari", "Google Chrome", "Arc", "Microsoft Edge", "Brave Browser", "Firefox")
CONTROL_TOOLS = {"ui_press", "ui_type", "press_keys", "scroll", "drag", "click_on_screen",
                 "browser_click", "browser_js", "run_applescript", "ui_elements"}


def blocked_apps() -> list[str]:
    return list(settings.get("control.blocked_apps", DEFAULT_APPS) or [])


def blocked_sites() -> list[str]:
    return list(settings.get("control.blocked_sites", DEFAULT_SITES) or [])


def app_reason(app: str) -> str:
    a = (app or "").strip().lower()
    if a and any(a == b.lower() or a.startswith(b.lower() + " ") for b in blocked_apps()):
        return (f"{app} is off-limits: Jarvis never controls it (Settings → Permissions). "
                "Tell the user to do this part themselves.")
    return ""


def site_reason(url: str) -> str:
    u = (url or "").lower()
    hit = next((s for s in blocked_sites() if s.lower() in u), None)
    if hit:
        return (f"This page ({url[:80]}) is off-limits — Jarvis never clicks or types on "
                f"banking, payment or account sites (rule: '{hit}'). Tell the user to do "
                "it themselves.")
    return ""


def check(app: str = "") -> str:
    """'' if Jarvis may control `app` (default: the app the user is in), else why not."""
    from . import selection
    target = app or selection.user_app()
    if reason := app_reason(target):
        return reason
    if any(b.lower() in (target or "").lower() for b in BROWSERS):
        _, url = selection._browser_page(target)
        return site_reason(url)
    return ""
