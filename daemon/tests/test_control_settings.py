import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import test_control_navigation as navigation
from internal_apps.manager import InternalAppManager
from internal_apps.menu import Confirmation
from internal_apps.wifi_control import WifiControl
from internal_apps.wifi_app import WifiNetwork
from internal_apps.bluetooth_control import BluetoothControl
from internal_apps.audio_control import AudioControl
from internal_apps.device_info import linux_metrics, quantity
from whisplay_daemon import WhisplayDaemon
from daemon_models import AppRecord
from daemon_shared import write_json_file


def args(run=None, spawn=None):
    return (threading.RLock(), Mock(), run or Mock(), spawn or (lambda name, target: target()), Mock())


class SettingsTests(unittest.TestCase):
    def test_all_new_menus_are_registered_and_network_back_returns_to_parent(self):
        manager = InternalAppManager()
        manager._spawn_worker = Mock()
        for app in manager._apps.values():
            app.refresh_async = Mock()
        identifiers = {app.app_id for app in manager.builtin_apps()}
        self.assertTrue({'whisplay-network', 'whisplay-display', 'whisplay-information',
                         'whisplay-volume', 'whisplay-wifi', 'whisplay-bluetooth'} <= identifiers)
        manager.activate('whisplay-network')
        manager.handle_button_release('whisplay-network', False)
        manager.handle_button_release('whisplay-network', True)
        self.assertEqual(manager.consume_navigation(), 'whisplay-wifi')
        manager.activate('whisplay-wifi')
        manager.handle_button_release('whisplay-wifi', True)
        self.assertEqual(manager.consume_navigation(), 'whisplay-network')
        manager.activate('whisplay-network')
        manager.handle_button_release('whisplay-network', True)
        self.assertTrue(manager.exit_requested)

    def test_wifi_status_never_changes_radio_and_saved_profiles_use_uuid(self):
        def run(command, timeout):
            text = ' '.join(command)
            output = ('enabled' if '-f WIFI radio' in text else
                      'wlan0:wifi:connected' if 'DEVICE,TYPE,STATE' in text else
                      '*:Lab:83:WPA2' if 'IN-USE,SSID' in text else
                      'IP4.ADDRESS[1]:192.0.2.5/24' if 'IP4.ADDRESS' in text else
                      '12345678-1234-1234-1234-123456789abc:Saved Lab:802-11-wireless')
            return SimpleNamespace(returncode=0, stdout=output, stderr='')
        runner = Mock(side_effect=run)
        app = WifiControl(*args(runner))
        app.refresh()
        self.assertEqual(app.state.networks[0].ipv4, '192.0.2.5')
        self.assertEqual(app.state.networks[0].signal, 83)
        self.assertEqual(app.saved[0][0], '12345678-1234-1234-1234-123456789abc')
        self.assertFalse(any('connect' in call.args[0] or 'on' in call.args[0] or 'off' in call.args[0]
                             for call in runner.call_args_list))
        self.assertIn('--rescan', runner.call_args_list[2].args[0])
        self.assertIn('no', runner.call_args_list[2].args[0])

    def test_wifi_password_can_be_entered_with_only_short_and_long_button(self):
        app = WifiControl(*args())
        app.select_network(WifiNetwork('Synthetic Lab', 80, 'WPA2'))
        for character in 'testpass':
            # Short presses move within visible row menus; long presses select.
            rows = app._password_items()
            key_page = next(i for i, row in enumerate(__import__('internal_apps.wifi_app', fromlist=['SCREEN_KEYBOARD_ROWS']).SCREEN_KEYBOARD_ROWS)
                            if any(key.value == character for key in row))
            target = 3 + key_page
            while app.key_index != target:
                app.handle_button(False)
            app.handle_button(True)
            target = next(i for i, row in enumerate(app._password_items()) if row[0] == character)
            while app.key_index != target:
                app.handle_button(False)
            app.handle_button(True)
        self.assertEqual(app.state.password_buffer, 'testpass')
        self.assertNotIn('testpass', json.dumps(app.view_model()))
        app.key_index = 2
        app.handle_button(True)
        self.assertEqual(app.state.password_buffer, '')
        self.assertIsNotNone(app.confirmation.pending)
        self.assertEqual(app.confirmation.selected, 0)
        app.change = Mock()
        app.handle_button(True)  # Cancel is default; never sends credentials.
        app.change.assert_not_called()

    def test_back_remains_usable_during_slow_work_and_view_does_no_io(self):
        worker = Mock()
        app = WifiControl(*args(spawn=worker))
        app.refresh_async()
        self.assertTrue(app.state.busy)
        app.state.selected_index = 0
        app.handle_button(True)
        app._request_exit.assert_called_once()
        app._run_command.reset_mock()
        app.view_model()
        app._run_command.assert_not_called()

    def test_bluetooth_read_never_powers_or_scans_and_disconnect_is_not_forget(self):
        def run(command, timeout):
            output = ('Powered: no' if command[-1] == 'show' else
                      'Device AA:BB:CC:DD:EE:FF Test speaker' if command[-1] == 'devices' else
                      'Connected: yes\nPaired: yes')
            return SimpleNamespace(returncode=0, stdout=output, stderr='')
        runner = Mock(side_effect=run)
        app = BluetoothControl(*args(runner))
        app.refresh()
        self.assertFalse(app.powered)
        self.assertIsNone(app.state.devices[0].signal)
        self.assertFalse(any('power' in call.args[0] or 'scan' in call.args[0] for call in runner.call_args_list))
        app.items()[4][2]()
        app.handle_button(False)
        app.handle_button(True)
        self.assertTrue(any('disconnect' in call.args[0] for call in runner.call_args_list))
        self.assertFalse(any('remove' in call.args[0] for call in runner.call_args_list))

    def test_volume_preserves_mapping_and_never_changes_mic_or_plays_audio(self):
        runner = Mock(return_value=SimpleNamespace(returncode=0, stdout=': values=80', stderr=''))
        app = AudioControl(*args(runner), glados_status=lambda: {'recording_enabled': True}, set_recording=Mock())
        app._detect_volume_control = Mock(return_value=('2', 'name=speaker', 100))
        app._read_current_value = Mock(return_value=80)
        app.volume(0)
        self.assertIn(['amixer', '-c', '2', 'cset', 'name=speaker', '0'], [c.args[0] for c in runner.call_args_list])
        self.assertFalse(any(c.args[0][0] == 'aplay' or ('cset' in c.args[0] and 'name=mic' in c.args[0]) for c in runner.call_args_list))
        self.assertEqual(app._curve_percent_to_device_value(50, 127), 109)
        self.assertEqual(app.mic, 80)
        app.toggle_recording()
        self.assertEqual(app.confirmation.selected, 0)
        app.handle_button(True)
        app.set_recording.assert_not_called()

    def test_missing_metrics_are_unavailable_and_command_timeout_is_not_zero(self):
        with patch('internal_apps.device_info.Path.read_text', side_effect=OSError), patch(
                'internal_apps.device_info.shutil.disk_usage', side_effect=OSError), patch(
                'internal_apps.device_info.shutil.which', return_value=None):
            result = linux_metrics(Mock())
        self.assertTrue(all(value is None for value in result.values()))
        self.assertEqual(quantity(None, '%'), 'Unavailable')
        self.assertEqual(quantity(0, '%'), '0.0 %')

    def test_atomic_recording_setting_survives_reload_and_failed_write_keeps_state(self):
        d = navigation.NavigationTests().daemon()
        d.apps = {}
        d._recording_enabled = True
        with tempfile.TemporaryDirectory() as directory:
            d._recording_path = str(Path(directory) / 'control-center.json')
            d._set_recording(False)
            self.assertFalse(json.loads(Path(d._recording_path).read_text())['glados_recording_enabled'])
            with patch('whisplay_daemon.write_json_file', side_effect=OSError):
                with self.assertRaises(OSError):
                    d._set_recording(True)
            self.assertFalse(d._recording_enabled)
            self.assertEqual(len(list(Path(directory).iterdir())), 1)

    def test_locked_recording_blocks_launch_and_focus_before_hardware_or_process(self):
        d = navigation.NavigationTests().daemon()
        d._recording_enabled = False
        app = AppRecord('whisplay-ai-chatbot', 'GLaDOS', launch_command='must-not-run')
        with patch('whisplay_daemon.subprocess.Popen') as popen:
            with self.assertRaisesRegex(RuntimeError, 'Recording locked'):
                d._launch_app(app)
            with self.assertRaisesRegex(RuntimeError, 'Recording locked'):
                d._grant_focus(app)
            popen.assert_not_called()

    def test_home_hides_network_children_but_keeps_them_in_registered_ipc_list(self):
        d = navigation.NavigationTests().daemon()
        for identifier in ('whisplay-network', 'whisplay-wifi', 'whisplay-bluetooth', 'whisplay-ai-chatbot'):
            d.apps[identifier] = AppRecord(identifier, identifier)
        self.assertEqual(d._home_apps()[0].app_id, 'whisplay-ai-chatbot')
        self.assertNotIn('whisplay-wifi', [app.app_id for app in d._home_apps()])
        self.assertIn('whisplay-wifi', [app.app_id for app in d._app_list()])

    def test_screen_wake_restores_commanded_brightness_and_does_not_select_item(self):
        import test_system_app
        d = test_system_app.LockScreenStateTests().make_daemon()
        d._brightness = 40
        d._lock_screen()
        d._on_button_released()
        self.assertEqual(d.board.backlight[-1], 40)
        self.assertIsNone(d.foreground_app_id)

    def test_declined_worker_start_never_leaves_menu_busy(self):
        app = WifiControl(*args(spawn=lambda name, work: False))
        app.refresh_async()
        self.assertFalse(app.state.busy)
        self.assertIn('retry', app.state.status)

    def test_recording_setting_missing_preserves_original_but_invalid_locks(self):
        for content, enabled in [(None, True), ('not JSON', False), ('[]', False),
                                 ('{"glados_recording_enabled":"true"}', False),
                                 ('{"glados_recording_enabled":false}', False),
                                 ('{"glados_recording_enabled":true}', True)]:
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                if content is not None:
                    (Path(directory) / 'control-center.json').write_text(content)
                with patch('whisplay_daemon.WhisplayBoard'), patch('whisplay_daemon.PiSugarManager'), patch(
                        'whisplay_daemon.FallbackDesktopRenderer'), patch('whisplay_daemon.StatusPoller'), patch.object(
                        WhisplayDaemon, '_load_apps'), patch.object(WhisplayDaemon, '_register_internal_apps'):
                    d = WhisplayDaemon(str(Path(directory) / 'sock'), directory, str(Path(directory) / 'settings.json'))
                self.assertEqual(d._recording_enabled, enabled)

    def test_background_pairing_cannot_open_or_accept_a_confirmation(self):
        app = BluetoothControl(*args())
        app._pairing_agent = Mock()
        app._update_pairing_state({'active': True, 'requires_confirmation': True, 'detail': '123456'})
        self.assertIsNone(app.confirmation.pending)
        app._pairing_agent.cancel.assert_called_once()
        app.activate()
        app.pairing_address = 'AA:BB:CC:DD:EE:FF'
        app._update_pairing_state({'active': True, 'requires_confirmation': True, 'detail': '123456'})
        self.assertEqual(app.confirmation.selected, 0)
        app.handle_button(True)
        app._pairing_agent.confirm.assert_not_called()
        self.assertEqual(app._pairing_agent.cancel.call_count, 2)

    def test_stopping_app_never_covers_home_controls_with_running_modal(self):
        d = navigation.NavigationTests().daemon()
        d.foreground_app_id = None
        d.apps['chat'].process = Mock(poll=Mock(return_value=None))
        d.desktop = Mock()
        d.status_poller = SimpleNamespace(wifi_signal_level=None, battery_level=None)
        WhisplayDaemon._render_desktop(d)
        self.assertIsNone(d.desktop.render.call_args.args[3])


if __name__ == '__main__':
    unittest.main()
