"""Voice bridge to existing built-ins. No model text becomes a command or path."""
from dataclasses import asdict
import json
import os
import re
from pathlib import Path
import shutil
import stat
import subprocess
import threading
import time
import uuid

from internal_apps.control_client import HELPER, WIFI_DISABLED, control
from internal_apps.wifi_app import WifiNetwork
from ipc_auth import peer_identity, tracked_app

APP = 'whisplay-ai-chatbot'
READS = {'capabilities', 'apps', 'display', 'audio', 'network', 'wifi', 'bluetooth', 'services'}
ACTIONS = {'brightness', 'volume', 'mute', 'home', 'lock', 'recording', 'wifi', 'wifi_scan', 'wifi_profile', 'wifi_join',
           'bluetooth', 'bluetooth_scan', 'bluetooth_device', 'service', 'reboot', 'shutdown'}
SERVICES = {'ssh', 'ollama', 'whisper', 'piper'}
PRIVILEGED_ACTIONS = {'wifi', 'wifi_profile', 'wifi_join', 'service', 'reboot', 'shutdown'}


class ControlAPI:
    def __init__(self, daemon, authorize=None, confirmations=True):
        self.daemon = daemon
        self.authorize = authorize or self._authorize
        self.confirmations = confirmations
        self.pending = None
        self.operations = threading.Lock()

    def _authorize(self, connection, mutation):
        pid = peer_identity(connection)
        if mutation:
            app = tracked_app(self.daemon, pid)
            if not app or app.app_id != APP or self.daemon.foreground_app_id != APP:
                raise PermissionError('Only the tracked foreground GLaDOS process may control the device')

    def helper_available(self):
        try:
            path = Path(HELPER)
            info = path.lstat()
            if not (stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022 and os.access(HELPER, os.X_OK)):
                return False
            for parent in path.parents:
                item = parent.lstat()
                if not stat.S_ISDIR(item.st_mode) or item.st_uid != 0 or item.st_mode & 0o022:
                    return False
            result = subprocess.run(['/usr/bin/sudo', '-n', HELPER, 'capabilities'], timeout=2,
                                    capture_output=True, text=True)
            if result.returncode != 0 or len(result.stdout) > 4096:
                return False
            capability = json.loads(result.stdout)
            return (capability.get('api') == 3 and capability.get('ssh_guard') is True
                    and capability.get('disruptive_wifi') is False and capability.get('wifi_checkpoint_seconds') == 120)
        except (OSError, ValueError, AttributeError, subprocess.SubprocessError):
            return False

    def capabilities(self, *, privileged=True):
        manager = self.daemon.internal_apps
        helper = self.helper_available() if privileged else False
        audio = bool(manager.volume._find_wm8960_card())
        nm = bool(shutil.which('nmcli'))
        bt = bool(shutil.which('bluetoothctl'))
        if bt:
            try:
                bt = 'Controller ' in manager.bluetooth.checked('show', timeout=2)
            except Exception:
                bt = False
        feature = lambda supported, confirmation=False, reason=None: {
            'supported': bool(supported), 'physical_confirmation': confirmation,
            **({'reason': reason} if not supported else {})}
        privileged = lambda condition=True: feature(condition and helper and self.confirmations, True,
            'Fixed privilege helper or local confirmation support unavailable')
        return {'api': 1, 'voice_control_revision': 2, 'push_to_talk': True, 'continuous_capture_added': False,
                'actions': {'brightness': feature(True), 'volume': feature(audio, reason='Supported sound card unavailable'),
                    'mute': feature(audio, reason='Supported sound card unavailable'),
                    'home': feature(self.confirmations, reason='Speech handoff unavailable'),
                    'lock': feature(self.confirmations, reason='Speech handoff unavailable'),
                    'recording': feature(APP in self.daemon.apps and self.confirmations, True, 'GLaDOS not registered / handoff unavailable'),
                    'wifi': {**privileged(nm), 'immediate_enable': True, 'disable_supported': False},
                    'wifi_scan': feature(nm, reason='NetworkManager unavailable'),
                    'wifi_profile': feature(False, reason=WIFI_DISABLED), 'wifi_join': feature(False, reason=WIFI_DISABLED),
                    'bluetooth': {**feature(bt and self.confirmations, True, 'BlueZ / confirmation unavailable'),
                                  'immediate_enable': True, 'immediate_disable_when_idle': True},
                    'bluetooth_scan': feature(bt, reason='BlueZ controller unavailable'),
                    'bluetooth_device': feature(bt and self.confirmations, True, 'BlueZ / confirmation unavailable'),
                    'service': {**privileged(bool(shutil.which('systemctl'))), 'immediate_start': True}, 'reboot': privileged(), 'shutdown': privileged()},
                'readable': ['capabilities', 'apps', 'display'] + (['audio'] if audio else []) +
                    (['network'] if nm or bt else []) + (['wifi'] if nm else []) + (['bluetooth'] if bt else []) +
                    (['services'] if shutil.which('systemctl') else []),
                'notes': ['Recording lock affects GLaDOS only, not other programs or hardware microphone gain.',
                          'Services report systemd/process state, not remote connectivity or backend readiness.',
                          'CPU/RAM/temperature/storage are supplied by the existing getSystemHealth tool.',
                          'Wi-Fi passwords are entered only on the local Network screen, never through voice tools.',
                          'Bluetooth targets must be uniquely discovered; paired reconnection is immediate, pairing retains local authorization.',
                          'Active SSH sessions block disruptive Wi-Fi operations and SSH restart; service start is immediate.',
                          'Wi-Fi enable and scan depend on authorization; disable, join, switch and disconnect stay blocked until recovery is verified.',
                          'Radio authorization is checked by the existing operations; no hardware power-on is promised.']}

    def read(self, scope):
        d, m = self.daemon, self.daemon.internal_apps
        if scope == 'capabilities':
            return self.capabilities()
        if scope == 'apps':
            with d.state_lock:
                return {'apps': d._list_apps_payload()}
        if scope == 'display':
            return {'brightness_percent': d._brightness, 'rgb_command': d._led_rgb,
                    'brightness_limit_percent': getattr(d, '_user_brightness', 100),
                    'screen_locked': d._screen_locked, 'measurement': 'last_commanded_not_sensor'}
        if scope == 'audio':
            m.volume.refresh()
            return {'speaker_percent': m.volume.state.current_percent, 'mic_gain': m.volume.mic,
                    'glados_recording_enabled': d._recording_enabled, 'input_mode': m.volume.ptt,
                    'sound_card': m.volume.state.card, 'hardware_mic_mute': False}
        if scope in ('network', 'wifi', 'bluetooth'):
            result = {}
            for name in (('wifi', 'bluetooth') if scope == 'network' else (scope,)):
                app = getattr(m, name)
                try:
                    if name == 'bluetooth':
                        app.refresh(budget_seconds=8)
                    else:
                        app.refresh()
                    result[name] = ({'enabled': app.radio, 'device': app.device,
                        'connected': [asdict(n) for n in app.state.networks if n.active]} if name == 'wifi' else
                        {'enabled': app.powered, 'devices': [asdict(n) for n in app.state.devices],
                         'details_complete': getattr(app, 'details_complete', True)})
                    if name == 'wifi':
                        result[name]['saved_profiles'] = [{'id': identity, 'name': label} for identity, label in app.saved]
                        result[name]['networks'] = [asdict(n) for n in app.state.networks]
                except Exception:
                    result[name] = {'available': False}
            return result
        if scope == 'services':
            m.services.refresh()
            return {'services': dict(m.services.statuses), 'glados': m.services.glados_state(),
                    'backend_readiness': 'not_tested'}
        raise ValueError('Unsupported read scope')

    def normalize(self, payload):
        if not isinstance(payload, dict) or set(payload) - {'action', 'level', 'change', 'enabled', 'service', 'operation', 'device', 'profile', 'network'}:
            raise ValueError('Unsupported action parameters')
        p = dict(payload)
        action = p.get('action')
        if action not in ACTIONS:
            raise ValueError('Unsupported action')
        permitted = {'action'}
        if action in ('brightness', 'volume'):
            if ('level' in p) == ('change' in p):
                raise ValueError('Supply exactly one level or change')
            key = 'level' if 'level' in p else 'change'
            lower = 20 if action == 'brightness' and key == 'level' else 0 if key == 'level' else -20
            upper = 100 if key == 'level' else 20
            if type(p[key]) is not int or not lower <= p[key] <= upper:
                raise ValueError('Invalid level/change')
            permitted.add(key)
        elif action in ('mute', 'recording', 'wifi', 'bluetooth'):
            if type(p.get('enabled')) is not bool:
                raise ValueError('Boolean enabled required')
            permitted.add('enabled')
        elif action == 'service':
            if p.get('service') not in SERVICES or p.get('operation') not in ('start', 'restart'):
                raise ValueError('Unsupported service operation')
            permitted.update(('service', 'operation'))
        elif action == 'bluetooth_device':
            if p.get('operation') not in ('connect', 'disconnect', 'pair', 'forget'):
                raise ValueError('Unsupported Bluetooth device operation')
            permitted.update(('operation', 'device'))
        elif action == 'wifi_profile':
            if p.get('operation') not in ('connect', 'disconnect'):
                raise ValueError('Unsupported Wi-Fi profile operation')
            permitted.add('operation')
            if p['operation'] == 'connect':
                permitted.add('profile')
        elif action == 'wifi_join':
            permitted.add('network')
        for key in ('device', 'profile', 'network'):
            if key in permitted and (not isinstance(p.get(key), str) or not 1 <= len(p[key]) <= 128
                                     or any(ord(c) < 32 for c in p[key])):
                raise ValueError('Valid discovered target required')
        if set(p) != permitted:
            raise ValueError('Unexpected or missing action parameters')
        if action == 'wifi' and not p['enabled']:
            raise RuntimeError(WIFI_DISABLED)
        m = self.daemon.internal_apps
        if action == 'wifi' and p['enabled'] and m.wifi.indicator_status()['enabled'] is True:
            p['already_enabled'] = True  # Verified read-only no-op needs no privilege grant.
            return p
        feature = self.capabilities(privileged=action in PRIVILEGED_ACTIONS)['actions'][action]
        if not feature['supported']:
            raise RuntimeError(feature.get('reason') or 'Action unavailable')
        m = self.daemon.internal_apps
        if action == 'bluetooth_device':
            m.bluetooth.refresh(budget_seconds=8)
            matches = [n for n in m.bluetooth.state.devices if p['device'].casefold() in (n.address.casefold(), n.name.casefold())]
            if len(matches) != 1 or not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', matches[0].address):
                raise ValueError('Bluetooth target unavailable or ambiguous; read Bluetooth status first')
            p['address'] = matches[0].address
            p['device'] = matches[0].name
        elif action in ('wifi_profile', 'wifi_join'):
            m.wifi.refresh()
            if action == 'wifi_join':
                matches = [n for n in m.wifi.state.networks if n.ssid == p['network']]
                if len(matches) != 1:
                    raise ValueError('Wi-Fi network unavailable or ambiguous; scan first')
                p['network_snapshot'] = asdict(matches[0])
            elif p['operation'] == 'connect':
                matches = [identity for identity, name in m.wifi.saved if p['profile'] in (identity, name)]
                if len(matches) != 1:
                    raise ValueError('Saved Wi-Fi profile unavailable or ambiguous')
                p['profile_id'] = matches[0]
            else:
                if not re.fullmatch(r'[A-Za-z0-9_.-]{1,32}', m.wifi.device):
                    raise ValueError('Wi-Fi device unavailable')
                p['interface'] = m.wifi.device
        return p

    def check_ssh(self):
        control(self.daemon.internal_apps._run_command, 'check-ssh')

    def execute(self, payload):
        p = self.normalize(payload)
        d, m, action = self.daemon, self.daemon.internal_apps, p['action']
        if action == 'wifi' and p.get('already_enabled'):
            return {'status': 'completed', 'action': action, 'enabled': True, 'changed': False,
                    'verification': 'NetworkManager_radio_readback'}
        if action == 'service' and p['operation'] == 'start':
            if m.services.state.busy:
                raise RuntimeError('Service operation already in progress')
            m.services.apply_start(p['service'])
            return {'status': 'completed', 'action': action, 'operation': 'start', 'service': p['service'],
                    'actual': m.services.statuses[p['service']], 'verification': 'systemd_readback'}
        if action == 'mute':
            if m.volume.state.busy:
                raise RuntimeError('Audio operation already in progress')
            actual = m.volume.apply_mute(p['enabled'])
            return {'status': 'completed', 'action': action, 'enabled': actual == 0, 'requested_enabled': p['enabled'],
                    'actual': actual, 'unit': '%', 'verification': 'mixer_readback'}
        if action == 'wifi_scan':
            if m.wifi.state.busy:
                raise RuntimeError('Wi-Fi operation already in progress')
            m.wifi.scan()
            return {'status': 'completed', 'action': action, 'networks': [asdict(n) for n in m.wifi.state.networks]}
        if action == 'bluetooth_scan':
            if m.bluetooth.state.busy:
                raise RuntimeError('Bluetooth operation already in progress')
            m.bluetooth.apply_change('scan')
            return {'status': 'completed', 'action': action, 'devices': [asdict(n) for n in m.bluetooth.state.devices]}
        if action == 'bluetooth':
            target = m.bluetooth
            if target.state.busy:
                raise RuntimeError('Bluetooth operation already in progress')
            target.refresh(budget_seconds=8)
            if target.powered is p['enabled']:
                return {'status': 'completed', 'action': action, 'enabled': target.powered,
                        'changed': False, 'verification': 'radio_readback'}
            if not p['enabled'] and (not getattr(target, 'details_complete', False)
                                    or any(n.connected for n in target.state.devices)):
                self.check_ssh()  # A connected Bluetooth PAN may carry SSH. Missing guard fails closed.
            else:
                target.apply_change('power', enabled=p['enabled'], include_devices=False)
                if target.powered is not p['enabled']:
                    raise RuntimeError('Bluetooth radio change not confirmed by actual status')
                return {'status': 'completed', 'action': action, 'enabled': target.powered,
                        'verification': 'radio_readback'}
        if action == 'bluetooth_device' and p['operation'] == 'connect':
            device = next(n for n in m.bluetooth.state.devices if n.address == p['address'])
            if device.paired:
                m.bluetooth.apply_change('connect', p['address'])
                if not any(n.address == p['address'] and n.connected for n in m.bluetooth.state.devices):
                    raise RuntimeError('Bluetooth connection not confirmed by actual status')
                return {'status': 'completed', 'action': action, 'operation': 'connect',
                        'device': p['device'], 'verification': 'BlueZ_readback'}
        if action == 'bluetooth_device' and p['operation'] in ('disconnect', 'forget'):
            # Neither a different operation name nor removal of a pairing bypasses SSH protection.
            self.check_ssh()
        if action == 'wifi' and p['enabled']:
            target = getattr(m, action)
            if target.state.busy:
                raise RuntimeError('Radio operation already in progress')
            if action == 'wifi':
                target.apply_change('wifi-radio', 'on')
                actual = target.radio
            else:
                target.apply_change('power', enabled=True, include_devices=False)
                actual = target.powered
            if actual is not True:
                raise RuntimeError('Radio enable was not confirmed by actual status')
            return {'status': 'completed', 'action': action, 'enabled': True, 'verification': 'radio_readback'}
        if action == 'recording' and p['enabled'] and d._recording_enabled:
            return {'status': 'completed', 'action': action, 'enabled': True, 'changed': False, 'verification': 'daemon_state'}
        if action == 'wifi_join' and p['network_snapshot']['active']:
            return {'status': 'completed', 'action': action, 'already_connected': True,
                    'network': p['network_snapshot']['ssid'], 'verification': 'NetworkManager_status'}
        if action in ('volume', 'brightness'):
            if action == 'volume':
                if m.volume.state.busy:
                    raise RuntimeError('Audio operation already in progress')
                m.volume.refresh()
                previous = m.volume.state.current_percent
            else:
                previous = d._brightness
            target = p.get('level', previous + p.get('change', 0))
            target = max(20 if action == 'brightness' else 0, min(100, target))
            if action == 'volume':
                actual = m.volume.apply_volume(target)
            else:
                with d.state_lock:
                    m.display.set_brightness(target)
                    actual = d._brightness
            return {'status': 'completed', 'action': action, 'previous': previous, 'actual': actual,
                    'unit': '%', 'verification': 'mixer_readback' if action == 'volume' else 'daemon_commanded'}
        if (action == 'wifi' and not p['enabled'] or action in ('wifi_profile', 'wifi_join')
                or action == 'service' and p['operation'] == 'restart' and p['service'] == 'ssh'):
            self.check_ssh()  # No pointless handoff if it is already unsafe; helper rechecks at execution.
        if self.pending:
            raise RuntimeError('A device handoff is already pending; cancel it before another request')
        app = d.apps.get(APP)
        ticket = uuid.uuid4().hex
        self.pending = {'ticket': ticket, 'params': p, 'expires': time.monotonic()+120,
                        'process': app.process if app else None, 'presented': False}
        return {'status': 'awaiting_physical_confirmation' if action not in ('home', 'lock') else 'awaiting_speech_handoff',
                'action': action, 'ticket': ticket, 'changed': False,
                'requested': p,
                'message': 'No change yet. After speech, GLaDOS stops and the existing local screen is shown.'}

    def handle(self, command, payload, connection):
        mutation = command != 'control.read'
        self.authorize(connection, mutation)
        if not self.operations.acquire(blocking=False):
            raise RuntimeError('Another device operation is in progress')
        try:
            if self.pending and time.monotonic() >= self.pending['expires']:
                self.pending = None
            if command == 'control.read':
                if not isinstance(payload, dict) or set(payload) != {'scope'} or payload['scope'] not in READS:
                    raise ValueError('Unsupported read request')
                return self.read(payload['scope'])
            if command == 'control.execute':
                return self.execute(payload)
            if command not in ('control.present', 'control.cancel') or not isinstance(payload, dict) or set(payload) != {'ticket'}:
                raise ValueError('Unsupported control command')
            pending = self.pending
            if not pending or payload['ticket'] != pending['ticket']:
                raise ValueError('Expired or unknown handoff')
            if self.daemon.apps.get(APP) is None or self.daemon.apps[APP].process is not pending['process']:
                self.pending = None
                raise ValueError('Handoff belongs to a previous GLaDOS process')
            if command == 'control.cancel':
                self.pending = None
                return {'status': 'cancelled', 'changed': False}
            if pending['presented']:
                raise ValueError('Handoff already presented')
            with self.daemon.state_lock:
                pending['presented'] = True
                self.daemon._request_exit(self.daemon.apps[APP], 'voice_handoff')
            return {'status': 'handoff_started', 'changed': False}
        finally:
            self.operations.release()

    def advance(self):
        """Called by the existing monitor only after owned app cleanup completes."""
        if not self.operations.acquire(blocking=False):
            return
        try:
            pending = self.pending
            if not pending:
                return
            d, m = self.daemon, self.daemon.internal_apps
            app = d.apps.get(APP)
            if time.monotonic() >= pending['expires'] or app is None or (app.process and app.process is not pending['process']):
                self.pending = None
                return
            if not pending['presented']:
                if not app.is_running():
                    self.pending = None
                return
            if app.is_running() or APP in d._app_exits:
                return
            self.pending = None
            if d.foreground_app_id is not None:
                return  # Physical navigation wins; never steal focus from a new app.
            p, action = pending['params'], pending['params']['action']
            if action == 'home':
                return
            if action == 'lock':
                d._lock_screen()
                return
            target = {'recording': m.volume, 'wifi': m.wifi, 'wifi_profile': m.wifi, 'wifi_join': m.wifi,
                      'bluetooth': m.bluetooth, 'bluetooth_device': m.bluetooth,
                      'service': m.services, 'reboot': m.system, 'shutdown': m.system}[action]
            # A held PTT gesture/release must never select or accept this dialog.
            # A fresh physical press clears the ignore flag in _on_button_pressed.
            d._button_press_started_at = 0.0
            d._ignore_button_release = True
            d._launch_app(d.apps[target.APP_ID])
            if action in ('reboot', 'shutdown'):
                target.ask_power('reboot' if action == 'reboot' else 'poweroff')
            elif action == 'service':
                target.ask_service(p['service'], p['operation'])
            elif action == 'wifi_join':
                target.select_network(WifiNetwork(**p['network_snapshot']))
            elif action == 'wifi_profile':
                callback = (lambda: target.change('wifi-connect', p['profile_id'])) if p['operation'] == 'connect' else (
                    lambda: target.change('wifi-disconnect', p['interface']))
                target.confirmation.ask(p['operation'].title() + ' Wi-Fi', ['Blocked during active SSH.', 'Recover in Network with button.'], callback)
            elif action == 'bluetooth_device':
                operation = 'remove' if p['operation'] == 'forget' else p['operation']
                target.confirmation.ask(p['operation'].title() + ' Bluetooth', [p['device'][:32], p['address']],
                                        lambda: target.change(operation, p['address']))
            else:
                enabled = p['enabled']
                if action == 'recording':
                    callback = lambda: target.perform(lambda: target._recording(enabled))
                    detail = ['GLaDOS only; not hardware mute.', 'Enable again here in Audio.']
                elif action == 'wifi':
                    callback = lambda: target.change('wifi-radio', 'on' if enabled else 'off')
                    detail = ['Blocked during active SSH.', 'Enable locally in Network.']
                else:
                    callback = lambda: target.change('power', enabled=enabled)
                    detail = ['May disconnect devices.', 'Enable locally in Network.']
                target.confirmation.ask(('Enable ' if enabled else 'Disable ') + action, detail, callback)
            d._render_internal_app()
        finally:
            self.operations.release()
