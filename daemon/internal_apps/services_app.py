"""Read-only status plus a fixed allowlist of locally confirmed operations."""
import subprocess
from .menu import MenuApp
from .control_client import control

UNITS = {'ssh': ('SSH', 'ssh.service'), 'ollama': ('Ollama', 'ollama.service'),
         'whisper': ('Faster-Whisper', 'whisplay-whisper.service'),
         'piper': ('Piper', 'whisplay-piper.service'),
         'daemon': ('Whisplay daemon', 'whisplay-daemon.service')}


def service_state(text):
    values = dict(line.split('=', 1) for line in text.splitlines() if '=' in line)
    if values.get('LoadState') not in ('loaded', 'masked'):
        return 'Unavailable'
    state = values.get('ActiveState')
    return {'active': 'Running', 'inactive': 'Stopped', 'activating': 'Starting',
            'reloading': 'Starting', 'deactivating': 'Stopping', 'failed': 'Failed'}.get(state, 'Unavailable')


class ServicesApp(MenuApp):
    APP_ID, TITLE, ICON, PRIORITY = 'whisplay-services', 'Services', 'SV', 152

    def __init__(self, *args, glados_status, launch_glados, begin_maintenance, end_maintenance):
        super().__init__(*args)
        self.glados_status, self.launch_glados = glados_status, launch_glados
        self.begin_maintenance, self.end_maintenance = begin_maintenance, end_maintenance
        self.statuses = {}
        self.selected_service = None

    def activate(self):
        super().activate()
        self.selected_service = None

    def refresh(self):
        statuses = {}
        for key, (_, unit) in UNITS.items():
            try:
                result = self._run_command(['/usr/bin/systemctl', 'show', '--no-pager',
                    '-p', 'LoadState,ActiveState,SubState', unit], timeout=3)
                statuses[key] = service_state(result.stdout) if result.returncode == 0 else 'Unavailable'
            except (OSError, subprocess.TimeoutExpired):
                statuses[key] = 'Unavailable'
        with self._lock:
            self.statuses = statuses
        self.note('Process / systemd status; backend readiness is not tested')

    def open_service(self, key):
        self.selected_service, self.state.selected_index = key, 0

    def back(self):
        self.selected_service, self.state.selected_index = None, 0

    def glados_state(self):
        state = self.glados_status()
        return ('Unavailable' if not state.get('registered') else 'Stopping' if state.get('stopping') else
                'Starting' if state.get('starting') else 'Running' if state.get('running') else
                'Failed' if state.get('failed') else 'Stopped')

    def change(self, key, action):
        if key not in UNITS or key == 'daemon' or action not in ('start', 'restart'):
            raise ValueError('Service action not allowed')
        def work():
            self.begin_maintenance()
            try:
                control(self._run_command, 'service', action, key)
                self.refresh()
                if self.statuses.get(key) != 'Running':
                    raise RuntimeError('Service action accepted but not running')
                self.note(UNITS[key][0] + ' running; backend readiness not tested')
            finally:
                self.end_maintenance()
        self.perform(work)

    def ask_service(self, key, action):
        detail = ['May interrupt SSH access.', 'Start SSH again in this menu.'] if key == 'ssh' else [
            'GLaDOS must be stopped.', 'No model / voice configuration changes.']
        self.confirmation.ask(action.title() + ' ' + UNITS[key][0], detail, lambda: self.change(key, action))

    def items(self):
        key = self.selected_service
        if key is None:
            return super().items() + [('Refresh status', 'Read systemd / app states', self.refresh_async)] + [
                (name, self.statuses.get(identifier, 'Unavailable'), lambda identifier=identifier: self.open_service(identifier))
                for identifier, (name, _) in UNITS.items()] + [
                ('GLaDOS chatbot', self.glados_state(), lambda: self.open_service('glados'))]
        rows = [('Back', 'Return to Services', self.back)]
        if key == 'daemon':
            return rows + [('Whisplay daemon', self.statuses.get(key, 'Unavailable'),
                            lambda: self.note('Read only: daemon cannot stop or restart itself'))]
        if key == 'glados':
            return rows + [('Launch GLaDOS', self.glados_state(), self.launch_glados)]
        name = UNITS[key][0]
        return rows + [('Start ' + name, self.statuses.get(key, 'Unavailable'), lambda: self.ask_service(key, 'start')),
                       ('Restart ' + name, 'Requires confirmation', lambda: self.ask_service(key, 'restart'))]
