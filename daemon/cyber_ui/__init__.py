"""Cyber-terminal look for the Whisplay launcher.

The visual language (palette, fonts, status bar, stage/caption framing,
action chips) comes from the chatbot's terminal UI in
soldercore/whisplay-ai-chatbot (python/whisplay_ui, commit 2dd608b). The
pieces needed here are vendored, not imported, so the daemon has no runtime
dependency on the chatbot repository. See VENDORED.md.

WHISPLAY_MENU_UI=classic keeps the original DesktopRenderer.
"""
import os


def menu_ui_mode(env=None):
    """Return "classic" or "cyber" from the WHISPLAY_MENU_UI environment variable."""
    env = os.environ if env is None else env
    value = str(env.get("WHISPLAY_MENU_UI", "") or "").strip().lower()
    return "classic" if value == "classic" else "cyber"


from .fallback import FallbackDesktopRenderer  # noqa: E402

__all__ = ["FallbackDesktopRenderer", "menu_ui_mode"]
