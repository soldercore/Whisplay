"""Shared one-button list and local confirmation behavior for built-in menus."""
from dataclasses import dataclass
import time

from daemon_models import AppRecord


class Confirmation:
    def __init__(self, changed, status):
        self.changed, self.status = changed, status
        self.pending = None
        self.selected = 0
        self.cancel_action = None

    def ask(self, title, detail, action, on_cancel=None):
        self.clear(cancel=True)
        self.pending = (title, detail, action, time.monotonic() + 30)
        self.cancel_action = on_cancel
        self.selected = 0  # Opening a dialog never selects the dangerous action.
        self.changed()

    def clear(self, cancel=False):
        callback = self.cancel_action if cancel else None
        self.pending = None
        self.selected = 0
        self.cancel_action = None
        if callback:
            callback()

    def handle(self, long_press):
        if self.pending is None:
            return False
        title, detail, action, deadline = self.pending
        if time.monotonic() >= deadline:
            self.clear(cancel=True)
            self.status('Confirmation expired')
        elif not long_press:
            self.selected = 1 - self.selected
            self.changed()
        else:
            selected = self.selected
            cancel_action = self.cancel_action
            self.clear()
            if selected == 1:
                action()
            else:
                if cancel_action:
                    cancel_action()
                self.status('Cancelled')
        return True

    def view(self):
        if self.pending is None:
            return None
        title, detail, _, deadline = self.pending
        if time.monotonic() >= deadline:
            self.clear(cancel=True)
            self.status('Confirmation expired')
            return None
        return {'kind': 'list', 'title': title, 'subtitle': 'Confirm locally',
                'items': [{'title': 'Cancel', 'meta': 'Make no changes'},
                          {'title': 'Confirm', 'meta': title}],
                'selected_index': self.selected, 'busy': False,
                'status': 'Tap to choose; hold to select', 'detail_lines': detail[:2]}


@dataclass
class MenuState:
    selected_index: int = 0
    busy: bool = False
    status: str = 'Hold to select'
    last_refresh_at: float = 0


class MenuApp:
    APP_ID = ''
    TITLE = ''
    ICON = ''
    PRIORITY = 0

    def __init__(self, lock, changed, run_command, spawn_worker, request_exit):
        self._lock, self._mark_dirty = lock, changed
        self._run_command, self._spawn_worker = run_command, spawn_worker
        self._request_exit = request_exit
        self.state = MenuState()
        self.confirmation = Confirmation(changed, self.note)

    def builtin_app(self):
        return AppRecord(self.APP_ID, self.TITLE, icon=self.ICON, priority=self.PRIORITY,
                         exit_gesture='', persist=False)

    def activate(self):
        with self._lock:
            self.confirmation.clear(cancel=True)
            self.state.selected_index = 0

    def deactivate(self):
        with self._lock:
            self.confirmation.clear(cancel=True)

    def note(self, text):
        with self._lock:
            self.state.status = str(text)
        self._mark_dirty()

    def set_error(self, message):
        with self._lock:
            self.state.busy = False
            self.state.last_refresh_at = time.time()
        self.note(message)

    def items(self):
        return [('Back', 'Return to Home', self._request_exit)]

    def handle_button(self, is_long_press):
        with self._lock:
            if self.confirmation.handle(is_long_press):
                return
            items = self.items()
            self.state.selected_index %= max(1, len(items))
            if not is_long_press:
                self.state.selected_index = (self.state.selected_index + 1) % len(items)
                self._mark_dirty()
                return
            index = self.state.selected_index
            if self.state.busy and index != 0:
                return
            action = items[index][2]
        action()

    def handle_keyboard_action(self, action):
        if action == 'submit':
            self.handle_button(True)
        elif action == 'down':
            self.handle_button(False)
        elif action == 'up':
            with self._lock:
                if self.confirmation.pending:
                    self.confirmation.selected = 1 - self.confirmation.selected
                else:
                    self.state.selected_index = (self.state.selected_index - 1) % len(self.items())
                self._mark_dirty()

    def view_model(self):
        with self._lock:
            confirm = self.confirmation.view()
            if confirm:
                return confirm
            items = self.items()
            return {'kind': 'list', 'title': self.TITLE, 'subtitle': 'Device controls',
                    'items': [{'title': title, 'meta': meta} for title, meta, _ in items],
                    'selected_index': min(self.state.selected_index, len(items) - 1),
                    'status': self.state.status, 'busy': self.state.busy}

    def refresh(self):
        pass

    def refresh_async(self, force=False):
        with self._lock:
            if self.state.busy or self.confirmation.pending:
                return
        self.perform(self.refresh, 'Reading status...')

    def perform(self, action, message='Applying...'):
        with self._lock:
            if self.state.busy:
                return
            self.state.busy = True
            self.state.status = message
        self._mark_dirty()

        def work():
            try:
                action()
            except Exception as exc:
                self.set_error(str(exc) or 'Operation failed')
            finally:
                with self._lock:
                    self.state.busy = False
                    self.state.last_refresh_at = time.time()
                self._mark_dirty()
        if self._spawn_worker('menu-' + self.APP_ID, work) is False:
            self.set_error('Previous operation finishing; retry')
