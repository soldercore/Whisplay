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



    def supported_api(self):
        api, d = self.setup_api()
        api.capabilities = lambda: {'actions': {a: {'supported': True} for a in __import__('control_api').ACTIONS}}
        return api, d

    def finish_handoff(self, api, d, result):
        with patch('whisplay_daemon.process_group_members', return_value={}):
            api.handle('control.present', {'ticket': result['ticket']}, None)
        d.apps[APP].process = None
        d.foreground_app_id = None
        d._app_exits.clear()
        api.advance()

    def test_home_waits_for_owned_cleanup_and_never_requests_pi_power(self):
        api, d = self.setup_api()
        d._lock_screen = Mock()
        d.internal_apps.system.ask_power = Mock()
        result = api.execute({'action': 'home'})
        with patch('whisplay_daemon.process_group_members', return_value={}):
            api.handle('control.present', {'ticket': result['ticket']}, None)
        d.apps[APP].process = None
        d.foreground_app_id = None
        api.advance()
        self.assertIsNotNone(api.pending, 'owned process exit must finish first')
        d._app_exits.clear()
        api.advance()
        self.assertIsNone(api.pending)
        self.assertIsNone(d.foreground_app_id)
        d.internal_apps.system.ask_power.assert_not_called()
        d._lock_screen.assert_not_called()
        self.assertTrue(d._recording_enabled)

    def test_user_brightness_survives_chatbot_updates_and_can_be_raised_again(self):
        from whisplay_daemon import WhisplayDaemon
        api, d = self.supported_api()
        d.board.set_backlight = Mock()
        d.internal_apps.display.set_brightness = d._set_user_brightness
        result = api.execute({'action':'brightness','change':-10})
        self.assertEqual(result['actual'],70)
        d._set_brightness(100)  # Existing GLaDOS thinking/answer updates.
        self.assertEqual(d._brightness,70)
        d._set_brightness(0)
        self.assertEqual(d._brightness,0)
        d._set_brightness(100)
        self.assertEqual(d._brightness,70)
        d._set_user_brightness(90)
        self.assertEqual(d._brightness,90)
        self.assertEqual(api.read('display')['brightness_limit_percent'],90)

    def test_mute_and_restore_reuse_actual_audio_state(self):
        api, d = self.supported_api()
        app = d.internal_apps.volume
        current = [73]
        def refresh():
            app.state.current_percent = current[0]
            if current[0]: app.restore_volume = current[0]
        def apply(target):
            current[0] = target
            refresh()
            return target
        app.refresh = Mock(side_effect=refresh)
        app.apply_volume = Mock(side_effect=apply)
        self.assertTrue(api.execute({'action':'mute','enabled':True})['enabled'])
        self.assertEqual(current[0],0)
        self.assertFalse(api.execute({'action':'mute','enabled':False})['enabled'])
        self.assertEqual(current[0],73)
        self.assertEqual([c.args for c in app.apply_volume.call_args_list],[(0,),(73,)])
        self.assertEqual(d.foreground_app_id,APP)
        self.assertIsNone(api.pending)

    def test_radio_enable_stays_in_glados_and_requires_actual_readback(self):
        for action in ('wifi','bluetooth'):
            with self.subTest(action=action):
                api,d=self.supported_api()
                target=getattr(d.internal_apps,action)
                attr='radio' if action=='wifi' else 'powered'
                setattr(target,attr,False)
                target.apply_change=Mock(side_effect=lambda *a,**k:setattr(target,attr,True))
                self.assertTrue(api.execute({'action':action,'enabled':True})['enabled'])
                self.assertEqual(d.foreground_app_id,APP)
                self.assertIsNone(api.pending)
                setattr(target,attr,False)
                target.apply_change=Mock()
                with self.assertRaisesRegex(RuntimeError,'not confirmed'):
                    api.execute({'action':action,'enabled':True})
                target.state.busy=True
                with self.assertRaisesRegex(RuntimeError,'in progress'):
                    api.execute({'action':action,'enabled':True})

    def test_bluetooth_disconnect_captures_discovered_target_and_cancel_is_first(self):
        from internal_apps.bluetooth_app import BluetoothDevice
        api,d=self.supported_api()
        bt=d.internal_apps.bluetooth
        bt.refresh=Mock()
        bt.change=Mock()
        address='AA:BB:CC:DD:EE:FF'
        bt.state.devices=[BluetoothDevice(address,'Lab headphones',None,True,True,False)]
        result=api.execute({'action':'bluetooth_device','operation':'disconnect','device':'Lab headphones'})
        bt.state.devices=[]  # UI refresh must not retarget the request.
        self.finish_handoff(api,d,result)
        self.assertEqual(bt.confirmation.selected,0)
        bt.handle_button(True)
        bt.change.assert_not_called()
        self.assertIsNone(bt.confirmation.pending)

    def test_bluetooth_pair_requires_button_and_ambiguous_targets_fail_closed(self):
        from internal_apps.bluetooth_app import BluetoothDevice
        api,d=self.supported_api()
        bt=d.internal_apps.bluetooth
        bt.refresh=Mock()
        bt.change=Mock()
        a='AA:BB:CC:DD:EE:FF'
        bt.state.devices=[BluetoothDevice(a,'Lab speaker',None,False,False,False)]
        result=api.execute({'action':'bluetooth_device','operation':'pair','device':'Lab speaker'})
        bt.change.assert_not_called()
        self.finish_handoff(api,d,result)
        bt.handle_button(False)
        bt.change.assert_not_called()
        bt.handle_button(True)
        bt.change.assert_called_once_with('pair',a)
        api,d=self.supported_api();bt=d.internal_apps.bluetooth;bt.refresh=Mock()
        bt.state.devices=[BluetoothDevice(a,'Same',None,False,False,False),BluetoothDevice('AA:BB:CC:DD:EE:00','Same',None,False,False,False)]
        for name in ('Same','Unknown','AA:BB;id'):
            with self.assertRaises(ValueError):
                api.execute({'action':'bluetooth_device','operation':'connect','device':name})
        self.assertIsNone(api.pending)

    def test_wifi_join_uses_snapshot_and_local_masked_input_never_voice_password(self):
        from internal_apps.wifi_app import WifiNetwork
        api,d=self.supported_api();wifi=d.internal_apps.wifi
        wifi.refresh=Mock();wifi.change=Mock()
        wifi.state.networks=[WifiNetwork('Synthetic Lab',80,'WPA2')]
        result=api.execute({'action':'wifi_join','network':'Synthetic Lab'})
        wifi.state.networks=[]
        self.finish_handoff(api,d,result)
        self.assertEqual(wifi.state.mode,'input')
        self.assertEqual(wifi.key_index,0,'Cancel password entry is first')
        self.assertEqual(wifi.state.password_buffer,'')
        wifi.change.assert_not_called()
        wifi.handle_button(True)
        wifi.change.assert_not_called()
        self.assertNotEqual(wifi.state.mode,'input')

    def test_wifi_profile_disconnect_captured_before_confirmation(self):
        api,d=self.supported_api();wifi=d.internal_apps.wifi
        wifi.refresh=Mock();wifi.change=Mock();wifi.device='wlan0'
        result=api.execute({'action':'wifi_profile','operation':'disconnect'})
        self.finish_handoff(api,d,result)
        wifi.device='wlan999'
        self.assertEqual(wifi.confirmation.selected,0)
        wifi.handle_button(False);wifi.handle_button(True)
        wifi.change.assert_called_once_with('wifi-disconnect','wlan0')

    def test_new_operation_parameters_reject_credentials_shells_and_coercion(self):
        api,d=self.supported_api()
        for p in [{'action':'mute','enabled':1},{'action':'wifi_join','network':'Lab','password':'DoNotLogThis'},
                  {'action':'bluetooth_device','device':'Lab','operation':'trust'},
                  {'action':'wifi_profile','operation':'disconnect','profile':'ignored'},
                  {'action':'wifi_scan','command':'id'},{'action':'bluetooth_scan','enabled':True}]:
            with self.subTest(action=p['action']),self.assertRaises(ValueError):api.execute(p)
        self.assertIsNone(api.pending)

    def test_read_scopes_and_scans_reuse_existing_operations(self):
        api,d=self.supported_api();wifi=d.internal_apps.wifi;bt=d.internal_apps.bluetooth
        wifi.refresh=Mock();wifi.scan=Mock();wifi.state.networks=[];wifi.saved=[]
        bt.refresh=Mock();bt.apply_change=Mock();bt.state.devices=[]
        self.assertIn('wifi',api.read('wifi'))
        bt.refresh.assert_not_called()
        self.assertIn('bluetooth',api.read('bluetooth'))
        self.assertEqual(wifi.refresh.call_count,1)
        self.assertEqual(api.execute({'action':'wifi_scan'})['status'],'completed')
        wifi.scan.assert_called_once_with()
        self.assertEqual(api.execute({'action':'bluetooth_scan'})['status'],'completed')
        bt.apply_change.assert_called_once_with('scan')

    def test_partial_bluetooth_read_does_not_invent_pairing_details(self):
        api,d=self.supported_api();bt=d.internal_apps.bluetooth
        def checked(*args,**kwargs):
            if args[0]=='show':return 'Powered: yes'
            if args[0]=='devices':return 'Device AA:BB:CC:DD:EE:FF Synthetic'
            raise RuntimeError('no info')
        bt.checked=Mock(side_effect=checked)
        bt.refresh(budget_seconds=8)
        self.assertTrue(bt.powered)
        self.assertFalse(bt.details_complete)
        self.assertEqual(bt.state.devices,[])

    def test_already_enabled_recording_never_exits_or_starts_capture(self):
        api,d=self.supported_api()
        r=api.execute({'action':'recording','enabled':True})
        self.assertEqual(r['status'],'completed')
        self.assertFalse(r['changed'])
        self.assertEqual(d.foreground_app_id,APP)
        self.assertIsNone(api.pending)

if __name__=='__main__':unittest.main()
