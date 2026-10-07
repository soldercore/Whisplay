from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import types
import unittest
from types import SimpleNamespace
from unittest import mock

DAEMON_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if DAEMON_DIR not in sys.path:
    sys.path.insert(0, DAEMON_DIR)

try:
    import numpy  # noqa: F401
    from PIL import Image, ImageFont  # noqa: F401

    HAVE_IMAGING = hasattr(ImageFont, "truetype")
except ImportError:
    HAVE_IMAGING = False

sys.modules.setdefault("spidev", types.ModuleType("spidev"))
sys.modules.setdefault("gpiod", types.ModuleType("gpiod"))

FRAME_BYTES = 240 * 280 * 2


@unittest.skipUnless(HAVE_IMAGING, "Pillow and numpy are needed to render the menu")
class CyberMenuRenderTests(unittest.TestCase):
    def setUp(self):
        from cyber_ui import preview

        self.preview = preview
        self.env = mock.patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ.pop("WHISPLAY_MENU_UI", None)

    def tearDown(self):
        self.env.stop()

    def board(self):
        board = self.preview.FakeBoard()
        board.set_rgb = lambda *_args: None
        board.set_backlight = lambda *_args: None
        return board

    def fallback(self, board, **kwargs):
        from cyber_ui.fallback import FallbackDesktopRenderer

        return FallbackDesktopRenderer(board, DAEMON_DIR, **kwargs)

    def classic_frame(self, action):
        from daemon_renderer import DesktopRenderer

        board = self.board()
        action(DesktopRenderer(board, DAEMON_DIR))
        return board.fb.copy()

    def test_every_screen_renders_a_full_frame_without_hardware(self):
        for name, action in self.preview.scenarios():
            with self.subTest(screen=name):
                board = self.board()
                renderer = self.fallback(board)
                action(renderer)
                self.assertEqual(renderer.mode, "cyber")
                self.assertEqual(board.draws, [(0, 0, 240, 280)])
                self.assertTrue(board.fb.any())

    def test_cyber_frames_use_the_shared_palette(self):
        from cyber_ui import theme

        board = self.board()
        self.fallback(board).render(self.preview.default_apps(), 2, None, None, 3, 80)
        colours = {tuple(c) for c in board.fb.reshape(-1, 3)}
        self.assertIn(theme.VOID, colours)
        self.assertIn(theme.GREEN, colours)
        self.assertIn(theme.LINE, colours)

    def test_selection_changes_the_frame(self):
        apps = self.preview.default_apps()
        first, second = self.board(), self.board()
        self.fallback(first).render(apps, 0, None, None, 3, 80)
        self.fallback(second).render(apps, 1, None, None, 3, 80)
        self.assertFalse((first.fb == second.fb).all())

    def test_classic_env_forces_original_launcher(self):
        os.environ["WHISPLAY_MENU_UI"] = "classic"
        board = self.board()
        renderer = self.fallback(board)
        self.assertEqual(renderer.mode, "classic")
        apps = self.preview.default_apps()
        renderer.render(apps, 3, None, None, 3, 80)
        expected = self.classic_frame(lambda r: r.render(apps, 3, None, None, 3, 80))
        self.assertTrue((board.fb == expected).all())

    def test_other_env_values_select_cyber(self):
        from cyber_ui import menu_ui_mode

        self.assertEqual(menu_ui_mode({}), "cyber")
        self.assertEqual(menu_ui_mode({"WHISPLAY_MENU_UI": "cyber"}), "cyber")
        self.assertEqual(menu_ui_mode({"WHISPLAY_MENU_UI": " Classic "}), "classic")

    def test_init_failure_falls_back_to_classic(self):
        def broken(*_args, **_kwargs):
            raise RuntimeError("injected init failure")

        board = self.board()
        renderer = self.fallback(board, cyber_factory=broken)
        self.assertEqual(renderer.mode, "classic")
        apps = self.preview.default_apps()
        renderer.render(apps, 1, None, None, 2, 50)
        expected = self.classic_frame(lambda r: r.render(apps, 1, None, None, 2, 50))
        self.assertTrue((board.fb == expected).all())

    def test_render_failure_redraws_with_classic_and_stays_classic(self):
        board = self.board()
        renderer = self.fallback(board)
        self.assertEqual(renderer.mode, "cyber")

        def boom(*_args, **_kwargs):
            raise RuntimeError("injected render failure")

        renderer.cyber.render = boom
        apps = self.preview.default_apps()
        renderer.render(apps, 4, None, None, 3, 90)
        self.assertEqual(renderer.mode, "classic")
        expected = self.classic_frame(lambda r: r.render(apps, 4, None, None, 3, 90))
        self.assertTrue((board.fb == expected).all())
        renderer.render_internal_app(self.preview.LIST_POWER)
        expected = self.classic_frame(lambda r: r.render_internal_app(self.preview.LIST_POWER))
        self.assertTrue((board.fb == expected).all())

    def test_internal_app_failure_falls_back(self):
        board = self.board()
        renderer = self.fallback(board)

        def boom(*_args, **_kwargs):
            raise ValueError("injected internal app failure")

        renderer.cyber.render_internal_app = boom
        renderer.render_internal_app(self.preview.KEYBOARD)
        self.assertEqual(renderer.mode, "classic")
        self.assertEqual(len(board.draws), 1)

    def test_missing_fonts_still_render(self):
        from cyber_ui.menu_renderer import CyberDesktopRenderer

        empty = tempfile.mkdtemp(prefix="whisplay-menu-nofonts-")
        try:
            for base in ("/nonexistent/font.ttf", None):
                renderer = CyberDesktopRenderer(self.board(), DAEMON_DIR, base_font_path=base, font_dir=empty)
                self.assertFalse(renderer.fonts.loaded["mono"])
                self.assertFalse(renderer.fonts.loaded["pixel"])
                for name, action in self.preview.scenarios():
                    with self.subTest(base=base, screen=name):
                        board = self.board()
                        renderer.board = board
                        action(renderer)
                        self.assertEqual(len(board.draws), 1)
        finally:
            shutil.rmtree(empty, ignore_errors=True)

    def test_inputs_are_not_mutated(self):
        apps = self.preview.default_apps()
        before = [(a.app_id, a.display_name) for a in apps]
        view_model = dict(self.preview.LIST_WIFI_BUSY)
        items = list(view_model["items"])
        renderer = self.fallback(self.board())
        renderer.render(apps, 2, "whisplay-wifi", None, 3, 80)
        renderer.render_internal_app(view_model)
        self.assertEqual(before, [(a.app_id, a.display_name) for a in apps])
        self.assertEqual(items, view_model["items"])


@unittest.skipUnless(HAVE_IMAGING, "Pillow and numpy are needed to render the menu")
class DaemonIntegrationTests(unittest.TestCase):
    """The daemon's own navigation code drives the new renderer unchanged."""

    def make_daemon(self):
        from cyber_ui import preview
        from cyber_ui.fallback import FallbackDesktopRenderer
        from whisplay_daemon import WhisplayDaemon

        board = preview.FakeBoard()
        board.rgb = []
        board.set_rgb = lambda r, g, b: board.rgb.append((r, g, b))
        daemon = WhisplayDaemon.__new__(WhisplayDaemon)
        daemon.state_lock = threading.RLock()
        daemon.board = board
        daemon.desktop = FallbackDesktopRenderer(board, DAEMON_DIR)
        daemon.apps = {app.app_id: app for app in preview.default_apps()}
        daemon.selected_app_index = 0
        daemon.foreground_app_id = None
        daemon.pending_launch_app_id = None
        daemon._screen_locked = False
        daemon._button_press_started_at = 0.0
        daemon._recent_release_times = []
        daemon.last_frame = None
        daemon.status_poller = SimpleNamespace(wifi_signal_level=3, battery_level=80)
        daemon.internal_apps = SimpleNamespace(is_internal_app=lambda _app_id: False)
        return daemon

    def test_daemon_builds_the_fallback_renderer(self):
        import whisplay_daemon
        from cyber_ui.fallback import FallbackDesktopRenderer

        self.assertIs(whisplay_daemon.FallbackDesktopRenderer, FallbackDesktopRenderer)

    def test_daemon_starts_classic_when_cyber_ui_cannot_import(self):
        import subprocess

        code = (
            "import sys, types\n"
            "sys.path.insert(0, %r)\n"
            "sys.modules['cyber_ui'] = None\n"
            "sys.modules.setdefault('spidev', types.ModuleType('spidev'))\n"
            "sys.modules.setdefault('gpiod', types.ModuleType('gpiod'))\n"
            "import whisplay_daemon\n"
            "assert whisplay_daemon.FallbackDesktopRenderer is None\n"
            "print('classic-ok')\n"
        ) % DAEMON_DIR
        result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
        self.assertIn("classic-ok", result.stdout, result.stderr)

    def test_short_press_moves_selection_and_redraws(self):
        daemon = self.make_daemon()
        daemon._render_desktop()
        first = daemon.board.fb.copy()
        daemon._on_button_released()
        self.assertEqual(daemon.selected_app_index, 1)
        self.assertEqual(daemon.desktop.mode, "cyber")
        self.assertFalse((daemon.board.fb == first).all())

    def test_selection_wraps_like_before(self):
        daemon = self.make_daemon()
        total = len(daemon.apps)
        for _ in range(total):
            daemon._move_desktop_selection(1)
        self.assertEqual(daemon.selected_app_index, 0)
        daemon._move_desktop_selection(-1)
        self.assertEqual(daemon.selected_app_index, total - 1)

    def test_empty_app_list_renders(self):
        daemon = self.make_daemon()
        daemon.apps = {}
        daemon._on_button_released()
        self.assertEqual(daemon.board.draws[-1], (0, 0, 240, 280))
        self.assertEqual(daemon.desktop.mode, "cyber")


if __name__ == "__main__":
    unittest.main()
