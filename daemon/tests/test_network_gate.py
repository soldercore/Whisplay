"""Recovery is not accepted: all disruptive routes fail before any side effect."""
import contextlib
import io
import json
import sys
import unittest
from unittest.mock import Mock, patch

import test_voice_control
import control_action as helper
from internal_apps.control_client import control, ControlBlocked


class NetworkGateTests(unittest.TestCase):
    def test_root_and_unprivileged_routes_cannot_override_disabled_wifi(self):
        for args in (['wifi-radio', 'off'], ['wifi-connect', '85c22a71-3adf-4d79-a1a9-6b974ed49a61'],
                     ['wifi-disconnect', 'wlan0'], ['wifi-join']):
            with self.subTest(args=args), patch.object(helper, 'nm') as nm, patch.object(helper, 'bus') as bus:
                with self.assertRaisesRegex(helper.ControlBlocked, 'wifi_changes_disabled'):
                    helper.dispatch(args, Mock(side_effect=AssertionError('No password read')))
                run = Mock()
                with self.assertRaisesRegex(ControlBlocked, 'unavailable'): control(run, *args)
                nm.assert_not_called(); bus.assert_not_called(); run.assert_not_called()

    def test_voice_capabilities_and_actions_truthfully_reject_before_handoff(self):
        api, d = test_voice_control.VoiceControlTests().setup_api()
        api.helper_available = lambda: True
        with patch('control_api.shutil.which', return_value='/usr/bin/test'):
            caps = api.capabilities()['actions']
            self.assertFalse(caps['wifi']['disable_supported'])
            self.assertFalse(caps['wifi_join']['supported']); self.assertFalse(caps['wifi_profile']['supported'])
            for payload in ({'action': 'wifi', 'enabled': False}, {'action': 'wifi_join', 'network': 'Lab'},
                            {'action': 'wifi_profile', 'operation': 'disconnect'}):
                with self.assertRaisesRegex(RuntimeError, 'unavailable'): api.execute(payload)
        self.assertIsNone(api.pending)
        self.assertEqual(d.foreground_app_id, 'whisplay-ai-chatbot')

    def test_physical_wifi_route_is_also_blocked_before_runner(self):
        _, d = test_voice_control.VoiceControlTests().setup_api()
        wifi = d.internal_apps.wifi; wifi._run_command = Mock()
        for args in (('wifi-radio', 'off'), ('wifi-connect', 'not-used'), ('wifi-disconnect', 'wlan0')):
            with self.assertRaises(ControlBlocked): wifi.apply_change(*args)
        wifi._run_command.assert_not_called()

    def test_failure_preserves_finite_automatic_timer_and_never_claims_recovery(self):
        state = {'checkpoint': False}
        def bus(method, *args):
            if method == 'GetDeviceByIpIface': return 'o "/org/freedesktop/NetworkManager/Devices/2"'
            if method == 'CheckpointCreate':
                self.assertEqual(args[-2:], ('120', '0')); state['checkpoint'] = True
                return 'o "/org/freedesktop/NetworkManager/Checkpoint/1"'
            self.fail('Failed operation must neither destroy nor explicitly roll back its checkpoint')
        with patch.object(helper, 'guard_ssh'), patch.object(helper, 'nm', return_value='wlan0:wifi'), \
             patch.object(helper, 'bus', side_effect=bus):
            with self.assertRaisesRegex(helper.WifiRecoveryPending, 'restoration unverified'):
                with helper.wifi_checkpoint(): raise TimeoutError('verification failed')
        self.assertTrue(state['checkpoint'])
        # A timer is not evidence of restoration. Failed restoration cannot enable
        # a deployment action; the hard gate remains false regardless of outcome.
        self.assertFalse(helper.DISRUPTIVE_WIFI_ENABLED)

    def test_radio_on_and_scan_remain_available_and_power_has_no_unrestricted_command(self):
        with patch.object(helper, 'nm', side_effect=['', 'enabled']) as nm:
            helper.dispatch(['wifi-radio', 'on'], Mock())
            self.assertEqual(nm.call_args_list[0].args, ('radio', 'wifi', 'on'))
        with patch.object(helper, 'nm') as nm:
            helper.dispatch(['wifi-scan'], Mock()); nm.assert_called_once_with('device', 'wifi', 'rescan')

    def test_ambiguous_checkpoint_commit_does_not_claim_a_surviving_timer(self):
        def bus(method, *args):
            if method == 'CheckpointDestroy': raise TimeoutError('reply lost after possible commit')
            return ('o "/org/freedesktop/NetworkManager/Devices/2"' if method == 'GetDeviceByIpIface'
                    else 'o "/org/freedesktop/NetworkManager/Checkpoint/1"')
        with patch.object(helper, 'guard_ssh'), patch.object(helper, 'nm', return_value='wlan0:wifi'), \
             patch.object(helper, 'bus', side_effect=bus):
            with self.assertRaisesRegex(helper.WifiRecoveryPending, 'recovery state unknown'):
                with helper.wifi_checkpoint(): pass

    def test_helper_reports_disabled_without_sensitive_details_or_root_commands(self):
        with patch.object(helper.os, 'geteuid', return_value=0, create=True), \
             patch.object(sys, 'argv', ['helper', 'wifi-radio', 'off']), \
             patch.object(helper, 'operation_lock', side_effect=contextlib.nullcontext), \
             patch.object(helper, 'run') as run, contextlib.redirect_stderr(io.StringIO()) as output:
            self.assertEqual(helper.main(), 4)
            self.assertEqual(json.loads(output.getvalue()), {'error': 'wifi_changes_disabled'})
            run.assert_not_called()


if __name__ == '__main__': unittest.main()
