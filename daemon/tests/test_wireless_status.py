import os
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from radio_status import RadioStatus, unknown_status
from internal_apps.wifi_control import WifiControl
from internal_apps.bluetooth_control import BluetoothControl
from internal_apps.bluetooth_app import BluetoothDevice
from internal_apps.control_client import ControlBlocked
import test_voice_control


class WirelessStatusTests(unittest.TestCase):
    def test_wifi_already_enabled_reports_actual_state_without_missing_helper(self):
        api, d = test_voice_control.VoiceControlTests().setup_api()
        api.helper_available = Mock(return_value=False)
        wifi = d.internal_apps.wifi
        wifi.indicator_status = Mock(return_value={'enabled':True, 'connected':True, 'signal':73})
        wifi.apply_change = Mock()
        result = api.execute({'action':'wifi','enabled':True})
        self.assertEqual((result['status'], result['enabled'], result['changed']), ('completed',True,False))
        wifi.apply_change.assert_not_called()
        api.helper_available.assert_not_called()
        wifi.indicator_status.return_value = {'enabled':False, 'connected':False, 'signal':None}
        with self.assertRaises(RuntimeError):
            api.execute({'action':'wifi','enabled':True})
        wifi.apply_change.assert_not_called()

    def test_indicator_reads_cached_nm_state_only_no_scan_or_credentials(self):
        wifi = WifiControl.__new__(WifiControl)
        wifi._read = Mock(side_effect=['enabled', '*:72\n:40'])
        self.assertEqual(wifi.indicator_status(), {'enabled': True, 'connected': True, 'signal': 72})
        self.assertIn('--rescan', wifi._read.call_args.args[0])
        self.assertEqual(wifi._read.call_args.args[0][-1], 'no')
        wifi._read = Mock(side_effect=['enabled', ':40'])
        self.assertEqual(wifi.indicator_status(), {'enabled': True, 'connected': False, 'signal': None})
        wifi._read = Mock(return_value='disabled')
        self.assertEqual(wifi.indicator_status(), {'enabled': False, 'connected': False, 'signal': None})
        self.assertEqual(wifi._read.call_count, 1)

    def test_sample_unknown_is_not_disabled_and_repeated_reads_do_not_publish_changes(self):
        wifi = SimpleNamespace(indicator_status=Mock(return_value={'enabled': True, 'connected': True, 'signal': 72}))
        bt = SimpleNamespace(refresh=Mock(), powered=False)
        status = RadioStatus(wifi, bt)
        status.sample()
        self.assertTrue(status.updated.is_set())
        snapshot = status.snapshot()
        snapshot['wifi']['enabled'] = False
        self.assertTrue(status.snapshot()['wifi']['enabled'])
        status.updated.clear(); status.sample()
        self.assertFalse(status.updated.is_set())
        wifi.indicator_status.side_effect = RuntimeError('Unavailable')
        bt.refresh.side_effect = RuntimeError('Unavailable')
        status.sample()
        self.assertEqual(status.snapshot(), unknown_status())

    def test_idle_bluetooth_off_is_immediate_and_checked_without_privilege(self):
        api, d = test_voice_control.VoiceControlTests().supported_api()
        bt = d.internal_apps.bluetooth
        bt.details_complete, bt.powered = True, True
        bt.state.devices = []
        bt.apply_change = Mock(side_effect=lambda *a, **k: setattr(bt, 'powered', k['enabled']))
        result = api.execute({'action': 'bluetooth', 'enabled': False})
        self.assertEqual((result['status'], result['enabled']), ('completed', False))
        self.assertIsNone(api.pending)
        api.check_ssh.assert_not_called()
        self.assertFalse(api.execute({'action': 'bluetooth', 'enabled': False})['changed'])
        bt.powered = True; bt.apply_change = Mock()
        with self.assertRaisesRegex(RuntimeError, 'not confirmed'):
            api.execute({'action': 'bluetooth', 'enabled': False})

    def test_connected_bluetooth_cannot_bypass_ssh_or_missing_guard(self):
        for payload in ({'action':'bluetooth','enabled':False},
                        {'action':'bluetooth_device','operation':'disconnect','device':'Lab PAN'},
                        {'action':'bluetooth_device','operation':'forget','device':'Lab PAN'}):
            api, d = test_voice_control.VoiceControlTests().supported_api()
            bt = d.internal_apps.bluetooth
            bt.details_complete = True
            bt.state.devices = [BluetoothDevice('AA:BB:CC:DD:EE:FF', 'Lab PAN', 50, True, True)]
            bt.apply_change = Mock()
            api.check_ssh = Mock(side_effect=ControlBlocked('Active SSH session'))
            with self.assertRaises(ControlBlocked):
                api.execute(payload)
            bt.apply_change.assert_not_called()
            self.assertIsNone(api.pending)

    def test_button_backend_rechecks_connected_transport_guard(self):
        api, d = test_voice_control.VoiceControlTests().supported_api()
        bt = d.internal_apps.bluetooth
        bt.details_complete = True
        bt.state.devices = [BluetoothDevice('AA:BB:CC:DD:EE:FF', 'Lab PAN', 50, True, True)]
        bt.checked = Mock()
        for action, address, enabled in [('power', None, False), ('disconnect', 'AA:BB:CC:DD:EE:FF', None), ('remove', 'AA:BB:CC:DD:EE:FF', None)]:
            with patch('internal_apps.bluetooth_control.control', side_effect=ControlBlocked('Active SSH')):
                with self.assertRaises(ControlBlocked):
                    bt.apply_change(action, address, enabled)
            bt.checked.assert_not_called()

    def test_paired_connect_reuses_backend_and_requires_readback(self):
        api, d = test_voice_control.VoiceControlTests().supported_api()
        bt = d.internal_apps.bluetooth
        device = BluetoothDevice('AA:BB:CC:DD:EE:FF', 'Lab headphones', 50, True, False)
        bt.state.devices = [device]
        bt.apply_change = Mock()
        with self.assertRaisesRegex(RuntimeError, 'not confirmed'):
            api.execute({'action':'bluetooth_device','operation':'connect','device':device.name})
        bt.apply_change.side_effect = lambda *a, **k: setattr(device, 'connected', True)
        result = api.execute({'action':'bluetooth_device','operation':'connect','device':device.name})
        self.assertEqual(result['verification'], 'BlueZ_readback')
        self.assertIsNone(api.pending)

    def test_radio_worker_is_event_driven_with_bounded_fallback_and_owned_cleanup(self):
        status = RadioStatus(Mock(), Mock())
        timeouts = []
        def wait(timeout):
            timeouts.append(timeout)
            status.stopped.set()
        status.dirty.wait = wait
        status.sample = Mock()
        status._work()
        self.assertEqual(timeouts, [60])
        status.sample.assert_not_called()
        process = Mock(stdout=Mock())
        process.poll.return_value = None
        status._close_process(process)
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=2)
        process.stdout.close.assert_called_once()

    def test_real_glyphs_distinguish_all_states_and_stay_inside_safe_bar(self):
        from PIL import Image, ImageDraw
        from cyber_ui import theme
        from wireless_icons import draw_wireless
        states = [unknown_status(), {'wifi':{'enabled':False},'bluetooth':{'enabled':False}},
                  {'wifi':{'enabled':True,'connected':False},'bluetooth':{'enabled':True}},
                  {'wifi':{'enabled':True,'connected':True,'signal':20},'bluetooth':{'enabled':True}},
                  {'wifi':{'enabled':True,'connected':True,'signal':90},'bluetooth':{'enabled':True}}]
        pixels = []
        for state in states:
            image = Image.new('RGB', (240, 27))
            x = draw_wireless(ImageDraw.Draw(image), 166, theme.STATUS_CENTER_Y, state, theme)
            self.assertGreaterEqual(x, theme.STATUS_SAFE_LEFT)
            self.assertLess(image.getbbox()[3], theme.DIVIDER_Y)
            pixels.append(image.tobytes())
        self.assertEqual(len(set(pixels)), len(states))

    def test_classic_renderer_survives_missing_cyber_package_with_radio_state(self):
        from cyber_ui.preview import FakeBoard
        from daemon_renderer import DesktopRenderer
        renderer = DesktopRenderer(FakeBoard(), str(Path(__file__).resolve().parents[1]))
        with patch.dict(sys.modules, {'cyber_ui': None}):
            renderer.render([], 0, battery_level=80, wireless_status=unknown_status())


if __name__ == '__main__':
    unittest.main()
