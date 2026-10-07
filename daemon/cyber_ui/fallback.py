"""Renderer selection with an automatic, permanent fallback to classic.

FallbackDesktopRenderer has the same interface as DesktopRenderer. The classic
renderer is always built first, so a broken cyber renderer can never stop the
daemon from drawing: any exception while building or rendering the cyber UI
switches to classic for the rest of the process, and the failed call is
redrawn by classic straight away.
"""
from __future__ import annotations

import traceback

from daemon_renderer import DesktopRenderer


class FallbackDesktopRenderer:
    def __init__(self, board, script_dir: str, cyber_factory=None):
        from . import menu_ui_mode

        self.classic = DesktopRenderer(board, script_dir)
        self.cyber = None
        if menu_ui_mode() == "classic":
            print("[WhisplayDaemon] Menu UI: classic (WHISPLAY_MENU_UI=classic)")
            return
        try:
            if cyber_factory is None:
                from .menu_renderer import CyberDesktopRenderer as cyber_factory
            self.cyber = cyber_factory(board, script_dir)
            print("[WhisplayDaemon] Menu UI: cyber terminal (set WHISPLAY_MENU_UI=classic for the classic menu)")
        except Exception as exc:
            traceback.print_exc()
            print(f"[WhisplayDaemon] Cyber menu UI unavailable, using classic: {exc}")
            self.cyber = None

    @property
    def mode(self) -> str:
        return "cyber" if self.cyber is not None else "classic"

    def _call(self, name, *args, **kwargs):
        if self.cyber is not None:
            try:
                return getattr(self.cyber, name)(*args, **kwargs)
            except Exception as exc:
                traceback.print_exc()
                print(f"[WhisplayDaemon] Cyber menu UI failed in {name}, falling back to classic: {exc}")
                self.cyber = None
        return getattr(self.classic, name)(*args, **kwargs)

    def render(self, *args, **kwargs):
        return self._call("render", *args, **kwargs)

    def render_internal_app(self, *args, **kwargs):
        return self._call("render_internal_app", *args, **kwargs)

    def __getattr__(self, name):
        # Anything else the daemon might use stays on the classic renderer.
        if name in ("classic", "cyber"):
            raise AttributeError(name)
        return getattr(self.classic, name)
