import re

from .menu import MenuApp
from .bluetooth_app import BluetoothInternalApp, BluetoothViewState, BluetoothDevice
from bluetooth_pairing_agent import BluetoothPairingAgent


class BluetoothControl(MenuApp, BluetoothInternalApp):
    APP_ID, TITLE, ICON, PRIORITY = 'whisplay-bluetooth', 'Bluetooth', 'BT', 200

    def __init__(self, *args):
        MenuApp.__init__(self, *args)
        self.state = BluetoothViewState()
        self.powered = None
        self.active = False
        self.pairing_address = None
        self._strip_ansi = lambda text: re.sub(r'\x1b\[[0-9;]*m', '', text)
        self._pairing_agent = BluetoothPairingAgent(self._update_pairing_state)

    def activate(self):
        MenuApp.activate(self)
        self.active = True

    def deactivate(self):
        MenuApp.deactivate(self)
        self.active = False
        self.state.pairing_active = False
        self._pairing_agent.cancel()

    def checked(self, *args, timeout=10):
        result = self._run_command(['bluetoothctl', *args], timeout=timeout)
        output = (result.stdout or '') + (result.stderr or '')
        if result.returncode or any(text in output.lower() for text in ('failed', 'not available', 'no default controller')):
            raise RuntimeError('Bluetooth operation failed / unavailable')
        return output

    def refresh(self):
        show = self.checked('show')
        powered = True if 'Powered: yes' in show else False if 'Powered: no' in show else None
        devices = []
        for address, name in list(self._parse_device_lines(self.checked('devices')).items())[:20]:
            if not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', address):
                continue
            info = self.checked('info', address)
            clean = self._resolve_name(address, name, info, {}) or address
            signal = self._parse_signal(info) if 'RSSI:' in info else None
            devices.append(BluetoothDevice(address, clean, signal, 'Paired: yes' in info,
                                            'Connected: yes' in info, 'Trusted: yes' in info))
        with self._lock:
            self.powered, self.state.devices = powered, devices
        self.note('Radio on' if powered else 'Radio off' if powered is False else 'Radio unavailable')

    def change(self, action, address=None):
        def work():
            if action == 'power':
                self.checked('power', 'off' if self.powered else 'on')
            elif action == 'scan':
                self.checked('--timeout', '5', 'scan', 'on', timeout=9)
            else:
                if not address or not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', address):
                    raise ValueError('Invalid Bluetooth address')
                self.pairing_address = address if action == 'pair' else None
                try:
                    self.checked(action, address, timeout=30)
                    if action == 'pair':
                        self.checked('connect', address, timeout=20)
                finally:
                    self.pairing_address = None
            self.refresh()
            self.note('Bluetooth action complete; status refreshed')
        self.perform(work)

    def _update_pairing_state(self, payload):
        with self._lock:
            if not self.active or not self.pairing_address:
                self._pairing_agent.cancel()
                return
            self.state.pairing_active = bool(payload.get('active'))
            self.state.pairing_message = str(payload.get('message') or '')
            self.state.pairing_detail = str(payload.get('detail') or '')
            if payload.get('requires_confirmation'):
                self.confirmation.ask('Confirm pairing', [str(payload.get('message', ''))[:40],
                    str(payload.get('detail', ''))[:40]], self._pairing_agent.confirm,
                    on_cancel=self._pairing_agent.cancel)
            elif payload.get('active'):
                self.state.status = str(payload.get('message') or 'Pairing...')
        self._mark_dirty()

    def view_model(self):
        view = MenuApp.view_model(self)
        if self.state.pairing_active and not self.confirmation.pending:
            view['detail_lines'] = [self.state.pairing_message, self.state.pairing_detail]
        return view

    def items(self):
        radio = 'On' if self.powered is True else 'Off' if self.powered is False else 'Unavailable'
        rows = [('Back', 'Return to Network', self._request_exit),
                ('Refresh status', 'No radio changes', self.refresh_async),
                ('Bluetooth ' + radio, 'Hold to toggle radio', lambda: self.confirmation.ask(
                    'Disable Bluetooth' if self.powered else 'Enable Bluetooth',
                    ['May disconnect devices.', 'Enable again in this menu.'], lambda: self.change('power'))),
                ('Scan devices', 'Five second local scan', lambda: self.change('scan'))]
        for device in self.state.devices:
            meta = 'Connected' if device.connected else 'Paired' if device.paired else 'Available'
            action = 'disconnect' if device.connected else 'connect' if device.paired else 'pair'
            rows.append((device.name, meta + ': ' + action, lambda device=device, action=action:
                         self.confirmation.ask(action.title() + ' device', [device.name, device.address],
                             lambda: self.change(action, device.address))))
            if device.paired:
                rows.append(('Forget ' + device.name, 'Remove pairing only', lambda device=device:
                    self.confirmation.ask('Forget pairing', [device.name, device.address],
                        lambda: self.change('remove', device.address))))
        return rows
