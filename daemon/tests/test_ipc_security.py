"""Kernel peer identity and negative IPC contracts; never launch a real command."""
import json
import os
import socket
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_control_navigation as navigation
from daemon_models import AppRecord
from daemon_events import EventBroadcaster
from whisplay_daemon import WhisplayDaemon


class IPCSecurityTests(unittest.TestCase):
    def setUp(self):
        self.d = navigation.NavigationTests().daemon()
        self.d.apps['chat'].process = Mock(pid=3210, poll=Mock(return_value=None))
        self.d.apps['chat'].session_token = 'private-session'
        self.d.apps['chat'].launch_command = 'bash /opt/chat/run.sh'
        self.d.apps['chat'].persist = True
        self.d._save_app = Mock()
        self.d.autostart_app_id = ''
        self.d._launch_app = Mock()
        self.d._grant_focus = Mock()
        self.d._allocate_framebuffer = Mock()
        self.peer = Mock()
        self.peer.getsockopt.return_value = struct.pack('3i', 3211, 1000, 29)
        self.uid = patch('os.getuid', return_value=1000, create=True)
        self.group = patch('os.getpgid', return_value=3210, create=True)
        self.uid.start(); self.group.start()
        self.addCleanup(self.uid.stop); self.addCleanup(self.group.stop)
        peercred = patch('socket.SO_PEERCRED', 17, create=True)
        peercred.start(); self.addCleanup(peercred.stop)

    def request(self, command, payload=None):
        return self.d.handle_command({'version': 1, 'cmd': command, 'payload': payload or {}}, self.peer)

    def test_foreign_uid_denied_for_every_supported_command_before_effects(self):
        self.peer.getsockopt.return_value = struct.pack('3i', 999, 1001, 29)
        for command in ('health.ping', 'app.list', 'button.get_state', 'app.register', 'app.launch',
                        'app.autostart.set', 'app.focus.acquire', 'app.focus.release', 'framebuffer.acquire',
                        'app.exit.request', 'backlight.set', 'led.set', 'led.fade', 'events.subscribe',
                        'control.read', 'control.execute', 'control.present', 'control.cancel'):
            with self.subTest(command=command), self.assertRaises(PermissionError):
                self.request(command, {'app_id': 'chat', 'session_token': 'private-session',
                                       'launch_command': 'sudo malicious', 'action': 'volume', 'level': 10})
        self.d._save_app.assert_not_called(); self.d._launch_app.assert_not_called()
        self.d._grant_focus.assert_not_called()

    def test_missing_or_unreadable_peer_credentials_fail_closed(self):
        with self.assertRaises(PermissionError):
            self.d.handle_command({'cmd': 'app.launch', 'payload': {'app_id': 'chat'}}, None)
        self.peer.getsockopt.side_effect = OSError('not a Unix peer')
        with self.assertRaises(PermissionError): self.request('app.register', {'app_id': 'evil'})

    def test_claimed_app_or_stolen_token_cannot_impersonate_another_process_group(self):
        self.d.apps['other'] = AppRecord('other', 'Other', process=Mock(pid=555, poll=Mock(return_value=None)),
                                         session_token='stolen')
        for command in ('app.focus.acquire', 'app.focus.release', 'framebuffer.acquire', 'events.subscribe', 'app.exit.request'):
            with self.subTest(command=command), self.assertRaises(PermissionError):
                self.request(command, {'app_id': 'other', 'session_token': 'stolen'})
        self.d._grant_focus.assert_not_called()

    def test_tracked_app_cannot_register_new_app_change_launch_or_invoke_admin_lifecycle(self):
        for command, payload in [('app.register', {'app_id': 'evil', 'launch_command': 'sudo malicious'}),
                                 ('app.register', {'app_id': 'chat', 'launch_command': 'sudo malicious'}),
                                 ('app.register', {'app_id': 'chat', 'env': {'LD_PRELOAD': '/tmp/evil'}}),
                                 ('app.register', {'app_id': 'chat', 'persist': False}),
                                 ('app.autostart.set', {'app_id': 'chat'}),
                                 ('app.launch', {'app_id': 'whisplay-system'})]:
            with self.subTest(command=command, payload=payload), self.assertRaises(PermissionError):
                self.request(command, payload)
        self.d._save_app.assert_not_called(); self.d._launch_app.assert_not_called()
        self.assertNotIn('evil', self.d.apps)

    def test_legitimate_runtime_registration_and_focus_are_preserved(self):
        self.request('app.register', {'app_id': 'chat', 'display_name': 'Chat', 'persist': True})
        self.request('app.focus.acquire', {'app_id': 'chat'})
        self.d._grant_focus.assert_called_once_with(self.d.apps['chat'])
        self.assertEqual(self.d.apps['chat'].launch_command, 'bash /opt/chat/run.sh')

    def test_empty_or_expired_session_token_never_authorizes_framebuffer_or_release(self):
        self.d.apps['chat'].session_token = None
        for command in ('framebuffer.acquire', 'app.focus.release'):
            with self.subTest(command=command), self.assertRaises(PermissionError):
                self.request(command, {'app_id': 'chat', 'session_token': ''})

    def test_hardware_updates_require_the_current_foreground_app(self):
        self.d._set_brightness = Mock()
        self.request('backlight.set', {'brightness': 70})
        self.d._set_brightness.assert_called_once_with(70)
        self.d.foreground_app_id = 'whisplay-system'
        with self.assertRaises(PermissionError): self.request('backlight.set', {'brightness': 70})

    def test_only_explicit_owner_admin_can_register_and_launch(self):
        with patch('os.getpgid', return_value=9000, create=True):
            self.request('app.register', {'app_id': 'new-app', 'launch_command': 'bash /opt/app/run.sh'})
            self.d.foreground_app_id = None
            self.request('app.launch', {'app_id': 'new-app'})
        self.d._launch_app.assert_called_once_with(self.d.apps['new-app'])

    def test_tokens_are_not_broadcast_to_global_or_stale_subscribers(self):
        self.d.event_broadcaster = EventBroadcaster()
        subscriber = Mock(); self.d.event_broadcaster.add(subscriber, None)
        self.d._button_press_started_at = 0
        WhisplayDaemon._grant_focus(self.d, self.d.apps['chat'])
        messages = ''.join(c.args[0].decode() for c in subscriber.sendall.call_args_list)
        self.assertNotIn(self.d.apps['chat'].session_token, messages)

    @unittest.skipUnless(hasattr(socket, 'SO_PEERCRED'), 'Linux kernel credentials')
    def test_actual_unix_peer_credentials_accept_owner_and_reject_other_uid(self):
        left, right = socket.socketpair()
        try:
            self.d.handle_command({'cmd': 'app.list'}, left)
            with patch('os.getuid', return_value=1001):
                with self.assertRaises(PermissionError): self.d.handle_command({'cmd': 'app.list'}, left)
        finally:
            left.close(); right.close()


class LaunchSecurityTests(unittest.TestCase):
    @unittest.skipUnless(hasattr(socket, 'SO_PEERCRED'), 'Linux peer/process lifecycle')
    def test_real_owned_process_can_register_acquire_update_and_release_home(self):
        d = navigation.NavigationTests().daemon()
        d.foreground_app_id = None; d._allocate_framebuffer = Mock()
        d._save_app = Mock(); d._set_brightness = Mock()
        d._button_press_started_at = 0
        # A fixed, unprivileged test client in the same kind of new process group
        # used for the actual launcher. No GPIO, microphone, shell or sudo.
        code = '''
import json,socket,sys
sys.stdin.readline()
def call(cmd,payload):
 with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
  s.connect(sys.argv[1]);s.sendall((json.dumps(dict(cmd=cmd,payload=payload))+'\\n').encode())
  return json.loads(s.makefile().readline())
assert call('app.register',dict(app_id='chat',display_name='Chat',persist=True))['ok']
token=call('app.focus.acquire',dict(app_id='chat'))['payload']['session_token']
assert call('framebuffer.acquire',dict(app_id='chat',session_token=token))['ok']
assert call('backlight.set',dict(brightness=70))['ok']
assert call('app.focus.release',dict(app_id='chat',session_token=token))['ok']
assert not call('framebuffer.acquire',dict(app_id='chat',session_token=token))['ok']
print('owned lifecycle passed')
'''
        with tempfile.TemporaryDirectory() as directory, socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            path = str(Path(directory) / 'test.sock'); server.bind(path); server.listen(2); server.settimeout(5)
            process = subprocess.Popen([sys.executable, '-c', code, path], start_new_session=True,
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            d.apps['chat'] = AppRecord('chat', 'Chat', process=process, persist=True)
            try:
                process.stdin.write('ready\n'); process.stdin.flush()
                for _ in range(6):
                    conn, _ = server.accept()
                    with conn:
                        conn.settimeout(5)
                        request = json.loads(conn.makefile().readline())
                        try: response, _ = d.handle_command(request, conn)
                        except PermissionError: response = {'ok': False}
                        conn.sendall((json.dumps(response) + '\n').encode())
                out, err = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, err)
                self.assertEqual(out.strip(), 'owned lifecycle passed')
                self.assertIsNone(d.foreground_app_id); self.assertIsNone(d.apps['chat'].session_token)
                d._set_brightness.assert_called_once_with(70)
            finally:
                if process.poll() is None:
                    process.terminate(); process.communicate(timeout=5)

    @unittest.skipUnless(hasattr(socket, 'SO_PEERCRED'), 'Linux Unix socket permissions')
    def test_socket_is_private_at_bind_and_refuses_existing_non_socket(self):
        with tempfile.TemporaryDirectory() as directory:
            d = navigation.NavigationTests().daemon()
            d.socket_dir = directory; d.socket_path = str(Path(directory) / 'daemon.sock')
            server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            wrapper = Mock(wraps=server)
            def stop_after_bind(*args):
                self.assertEqual(Path(d.socket_path).stat().st_mode & 0o777, 0o600)
                raise RuntimeError('stop before hardware')
            wrapper.listen.side_effect = stop_after_bind
            try:
                with patch('whisplay_daemon.socket.socket', return_value=wrapper):
                    with self.assertRaisesRegex(RuntimeError, 'stop before hardware'): d.start()
            finally: server.close()
            Path(d.socket_path).unlink()
            Path(d.socket_path).write_text('must be preserved')
            with self.assertRaises(PermissionError): d.start()
            self.assertEqual(Path(d.socket_path).read_text(), 'must be preserved')

    def test_legacy_glados_log_redirect_is_translated_without_a_shell(self):
        d = navigation.NavigationTests().daemon(); d.foreground_app_id = None
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'run_chatbot.sh'; script.write_text('test only')
            log = Path(directory) / 'chatbot.log'
            app = AppRecord('chat', 'Chat', cwd=directory, launch_command=f'bash "{script}" >> "{log}" 2>&1')
            with patch('whisplay_daemon.subprocess.Popen') as launch:
                d._launch_app(app)
                self.assertEqual(launch.call_args.args[0], ['bash', str(script)])
                self.assertIs(launch.call_args.kwargs['shell'], False)
            d._close_process_log(app)

    def test_shell_operators_and_eval_are_not_valid_registered_launches(self):
        d = navigation.NavigationTests().daemon(); d.foreground_app_id = None
        for command in ('bash /opt/run.sh; sudo evil', 'bash -c "sudo evil"', 'sh -lc evil',
                        'echo $(id)', 'echo `id`', 'echo hello | sh', 'env bash -c evil'):
            with self.subTest(command=command), patch('whisplay_daemon.subprocess.Popen') as launch:
                with self.assertRaises((ValueError, RuntimeError)):
                    d._launch_app(AppRecord('chat', 'Chat', launch_command=command))
                launch.assert_not_called()


if __name__ == '__main__': unittest.main()
