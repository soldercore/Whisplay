import os
import subprocess
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import test_control_navigation as navigation
from daemon_models import AppRecord
from internal_apps.manager import InternalAppManager
from control_api import ControlAPI, APP


class VoiceControlTests(unittest.TestCase):
    def setup_api(self):
        d = navigation.NavigationTests().daemon()
        d.internal_apps = InternalAppManager(glados_status=lambda: d._glados_status())
        for app in d.internal_apps._apps.values():
            app.refresh_async = Mock()
        d.apps = {app.app_id: app for app in d.internal_apps.builtin_apps()}
        d.apps[APP] = AppRecord(APP, 'GLaDOS', process=Mock(pid=424242, poll=Mock(return_value=None)))
        d.foreground_app_id = APP
        d._brightness, d._led_rgb, d._recording_enabled = 80, None, True
        d._render_internal_app = Mock()
        d.internal_apps.volume._find_wm8960_card = Mock(return_value='2')
        api = ControlAPI(d, authorize=Mock())
        return api, d

    def test_capabilities_fail_closed_for_uninstalled_helper(self):
        api, d = self.setup_api()
        api.helper_available = lambda: False
        for action in ('wifi','service','reboot','shutdown'):
            self.assertFalse(api.capabilities()['actions'][action]['supported'])
        with self.assertRaises(RuntimeError):api.execute({'action':'reboot'})
        self.assertIsNone(api.pending)

    def test_invalid_inputs_never_reach_existing_operations(self):
        api, d = self.setup_api()
        d.internal_apps.volume.apply_volume = Mock()
        for p in [{'action':'shell','level':10}, {'action':'volume','level':True},
                  {'action':'volume','level':10,'change':1}, {'action':'volume','level':101},
                  {'action':'brightness','level':0}, {'action':'recording','enabled':'false'},
                  {'action':'service','service':'daemon','operation':'restart'},
                  {'action':'volume','level':10,'command':'id'}]:
            with self.subTest(p=p),self.assertRaises((ValueError,RuntimeError)):api.execute(p)
        d.internal_apps.volume.apply_volume.assert_not_called()

    def test_volume_reuses_mixer_operation_and_returns_actual_readback(self):
        api,d=self.setup_api()
        d.internal_apps.volume.refresh=Mock()
        d.internal_apps.volume.state.current_percent=80
        d.internal_apps.volume.apply_volume=Mock(return_value=70)
        r=api.execute({'action':'volume','change':-10})
        d.internal_apps.volume.apply_volume.assert_called_once_with(70)
        self.assertEqual((r['previous'],r['actual'],r['verification']),(80,70,'mixer_readback'))
        d.internal_apps.volume.state.busy=True
        with self.assertRaises(RuntimeError):api.execute({'action':'volume','level':30})

    def test_confirmation_never_executes_before_speech_exit_and_button(self):
        api,d=self.setup_api()
        api.helper_available=lambda:True
        d.internal_apps.wifi.change=Mock()
        with patch('control_api.shutil.which',return_value='/usr/bin/nmcli'):
            r=api.handle('control.execute',{'action':'wifi','enabled':False},None)
        self.assertEqual(r['status'],'awaiting_physical_confirmation')
        api.advance()
        self.assertEqual(d.foreground_app_id,APP)
        d.internal_apps.wifi.change.assert_not_called()
        with patch('whisplay_daemon.process_group_members',return_value={}):
            api.handle('control.present',{'ticket':r['ticket']},None)
        api.advance()
        self.assertEqual(d.foreground_app_id,APP)
        d.apps[APP].process=None
        d.foreground_app_id=None
        d._app_exits.clear()
        api.advance()
        self.assertEqual(d.foreground_app_id,'whisplay-wifi')
        self.assertEqual(d.internal_apps.wifi.confirmation.selected,0)
        d.internal_apps.wifi.handle_button(True)
        d.internal_apps.wifi.change.assert_not_called()
        with self.assertRaises(ValueError):api.handle('control.present',{'ticket':r['ticket']},None)

    def test_pending_ticket_expires_and_cancel_never_changes_settings(self):
        api,d=self.setup_api()
        r=api.execute({'action':'recording','enabled':False})
        api.handle('control.cancel',{'ticket':r['ticket']},None)
        self.assertIsNone(api.pending)
        api.execute({'action':'recording','enabled':False})
        with patch('control_api.time.monotonic',return_value=float('inf')):api.advance()
        self.assertIsNone(api.pending)
        self.assertTrue(d._recording_enabled)

    def test_physical_confirm_executes_captured_request_once(self):
        api,d=self.setup_api()
        api.helper_available=lambda:True
        d.internal_apps.wifi.change=Mock()
        with patch('control_api.shutil.which',return_value='/usr/bin/nmcli'):
            r=api.handle('control.execute',{'action':'wifi','enabled':False},None)
        with patch('whisplay_daemon.process_group_members',return_value={}):
            api.handle('control.present',{'ticket':r['ticket']},None)
        d.apps[APP].process=None
        d.foreground_app_id=None
        d._app_exits.clear()
        api.advance()
        wifi=d.internal_apps.wifi
        wifi.handle_button(False)  # Physical tap selects Confirm.
        wifi.change.assert_not_called()
        wifi.handle_button(True)  # Physical hold commits the captured request.
        wifi.change.assert_called_once_with('wifi-radio','off')
        api.advance()
        self.assertIsNone(wifi.confirmation.pending)
        wifi.change.assert_called_once()

    def test_old_ticket_cannot_stop_a_restarted_glados(self):
        api,d=self.setup_api()
        r=api.execute({'action':'home'})
        d.apps[APP].process=Mock(pid=555555,poll=Mock(return_value=None))
        d._request_exit=Mock()
        with self.assertRaisesRegex(ValueError,'previous GLaDOS process'):
            api.handle('control.present',{'ticket':r['ticket']},None)
        d._request_exit.assert_not_called()
        self.assertIsNone(api.pending)

    def test_helper_probe_timeout_reports_unavailable(self):
        api,d=self.setup_api()
        safe=SimpleNamespace(st_mode=0o100755,st_uid=0)
        with patch('control_api.Path.lstat',return_value=safe),patch('control_api.os.access',return_value=True), \
             patch('control_api.subprocess.run',side_effect=subprocess.TimeoutExpired('sudo',2)):
            self.assertFalse(api.helper_available())

    def test_peer_authorization_rejects_foreign_uid_and_untracked_process(self):
        import struct
        api,d=self.setup_api()
        api.authorize=api._authorize
        connection=Mock()
        connection.getsockopt.return_value=struct.pack('3i',123,os.getuid()+1 if hasattr(os,'getuid') else 1001,1)
        with patch('control_api.os.getuid',return_value=1000,create=True),patch('control_api.socket.SO_PEERCRED',17,create=True):
            with self.assertRaises(PermissionError):api.handle('control.read',{'scope':'apps'},connection)
            connection.getsockopt.return_value=struct.pack('3i',123,1000,1)
            with patch('control_api.os.getpgid',return_value=999,create=True):
                with self.assertRaises(PermissionError):api.handle('control.execute',{'action':'volume','level':10},connection)
            with patch('control_api.os.getpgid',return_value=424242,create=True):
                api._authorize(connection,True)
                api._authorize(connection,False)
                d.foreground_app_id=None
                with self.assertRaises(PermissionError):api._authorize(connection,True)


if __name__=='__main__':unittest.main()
