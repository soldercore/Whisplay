import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import control_action
import test_control_navigation as navigation
from internal_apps.services_app import ServicesApp, service_state, UNITS
from internal_apps.system_app import SystemInternalApp
from internal_apps.manager import InternalAppManager
from daemon_models import AppRecord


def args(run=None):
    return (threading.RLock(), Mock(), run or Mock(), lambda name, work: work(), Mock())


class ControlSafetyTests(unittest.TestCase):
    def test_power_cancel_expiry_and_deactivate_never_execute(self):
        run = Mock()
        app = SystemInternalApp(*args(run), Mock())
        app.state.selected_index = 3
        app.handle_button(True)
        self.assertIn('power-on', str(app.view_model()['detail_lines']))
        app.handle_button(True)  # Defaults to Cancel.
        run.assert_not_called()
        app.handle_button(True)
        app.handle_button(False)
        with patch('internal_apps.menu.time.monotonic', return_value=float('inf')):
            app.handle_button(True)
        run.assert_not_called()
        self.assertEqual(app.state.status, 'Confirmation expired')
        app.state.selected_index = 2
        app.handle_button(True)
        app.deactivate()
        self.assertIsNone(app.confirmation.pending)

    def test_command_failure_or_timeout_never_reports_acceptance(self):
        for runner in (Mock(return_value=SimpleNamespace(returncode=1)),
                       Mock(side_effect=subprocess.TimeoutExpired('synthetic', 1))):
            app = SystemInternalApp(*args(runner), Mock())
            app.ask_power('reboot')
            app.handle_button(False)
            app.handle_button(True)
            self.assertNotIn('accepted', app.state.status.lower())
            self.assertFalse(app.state.busy)

    def test_service_states_distinguish_missing_from_stopped_and_failed(self):
        for active, expected in [('active', 'Running'), ('inactive', 'Stopped'),
                                 ('activating', 'Starting'), ('failed', 'Failed')]:
            self.assertEqual(service_state('LoadState=loaded\nActiveState=' + active), expected)
        self.assertEqual(service_state('LoadState=not-found\nActiveState=inactive'), 'Unavailable')
        self.assertEqual(service_state(''), 'Unavailable')

    def services(self, runner):
        return ServicesApp(*args(runner), glados_status=lambda: {'registered': True},
                           launch_glados=Mock(), begin_maintenance=Mock(), end_maintenance=Mock())

    def test_service_status_only_reads_exact_allowlist_and_daemon_is_read_only(self):
        runner = Mock(return_value=SimpleNamespace(returncode=0, stdout='LoadState=loaded\nActiveState=active'))
        app = self.services(runner)
        app.refresh()
        self.assertEqual({c.args[0][-1] for c in runner.call_args_list}, {v[1] for v in UNITS.values()})
        self.assertTrue(all('show' in c.args[0] and 'sudo' not in c.args[0] for c in runner.call_args_list))
        with self.assertRaises(ValueError):
            app.change('daemon', 'restart')
        with self.assertRaises(ValueError):
            app.change('other.service', 'start')
        app.open_service('daemon')
        self.assertEqual(len(app.items()), 2)

    def test_ssh_restart_cancel_then_confirm_reserves_and_releases_maintenance(self):
        runner = Mock(return_value=SimpleNamespace(returncode=0, stdout='LoadState=loaded\nActiveState=active'))
        app = self.services(runner)
        app.ask_service('ssh', 'restart')
        self.assertIn('active SSH', str(app.view_model()['detail_lines']))
        app.handle_button(True)
        runner.assert_not_called()
        app.ask_service('ssh', 'restart')
        app.handle_button(False)
        app.handle_button(True)
        app.begin_maintenance.assert_called_once()
        app.end_maintenance.assert_called_once()
        self.assertIn(['/usr/bin/sudo', '-n', '/usr/lib/whisplay/control-action', 'service', 'restart', 'ssh'],
                      [c.args[0] for c in runner.call_args_list])

    def test_failed_service_action_releases_reservation_and_keeps_failure_visible(self):
        app = self.services(Mock(return_value=SimpleNamespace(returncode=1)))
        app.change('piper', 'restart')
        app.end_maintenance.assert_called_once()
        self.assertIn('failed', app.state.status.lower())
        self.assertFalse(app.state.busy)

    def test_backend_maintenance_blocks_app_launch_and_cannot_start_with_live_app(self):
        d = navigation.NavigationTests().daemon()
        d._maintenance = False
        d.apps['chat'].process = Mock(poll=Mock(return_value=None))
        with self.assertRaisesRegex(RuntimeError, 'Wait for all apps'):
            d._begin_maintenance()
        d.apps['chat'].process = None
        d._begin_maintenance()
        with patch('whisplay_daemon.subprocess.Popen') as popen:
            with self.assertRaisesRegex(RuntimeError, 'maintenance'):
                d._launch_app(AppRecord('new', 'New', launch_command='must-not-run'))
            popen.assert_not_called()
        d._end_maintenance()
        self.assertFalse(d._maintenance)

    def test_privileged_helper_denies_arbitrary_shell_services_and_bad_inputs(self):
        invalid = [[], ['service', 'stop', 'ssh'], ['service', 'restart', 'daemon'],
                   ['service', 'restart', 'ssh.service;reboot'], ['power', 'halt'],
                   ['wifi-radio', '--help'], ['wifi-connect', '../bad'],
                   ['wifi-disconnect', '-wlan0'], ['wifi-disconnect', 'wlan0;id']]
        with patch.object(control_action, 'run') as run:
            for value in invalid:
                with self.subTest(value=value), self.assertRaises((ValueError, RuntimeError)):
                    control_action.dispatch(value, Mock())
            run.assert_not_called()

    def test_privileged_helper_never_accepts_daemon_or_arbitrary_unit(self):
        with patch.object(control_action, 'run', return_value='active') as run:
            control_action.dispatch(['service', 'restart', 'whisper'], Mock())
            self.assertEqual(run.call_args_list[0].args[0], ['/usr/bin/systemctl', 'restart', 'whisplay-whisper.service'])
        with patch.object(control_action, 'nm', side_effect=['', 'disabled']):
            with self.assertRaisesRegex(RuntimeError, 'not confirmed'):
                control_action.dispatch(['wifi-radio', 'on'], Mock())

    @patch.object(control_action, "DISRUPTIVE_WIFI_ENABLED", True)  # Dormant algorithm only.
    def test_new_wifi_credentials_never_appear_in_process_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            real_temporary_directory = tempfile.TemporaryDirectory
            def local_directory(**kwargs):
                return real_temporary_directory(dir=directory)
            with patch.object(control_action.tempfile, 'TemporaryDirectory', side_effect=local_directory), patch.object(control_action, 'nm') as nm, patch.object(control_action, 'guard_ssh'), patch.object(control_action, 'wifi_checkpoint', side_effect=__import__('contextlib').nullcontext):
                control_action.dispatch(['wifi-join'], lambda size: json.dumps({
                    'ssid': 'Synthetic Only', 'password': 'synthetic-password', 'security': 'wpa-psk'}))
                self.assertNotIn('synthetic-password', str(nm.call_args_list))
                self.assertEqual(list(Path(directory).iterdir()), [])
        for payload in [{'ssid': '-evil', 'password': 'password', 'security': 'wpa-psk'},
                        {'ssid': 'Test', 'password': 'bad\nsecret', 'security': 'wpa-psk'},
                        {'ssid': 'Test', 'password': '', 'security': 'enterprise'}]:
            with patch.object(control_action, 'nm') as nm:
                with self.assertRaises(ValueError):
                    control_action.dispatch(['wifi-join'], lambda size: json.dumps(payload))
                nm.assert_not_called()

    def test_real_daemon_button_path_navigates_network_and_returns_home(self):
        d = navigation.NavigationTests().daemon()
        d.internal_apps = InternalAppManager()
        for app in d.internal_apps._apps.values():
            app.refresh_async = Mock()
        d.apps = {app.app_id: app for app in d.internal_apps.builtin_apps()}
        d._render_internal_app = Mock()
        d._launch_app(d.apps['whisplay-network'])
        def press(long):
            d._button_press_started_at = 100 if long else 101
            with patch('whisplay_daemon.time.time', return_value=101):
                d._on_button_released()
        press(False)
        press(True)
        self.assertEqual(d.foreground_app_id, 'whisplay-wifi')
        press(True)
        self.assertEqual(d.foreground_app_id, 'whisplay-network')
        press(True)
        self.assertIsNone(d.foreground_app_id)

    def test_exit_keeps_tracking_owned_descendant_after_shell_exits(self):
        d = navigation.NavigationTests().daemon()
        process = Mock(pid=424242, poll=Mock(return_value=None))
        d.apps['chat'].process = process
        # Fake /proc identities. Never signal a real process in this test.
        with patch('whisplay_daemon.process_group_members', return_value={424242: 10, 424243: 11}, create=True), patch(
                'whisplay_daemon.os.killpg', create=True) as killpg:
            d._request_exit(d.apps['chat'], 'quad_click_exit')
            deadline = d.exit_request['deadline']
            d._advance_app_exits(deadline)
            process.poll.return_value = 0
            d.apps['chat'].process = None  # The actual monitor reaps the launcher.
            with patch('whisplay_daemon.process_group_members', return_value={424243: 11}, create=True):
                d._advance_app_exits(deadline + 2.1)
            self.assertEqual(killpg.call_count, 2)
            self.assertIn('chat', d._app_exits)

    def test_reused_process_group_is_never_signaled_after_old_group_exits(self):
        d = navigation.NavigationTests().daemon()
        process = Mock(pid=424242, poll=Mock(return_value=None))
        d.apps['chat'].process = process
        with patch('whisplay_daemon.process_group_members', return_value={424242: 10}, create=True):
            d._request_exit(d.apps['chat'], 'quad_click_exit')
        process.poll.return_value = 0
        d.apps['chat'].process = None
        with patch('whisplay_daemon.process_group_members', return_value={424242: 99}, create=True), patch(
                'whisplay_daemon.os.killpg', create=True) as killpg:
            d._advance_app_exits(d.exit_request['deadline'])
            killpg.assert_not_called()


if __name__ == '__main__':
    unittest.main()
