from __future__ import annotations

import re
import os
import subprocess
import threading
import time

from .bluetooth_app import BLUETOOTH_APP_ID, BluetoothInternalApp
from .system_app import SYSTEM_APP_ID, SystemInternalApp
from .volume_app import VOLUME_APP_ID, VolumeInternalApp
from .wifi_app import WIFI_APP_ID, WifiInternalApp
from .wifi_control import WifiControl
from .bluetooth_control import BluetoothControl
from .audio_control import AudioControl
from .network_app import NetworkApp
from .display_app import DisplayApp
from .device_info import InformationApp


class InternalAppManager:
    REFRESH_INTERVAL_SEC = 20.0

    def __init__(self, lock_screen=None, *, glados_status=lambda: {}, set_recording=lambda value: None,
                 get_display=lambda: {}, set_brightness=lambda value: None, battery=lambda: None):
        self._lock = threading.RLock()
        self._dirty = False
        self._exit_requested = False
        self._threads: dict[str, threading.Thread] = {}
        self._active_app = None
        self._parents = []
        self._navigation = None
        self._navigating = False
        args = (self._lock, self._mark_dirty, self._run_command, self._spawn_worker, self._request_exit)
        self.bluetooth = BluetoothControl(*args)
        self.wifi = WifiControl(*args)
        self.volume = AudioControl(*args, glados_status=glados_status, set_recording=set_recording)
        self.network = NetworkApp(*args, open_app=self.open_child)
        self.display = DisplayApp(*args, get_display=get_display, set_brightness=set_brightness,
                                  lock_screen=lock_screen or (lambda: None))
        self.information = InformationApp(*args, battery=battery)
        self.system = SystemInternalApp(
            self._lock,
            self._mark_dirty,
            self._run_command,
            self._spawn_worker,
            self._request_exit,
            lock_screen or (lambda: None),
        )
        self._apps = {
            BLUETOOTH_APP_ID: self.bluetooth,
            WIFI_APP_ID: self.wifi,
            VOLUME_APP_ID: self.volume,
            SYSTEM_APP_ID: self.system,
            self.network.APP_ID: self.network,
            self.display.APP_ID: self.display,
            self.information.APP_ID: self.information,
        }

    def start(self):
        self.bluetooth.start()

    def stop(self):
        self.bluetooth.stop()

    def builtin_apps(self):
        return [app.builtin_app() for app in self._apps.values()]

    def is_internal_app(self, app_id: str | None) -> bool:
        return app_id in self._apps

    @property
    def exit_requested(self) -> bool:
        with self._lock:
            return self._exit_requested

    def clear_exit_requested(self):
        with self._lock:
            self._exit_requested = False

    def text_input_active(self) -> bool:
        return self.wifi.text_input_active()

    def consume_dirty(self) -> bool:
        with self._lock:
            dirty = self._dirty
            self._dirty = False
            return dirty

    def activate(self, app_id: str):
        previous = self._apps.get(self._active_app)
        if previous is not None and hasattr(previous, 'deactivate'):
            previous.deactivate()
        if not self._navigating:
            self._parents.clear()
        self._navigating = False
        self._active_app = app_id
        app = self._apps.get(app_id)
        if app is not None and hasattr(app, "activate"):
            app.activate()
        self._mark_dirty()
        self.refresh_async(app_id, force=True)

    def deactivate(self):
        previous = self._apps.get(self._active_app)
        if previous is not None and hasattr(previous, 'deactivate'):
            previous.deactivate()
        self._active_app = None
        self._parents.clear()
        self._navigation = None

    def open_child(self, app_id):
        if app_id not in self._apps:
            return
        self._parents.append(self._active_app)
        self._navigation = app_id

    def consume_navigation(self):
        target, self._navigation = self._navigation, None
        self._navigating = target is not None
        return target

    def tick(self, app_id: str | None):
        app = self._apps.get(app_id)
        if app is None:
            return
        state = app.state
        now = time.time()
        if state.busy or state.selected_index != 0:
            return
        if now - state.last_refresh_at >= self.REFRESH_INTERVAL_SEC:
            self.refresh_async(app_id, force=True)

    def handle_button_release(self, app_id: str, is_long_press: bool):
        app = self._apps.get(app_id)
        if app is not None:
            app.handle_button(is_long_press)

    def handle_keyboard_action(self, app_id: str, action):
        app = self._apps.get(app_id)
        if app is not None:
            app.handle_keyboard_action(action)

    def get_view_model(self, app_id: str) -> dict:
        app = self._apps.get(app_id)
        return app.view_model() if app is not None else {}

    def refresh_async(self, app_id: str, force: bool = False):
        app = self._apps.get(app_id)
        if app is None:
            return
        app.refresh_async()

    def _request_exit(self):
        with self._lock:
            if self._parents:
                self._navigation = self._parents.pop()
            else:
                self._exit_requested = True

    def _spawn_worker(self, name: str, target):
        with self._lock:
            thread = self._threads.get(name)
            if thread and thread.is_alive():
                return
            thread = threading.Thread(target=self._run_worker, args=(target,), daemon=True)
            self._threads[name] = thread
            thread.start()

    def _run_worker(self, target):
        try:
            target()
        except Exception as exc:
            self._set_error(str(exc))

    def _set_error(self, message: str):
        text = (message or "operation failed").strip()
        self.bluetooth.set_error(text)
        self.wifi.set_error(text)
        self.volume.set_error(text)
        self.system.set_error(text)

    def _mark_dirty(self):
        with self._lock:
            self._dirty = True

    def _run_command(self, args: list[str], timeout: float = 10.0, input_text=None) -> subprocess.CompletedProcess:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout, check=False,
                              input=input_text, env={**os.environ, 'LC_ALL': 'C'})

    def _strip_ansi(self, text: str) -> str:
        return re.sub(r"\x1b\[[0-9;]*m", "", text)
