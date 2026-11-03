"""One read-only event observer. No scans, credentials, or microphone access."""
import subprocess
import threading
import time


def unknown_status():
    return {'wifi': {'enabled': None, 'connected': None, 'signal': None},
            'bluetooth': {'enabled': None}}


class RadioStatus:
    def __init__(self, wifi, bluetooth):
        self.wifi, self.bluetooth = wifi, bluetooth
        self.state = unknown_status()
        self.lock = threading.Lock()
        self.dirty, self.stopped, self.updated = threading.Event(), threading.Event(), threading.Event()
        self.process = None
        self.worker = self.listener = None

    def snapshot(self):
        with self.lock:
            return {key: dict(value) for key, value in self.state.items()}

    def sample(self):
        state = unknown_status()
        try:
            state['wifi'] = self.wifi.indicator_status()
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
            pass  # Unknown, never display a failed read as disabled.
        try:
            self.bluetooth.refresh(include_devices=False, budget_seconds=2)
            state['bluetooth']['enabled'] = self.bluetooth.powered
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
            pass
        with self.lock:
            if state != self.state:
                self.state = state
                self.updated.set()

    def _observe(self):
        while not self.stopped.is_set():
            try:
                process = subprocess.Popen(['/usr/bin/dbus-monitor', '--system',
                    "type='signal',sender='org.freedesktop.NetworkManager'",
                    "type='signal',sender='org.bluez'",
                    "type='signal',interface='org.freedesktop.DBus',member='NameOwnerChanged',arg0='org.bluez'",
                    "type='signal',interface='org.freedesktop.DBus',member='NameOwnerChanged',arg0='org.freedesktop.NetworkManager'"],
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
                with self.lock:
                    self.process = process
                if self.stopped.is_set():
                    self._close_process(process)
                    return
                self.dirty.set()  # Subscribe before initial read to avoid missing a change.
                try:
                    for line in process.stdout:
                        # Drain, but never retain/log any D-Bus property values.
                        if line.startswith('signal '):
                            self.dirty.set()
                        if self.stopped.is_set():
                            break
                finally:
                    self._close_process(process)
                    with self.lock:
                        if self.process is process:
                            self.process = None
            except (OSError, subprocess.SubprocessError):
                self.dirty.set()
            self.stopped.wait(10)

    @staticmethod
    def _close_process(process):
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()  # Only this observer's exact owned child.
                process.wait(timeout=2)
        if process.stdout:
            process.stdout.close()

    def _work(self):
        while not self.stopped.is_set():
            self.dirty.wait(60)  # Infrequent fallback if a bus event is lost/unavailable.
            if self.stopped.is_set():
                return
            self.dirty.clear()
            self.sample()
            self.stopped.wait(1)  # Coalesce signal bursts; never block the button/render loop.

    def start(self):
        self.dirty.set()
        self.worker = threading.Thread(target=self._work, daemon=True)
        self.listener = threading.Thread(target=self._observe, daemon=True)
        self.worker.start()
        self.listener.start()

    def stop(self):
        self.stopped.set()
        self.dirty.set()
        with self.lock:
            process = self.process
        if process and process.poll() is None:
            process.terminate()
        for thread in (self.listener, self.worker):
            if thread:
                thread.join(timeout=12)
