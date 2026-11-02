"""Exercise the installed input/monitor paths with no GPIO or real processes."""
import os
import sys
import threading
import types
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.modules.setdefault('spidev', types.ModuleType('spidev'))
sys.modules.setdefault('gpiod', types.ModuleType('gpiod'))
try:
    import PIL
except ImportError:
    pil = types.ModuleType('PIL')
    pil.Image = SimpleNamespace(Image=object)
    pil.ImageDraw = SimpleNamespace(ImageDraw=object)
    pil.ImageFont = SimpleNamespace()
    sys.modules['PIL'] = pil

from daemon_models import AppRecord
from whisplay_daemon import WhisplayDaemon


class NavigationTests(unittest.TestCase):
    def daemon(self):
        d = WhisplayDaemon.__new__(WhisplayDaemon)
        d.state_lock = threading.RLock()
        d.board = SimpleNamespace(set_rgb=lambda *args: None)
        d.apps = {'chat': AppRecord('chat', 'Chat')}
        d.foreground_app_id = 'chat'
        d.selected_app_index = 0
        d.pending_launch_app_id = None
        d.pending_launch_started_at = 0
        d.exit_request = None
        d._app_exits = {}
        d._screen_locked = False
        d._ignore_button_release = False
        d._button_press_started_at = 0
        d._recent_release_times = []
        d._foreground_long_press_fired = False
        d._keyboard_hold_cancel_fired = False
        d.joy_mode = False
        d.last_frame = None
        d.event_broadcaster = SimpleNamespace(broadcast=Mock())
        d.internal_apps = SimpleNamespace(is_internal_app=lambda app: False)
        d.pisugar = SimpleNamespace(poll_pisugar3_power_button_single=lambda: False,
                                   poll_home_trigger=lambda: False,
                                   pisugar3_power_button_exit_enabled=False)
        d._teardown_framebuffer = lambda app: None
        d._render_desktop = Mock()
        d._refresh_status_icons = lambda: None
        d._process_button_hold = lambda: None
        return d

    def tick(self, daemon, now):
        daemon.running = True
        with patch('whisplay_daemon.time.time', return_value=now), patch(
                'whisplay_daemon.time.sleep', side_effect=lambda _: setattr(daemon, 'running', False)):
            daemon._monitor_loop()

    def test_four_click_escape_still_delivers_push_to_talk_and_requests_exit(self):
        d = self.daemon()
        for i in range(4):
            with patch('whisplay_daemon.time.time', return_value=100 + i * .25):
                d._on_button_pressed()
                d._on_button_released()
        events = [call.args[0] for call in d.event_broadcaster.broadcast.call_args_list]
        self.assertEqual(events.count('button_pressed'), 4)
        self.assertEqual(events.count('button_released'), 4)
        self.assertIn('app_exit_requested', events)
        self.assertEqual(d.exit_request['reason'], 'quad_click_exit')

    def test_home_short_press_moves_and_long_press_opens(self):
        d = self.daemon()
        d.foreground_app_id = None
        d.apps['other'] = AppRecord('other', 'Other')
        d._launch_app = Mock()
        with patch('whisplay_daemon.time.time', return_value=100):
            d._on_button_pressed()
            d._on_button_released()
        self.assertEqual(d.selected_app_index, 1)
        d._on_button_pressed()
        with patch('whisplay_daemon.time.time', return_value=10**12):
            d._on_button_released()
        d._launch_app.assert_called_once_with(d.apps['other'])

    def test_hung_owned_app_returns_home_and_escalates_only_its_group(self):
        d = self.daemon()
        process = Mock(pid=3210)
        process.poll.return_value = None
        d.apps['chat'].process = process
        with patch('whisplay_daemon.time.time', return_value=100):
            d._request_exit(d.apps['chat'], 'quad_click_exit')
        with patch('whisplay_daemon.os.killpg', create=True) as killpg:
            self.tick(d, 102)
            self.assertIsNone(d.foreground_app_id)
            killpg.assert_called_once()
            self.assertEqual(killpg.call_args.args[0], 3210)
            self.assertEqual(len(killpg.call_args_list), 1)
            with self.assertRaisesRegex(RuntimeError, 'stopping'):
                d._launch_app(d.apps['chat'])
            self.tick(d, 105)
            self.assertEqual(len(killpg.call_args_list), 2)
            self.assertTrue(all(call.args[0] == 3210 for call in killpg.call_args_list))
            process.poll.return_value = 0
            self.tick(d, 108)
            self.assertEqual(d._app_exits, {})

    def test_repeated_exit_requests_cannot_extend_deadline(self):
        d = self.daemon()
        d.apps['chat'].process = Mock(pid=3210)
        d.apps['chat'].process.poll.return_value = None
        with patch('whisplay_daemon.time.time', return_value=100):
            d._request_exit(d.apps['chat'], 'quad_click_exit')
        deadline = d.exit_request['deadline']
        with patch('whisplay_daemon.time.time', return_value=101):
            d._request_exit(d.apps['chat'], 'quad_click_exit')
        self.assertEqual(d.exit_request['deadline'], deadline)

    def test_child_replacement_or_normal_exit_is_never_signalled(self):
        for replaced in (False, True):
            d = self.daemon()
            old = Mock(pid=3210)
            old.poll.return_value = None
            d.apps['chat'].process = old
            with patch('whisplay_daemon.time.time', return_value=100):
                d._request_exit(d.apps['chat'], 'quad_click_exit')
            if replaced:
                d.apps['chat'].process = Mock(pid=6540)
            else:
                old.poll.return_value = 0
            with patch('whisplay_daemon.os.killpg', create=True) as killpg:
                d._advance_app_exits(105)
                killpg.assert_not_called()
            self.assertEqual(d._app_exits, {})

    def test_focus_release_does_not_cancel_pending_owned_cleanup(self):
        d = self.daemon()
        d.apps['chat'].process = Mock(pid=3210)
        d.apps['chat'].process.poll.return_value = None
        with patch('whisplay_daemon.time.time', return_value=100):
            d._request_exit(d.apps['chat'], 'quad_click_exit')
        d._release_focus(d.apps['chat'], 'app_release')
        with patch('whisplay_daemon.os.killpg', create=True) as killpg:
            self.tick(d, 102)
            killpg.assert_called_once()

    def test_release_across_focus_handoff_cannot_open_a_home_item(self):
        d = self.daemon()
        d._button_press_started_at = 100
        d._release_focus(d.apps['chat'], 'process_exit')
        d._launch_app = Mock()
        with patch('whisplay_daemon.time.time', return_value=105):
            d._on_button_released()
        d._launch_app.assert_not_called()
        self.assertEqual(d.selected_app_index, 0)

    def test_crashed_foreground_app_returns_home(self):
        d = self.daemon()
        d.apps['chat'].process = Mock()
        d.apps['chat'].process.poll.return_value = 1
        self.tick(d, 100)
        self.assertIsNone(d.foreground_app_id)
        self.assertIsNone(d.apps['chat'].process)
        d._render_desktop.assert_called()
