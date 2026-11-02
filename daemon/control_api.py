"""Voice bridge to existing built-ins. No model text becomes a command or path."""
from dataclasses import asdict
import os
from pathlib import Path
import shutil
import socket
import stat
import struct
import subprocess
import threading
import time
import uuid

from internal_apps.control_client import HELPER

APP = 'whisplay-ai-chatbot'
READS = {'capabilities', 'apps', 'display', 'audio', 'network', 'services'}
ACTIONS = {'brightness', 'volume', 'home', 'lock', 'recording', 'wifi', 'bluetooth', 'service', 'reboot', 'shutdown'}
SERVICES = {'ssh', 'ollama', 'whisper', 'piper'}


class ControlAPI:
    def __init__(self, daemon, authorize=None, confirmations=True):
        self.daemon = daemon
        self.authorize = authorize or self._authorize
        self.confirmations = confirmations
        self.pending = None
        self.operations = threading.Lock()

    def _authorize(self, connection, mutation):
        if connection is None or not hasattr(socket, 'SO_PEERCRED'):
            raise PermissionError('Local Unix peer credentials required')
        pid, uid, _ = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid != os.getuid():
            raise PermissionError('Daemon user required')
        if mutation:
            app = self.daemon.apps.get(APP)
            if not app or not app.is_running() or self.daemon.foreground_app_id != APP or os.getpgid(pid) != app.process.pid:
                raise PermissionError('Only the tracked foreground GLaDOS process may control the device')

    def helper_available(self):
        try:
            info = Path(HELPER).lstat()
            safe = stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022 and os.access(HELPER, os.X_OK)
            return safe and subprocess.run(['/usr/bin/sudo', '-n', '-l', HELPER], timeout=2,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    def capabilities(self):
        manager = self.daemon.internal_apps
        helper = self.helper_available()
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
        return {'api': 1, 'push_to_talk': True, 'continuous_capture_added': False,
                'actions': {'brightness': feature(True), 'volume': feature(audio, reason='Supported sound card unavailable'),
                    'home': feature(self.confirmations, reason='Speech handoff unavailable'),
                    'lock': feature(self.confirmations, reason='Speech handoff unavailable'),
                    'recording': feature(APP in self.daemon.apps and self.confirmations, True, 'GLaDOS not registered / handoff unavailable'),
                    'wifi': privileged(nm), 'bluetooth': feature(bt and self.confirmations, True, 'BlueZ / confirmation unavailable'),
                    'service': privileged(bool(shutil.which('systemctl'))), 'reboot': privileged(), 'shutdown': privileged()},
                'readable': ['capabilities', 'apps', 'display'] + (['audio'] if audio else []) +
                    (['network'] if nm or bt else []) + (['services'] if shutil.which('systemctl') else []),
                'notes': ['Recording lock affects GLaDOS only, not other programs or hardware microphone gain.',
                          'Services report systemd/process state, not remote connectivity or backend readiness.',
                          'CPU/RAM/temperature/storage are supplied by the existing getSystemHealth tool.',
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
                    'screen_locked': d._screen_locked, 'measurement': 'last_commanded_not_sensor'}
        if scope == 'audio':
            m.volume.refresh()
            return {'speaker_percent': m.volume.state.current_percent, 'mic_gain': m.volume.mic,
                    'glados_recording_enabled': d._recording_enabled, 'input_mode': m.volume.ptt,
                    'sound_card': m.volume.state.card, 'hardware_mic_mute': False}
        if scope == 'network':
            result = {}
            for name in ('wifi', 'bluetooth'):
                app = getattr(m, name)
                try:
                    app.refresh()
                    result[name] = ({'enabled': app.radio, 'device': app.device,
                        'connected': [asdict(n) for n in app.state.networks if n.active]} if name == 'wifi' else
                        {'enabled': app.powered, 'devices': [asdict(n) for n in app.state.devices]})
                except Exception:
                    result[name] = {'available': False}
            return result
        if scope == 'services':
            m.services.refresh()
            return {'services': dict(m.services.statuses), 'glados': m.services.glados_state(),
                    'backend_readiness': 'not_tested'}
        raise ValueError('Unsupported read scope')

    def normalize(self, payload):
        if not isinstance(payload, dict) or set(payload) - {'action', 'level', 'change', 'enabled', 'service', 'operation'}:
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
        elif action in ('recording', 'wifi', 'bluetooth'):
            if type(p.get('enabled')) is not bool:
                raise ValueError('Boolean enabled required')
            permitted.add('enabled')
        elif action == 'service':
            if p.get('service') not in SERVICES or p.get('operation') not in ('start', 'restart'):
                raise ValueError('Unsupported service operation')
            permitted.update(('service', 'operation'))
        if set(p) != permitted:
            raise ValueError('Unexpected or missing action parameters')
        if not self.capabilities()['actions'][action]['supported']:
            raise RuntimeError(self.capabilities()['actions'][action].get('reason') or 'Action unavailable')
        return p

    def execute(self, payload):
        p = self.normalize(payload)
        d, m, action = self.daemon, self.daemon.internal_apps, p['action']
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
            target = {'recording': m.volume, 'wifi': m.wifi, 'bluetooth': m.bluetooth,
                      'service': m.services, 'reboot': m.system, 'shutdown': m.system}[action]
            d._launch_app(d.apps[target.APP_ID])
            if action in ('reboot', 'shutdown'):
                target.ask_power('reboot' if action == 'reboot' else 'poweroff')
            elif action == 'service':
                target.ask_service(p['service'], p['operation'])
            else:
                enabled = p['enabled']
                if action == 'recording':
                    callback = lambda: target.perform(lambda: target._recording(enabled))
                    detail = ['GLaDOS only; not hardware mute.', 'Enable again here in Audio.']
                elif action == 'wifi':
                    callback = lambda: target.change('wifi-radio', 'on' if enabled else 'off')
                    detail = ['May disconnect SSH.', 'Enable locally in Network.']
                else:
                    callback = lambda: target.change('power', enabled=enabled)
                    detail = ['May disconnect devices.', 'Enable locally in Network.']
                target.confirmation.ask(('Enable ' if enabled else 'Disable ') + action, detail, callback)
            d._render_internal_app()
        finally:
            self.operations.release()
