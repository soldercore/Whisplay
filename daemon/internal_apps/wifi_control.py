"""Extend the existing nmcli/keyboard integration for the original one-button HAT."""
import re
import time

from .menu import MenuApp
from .wifi_app import WifiInternalApp, WifiViewState, WifiNetwork, SCREEN_KEYBOARD_ROWS
from .control_client import control, ControlBlocked


class WifiControl(MenuApp, WifiInternalApp):
    APP_ID, TITLE, ICON, PRIORITY = 'whisplay-wifi', 'Wi-Fi', 'WF', 190

    def __init__(self, *args):
        MenuApp.__init__(self, *args)
        self.state = WifiViewState()
        self.radio = None
        self.device = ''
        self.saved = []
        self.key_page = None
        self.key_index = 0
        self.join_security = 'wpa-psk'

    def activate(self):
        MenuApp.activate(self)
        self._cancel_password_input('Hold Refresh to scan')

    def deactivate(self):
        MenuApp.deactivate(self)
        self._cancel_password_input('Cancelled')

    def refresh_async(self, force=False):
        if self.state.mode != 'input':
            MenuApp.refresh_async(self, force)

    def _read(self, args, timeout=8):
        result = self._run_command(['nmcli', *args], timeout=timeout)
        if result.returncode:
            raise RuntimeError('NetworkManager unavailable')
        return result.stdout

    def refresh(self):
        radio = self._read(['-t', '-f', 'WIFI', 'radio']).strip()
        radio = True if radio == 'enabled' else False if radio == 'disabled' else None
        devices = self._read(['-t', '-f', 'DEVICE,TYPE,STATE', 'device'])
        device = next((self._split_escaped_fields(line, 3, ':')[0] for line in devices.splitlines()
                       if len(self._split_escaped_fields(line, 3, ':')) == 3
                       and self._split_escaped_fields(line, 3, ':')[1] == 'wifi'), '')
        networks = []
        if radio:
            data = self._read(['-t', '--escape', 'yes', '-f', 'IN-USE,SSID,SIGNAL,SECURITY',
                               'device', 'wifi', 'list', '--rescan', 'no'], 15)
            for line in data.splitlines():
                fields = self._split_escaped_fields(line, 4, ':')
                if len(fields) != 4 or not fields[1]:
                    continue
                active, ssid, signal, security = fields
                strength = int(signal) if signal.isdigit() and 0 <= int(signal) <= 100 else None
                if not any(n.ssid == ssid for n in networks):
                    networks.append(WifiNetwork(ssid, strength, security, active == '*'))
            ip = self._get_connected_wifi_ipv4()
            for network in networks:
                if network.active:
                    network.ipv4 = ip
        saved = []
        for line in self._read(['-t', '--escape', 'yes', '-f', 'UUID,NAME,TYPE', 'connection', 'show']).splitlines():
            fields = self._split_escaped_fields(line, 3, ':')
            if len(fields) == 3 and fields[2] == '802-11-wireless' and re.fullmatch('[0-9a-fA-F-]{36}', fields[0]):
                saved.append((fields[0], fields[1]))
        networks.sort(key=lambda n: (not n.active, -(n.signal or 0), n.ssid))
        with self._lock:
            self.radio, self.device, self.saved = radio, device, saved
            self.state.networks = networks
        self.note('Radio on' if radio else 'Radio off; enable locally' if radio is False else 'Radio unavailable')

    def scan(self):
        try:
            self._read(['device', 'wifi', 'rescan'], 15)
        except RuntimeError:
            # Headless polkit may require authorization; keep already-authorized
            # users unprivileged and use only the fixed scan fallback otherwise.
            control(self._run_command, 'wifi-scan')
        self.refresh()

    def change(self, *args, payload=None):
        self.perform(lambda: self.apply_change(*args, payload=payload))

    def apply_change(self, *args, payload=None):
        try:
            control(self._run_command, *args, payload=payload)
        except ControlBlocked:
            raise
        except Exception:
            raise RuntimeError('Wi-Fi action failed; check permissions / credentials') from None
        self.refresh()
        self.note('Wi-Fi action accepted; status refreshed')

    def ask(self, title, action, target=None):
        self.confirmation.ask(title, [target[:18], target[18:36]] if target else
            ['May disconnect SSH.', 'Wi-Fi can be enabled here.'], action)
        self.confirmation_target = target

    def select_network(self, network):
        security = network.security.upper()
        if network.active:
            self.note('Connected: ' + (network.ipv4 or 'IP unavailable'))
        elif '802.1X' in security or 'EAP' in security or 'WEP' in security:
            self.note('Use a saved profile for enterprise / WEP')
        elif security in ('', '--', 'NONE', 'OPEN'):
            self.ask('Join Wi-Fi', lambda: self.change('wifi-join', payload={
                'ssid': network.ssid, 'password': '', 'security': 'open'}), target=network.ssid)
        else:
            self.state.mode = 'input'
            self.state.password_target_ssid = network.ssid
            self.state.password_buffer = ''
            self.join_security = 'sae' if 'WPA3' in security and 'WPA2' not in security else 'wpa-psk'
            self.key_page, self.key_index = None, 0
            self.note('Tap next; hold select. Password masked.')

    def items(self):
        radio = 'On' if self.radio is True else 'Off' if self.radio is False else 'Unavailable'
        rows = [('Back', 'Return to Network', self._request_exit),
                ('Refresh status', 'No radio changes', self.refresh_async),
                ('Wi-Fi ' + radio, 'Hold to ' + ('disable' if self.radio else 'enable'),
                 lambda: self.ask('Disable Wi-Fi' if self.radio else 'Enable Wi-Fi',
                     lambda: self.change('wifi-radio', 'off' if self.radio else 'on'))),
                ('Scan networks', 'Explicit local scan', lambda: self.perform(self.scan)),
                ('Disconnect', 'Current Wi-Fi; may lose SSH', lambda: self.ask('Disconnect Wi-Fi',
                     lambda: self.change('wifi-disconnect', self.device)))]
        for identity, name in self.saved:
            rows.append(('Saved: ' + name, 'Hold to connect', lambda identity=identity, name=name:
                         self.ask('Connect saved Wi-Fi', lambda: self.change('wifi-connect', identity), target=identity)))
        for network in self.state.networks:
            signal = 'signal unavailable' if network.signal is None else f'{network.signal}%'
            meta = (signal + ' | ' + (network.ipv4 or 'IP unavailable')) if network.active else signal + ' ' + network.security
            rows.append((network.ssid, meta, lambda network=network: self.select_network(network)))
        return rows

    def _password_items(self):
        if self.key_page is not None:
            row = SCREEN_KEYBOARD_ROWS[self.key_page]
            return [('Back to keys', '', lambda: self._key_back())] + [
                (self._screen_key_label(key), 'Hold to enter', lambda key=key: self._enter_key(key)) for key in row]
        return [('Cancel', 'Discard password', lambda: self._cancel_password_input('Cancelled')),
                ('Delete', 'Remove last character', self._delete),
                ('Join', 'Confirm network switch', self._submit)] + [
            ('Keys: ' + ''.join(self._screen_key_label(k) for k in row)[:18], 'Hold to open row',
             lambda i=i: self._key_open(i)) for i, row in enumerate(SCREEN_KEYBOARD_ROWS)]

    def _key_open(self, page):
        self.key_page, self.key_index = page, 0

    def _key_back(self):
        self.key_page, self.key_index = None, 0

    def _delete(self):
        self.state.password_buffer = self.state.password_buffer[:-1]

    def _enter_key(self, key):
        if key.action == 'submit':
            self._submit()
        elif key.action == 'backspace':
            self._delete()
        elif key.action == 'shift':
            self.state.keyboard_shifted = not self.state.keyboard_shifted
        elif len(self.state.password_buffer) < 64:
            self.state.password_buffer += key.shifted if self.state.keyboard_shifted else key.value
        self._key_back()

    def _submit(self):
        ssid, password = self.state.password_target_ssid, self.state.password_buffer
        if not 8 <= len(password) <= 63 and not re.fullmatch('[0-9a-fA-F]{64}', password):
            self.note('WPA password: 8-63 characters or 64 hex')
            return
        payload = {'ssid': ssid, 'password': password, 'security': self.join_security}
        self._cancel_password_input('Confirm join')
        self.ask('Join Wi-Fi', lambda: self.change('wifi-join', payload=payload), target=ssid)

    def handle_button(self, is_long_press):
        with self._lock:
            if self.confirmation.pending or self.state.mode != 'input':
                return MenuApp.handle_button(self, is_long_press)
            rows = self._password_items()
            self.key_index %= len(rows)
            if is_long_press:
                rows[self.key_index][2]()
            else:
                self.key_index = (self.key_index + 1) % len(rows)
            self._mark_dirty()

    def handle_keyboard_action(self, action):
        if self.state.mode == 'input':
            if action in ('down', 'keyboard_down', 'keyboard_right'):
                self.handle_button(False)
            elif action in ('up', 'keyboard_up', 'keyboard_left'):
                self.key_index = (self.key_index - 1) % len(self._password_items())
            elif action in ('submit', 'keyboard_select'):
                self.handle_button(True)
            elif action in ('cancel', 'keyboard_cancel'):
                self._cancel_password_input('Cancelled')
            elif action == 'backspace':
                self._delete()
            elif isinstance(action, tuple) and action[0] == 'char' and len(self.state.password_buffer) < 64:
                self.state.password_buffer += ''.join(c for c in action[1] if 32 <= ord(c) <= 126)[:1]
            self._mark_dirty()
        else:
            MenuApp.handle_keyboard_action(self, action)

    def view_model(self):
        if self.state.mode != 'input':
            view = MenuApp.view_model(self)
            if self.confirmation.pending and getattr(self, 'confirmation_target', None):
                view['subtitle'] = 'May disconnect SSH'
                view['detail_compact'] = True
            elif not self.confirmation.pending:
                view['subtitle'] = 'Wi-Fi on' if self.radio is True else 'Wi-Fi off' if self.radio is False else 'Radio unavailable'
                index = self.state.selected_index - 5
                if 0 <= index < len(self.saved):
                    identity = self.saved[index][0]
                    view['detail_lines'] = [identity[:18], identity[18:]]
                    view['detail_compact'] = True
                elif 0 <= index - len(self.saved) < len(self.state.networks):
                    ssid = self.state.networks[index - len(self.saved)].ssid
                    view['detail_lines'] = [ssid[:18], ssid[18:]]
                    view['detail_compact'] = True
            return view
        with self._lock:
            return {'kind': 'list', 'title': 'Wi-Fi password', 'subtitle': self.state.password_target_ssid,
                    'items': [{'title': t, 'meta': m} for t, m, _ in self._password_items()],
                    'selected_index': self.key_index, 'busy': False,
                    'status': '*' * min(len(self.state.password_buffer), 20),
                    'detail_lines': [f'{len(self.state.password_buffer)} characters', self.state.status]}
