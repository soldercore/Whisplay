"""Power actions require a separate, expiring local confirmation."""
from .menu import MenuApp
from .control_client import control

SYSTEM_APP_ID = 'whisplay-system'


class SystemInternalApp(MenuApp):
    APP_ID, TITLE, ICON, PRIORITY = SYSTEM_APP_ID, 'Power Menu', 'PW', 150

    def __init__(self, lock, mark_dirty, run_command, spawn_worker, request_exit, lock_screen):
        super().__init__(lock, mark_dirty, run_command, spawn_worker, request_exit)
        self._lock_screen = lock_screen

    def builtin_app(self):
        app = super().builtin_app()
        app.display_name = 'Power'
        return app

    def ask_power(self, action):
        title = 'Shut down Pi' if action == 'poweroff' else 'Reboot Pi'
        detail = ['All apps will stop.', 'Hardware power-on only.'] if action == 'poweroff' else [
            'All apps / SSH will stop.', 'Wait for the Pi to restart.']
        self.confirmation.ask(title, detail, lambda: self.perform(lambda: self._run_power_action(action)))

    def _run_power_action(self, action):
        if action not in ('reboot', 'poweroff'):
            raise ValueError('Power action is not allowed')
        control(self._run_command, 'power', action)
        self.note('Shutdown command accepted' if action == 'poweroff' else 'Reboot command accepted')

    def items(self):
        return super().items() + [
            ('Lock screen', 'Press button to unlock', self._lock_screen),
            ('Reboot', 'Requires confirmation', lambda: self.ask_power('reboot')),
            ('Shutdown', 'Hardware needed to power on', lambda: self.ask_power('poweroff'))]
