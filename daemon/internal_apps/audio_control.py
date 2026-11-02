import re
from pathlib import Path

from .menu import MenuApp
from .volume_app import VolumeInternalApp, VolumeViewState


class AudioControl(MenuApp, VolumeInternalApp):
    APP_ID, TITLE, ICON, PRIORITY = 'whisplay-volume', 'Audio', 'AU', 180

    def __init__(self, *args, glados_status, set_recording):
        MenuApp.__init__(self, *args)
        self.state = VolumeViewState()
        self.glados_status, self.set_recording = glados_status, set_recording
        self.available, self.mic, self.ptt = False, None, 'Unavailable'
        self.restore_volume = 50

    def refresh(self):
        self.available, self.mic = False, None
        card, name, maximum = self._detect_volume_control()
        current = self._read_current_value(card, name)
        percent = max(0, min(100, current)) if self._is_unified_control(name) else self._device_value_to_curve_percent(current, maximum)
        result = self._run_command(['amixer', '-c', card, 'cget', 'name=mic'], timeout=5)
        match = re.search(r':\s*values=(\d+)', result.stdout) if result.returncode == 0 else None
        mic = int(match.group(1)) if match else None
        status = self.glados_status()
        self.ptt = 'Unavailable'
        config = status.get('config_path')
        if config:
            try:
                lines = Path(config).read_text().splitlines()
                wake = next((line.partition('=')[2].strip().strip('\"\'').lower() for line in reversed(lines)
                             if line.strip().startswith('WAKE_WORD_ENABLED=')), 'false')
                self.ptt = 'Wake word enabled' if wake == 'true' else 'Push-to-talk configured'
            except OSError:
                pass
        with self._lock:
            self.state.card, self.state.control_name, self.state.max_value = card, name, maximum
            self.state.current_value, self.state.current_percent = current, percent
            self.available, self.mic = True, mic
            if percent:
                self.restore_volume = percent
        self.note('Microphone gain unchanged; software lock affects GLaDOS only')

    def volume(self, target):
        self.perform(lambda: self.apply_volume(target))

    def apply_volume(self, target):
        """Shared UI/voice operation, including actual mixer readback."""
        if type(target) is not int or not 0 <= target <= 100:
            raise ValueError('Volume must be an integer from 0 to 100')
        def work():
            # Re-detect just before changing the original speaker control.
            card, name, maximum = self._detect_volume_control()
            value = max(0, min(maximum, target)) if self._is_unified_control(name) else self._curve_percent_to_device_value(target, maximum)
            result = self._run_command(['amixer', '-c', card, 'cset' if name.startswith('name=') else 'set', name, str(value)], timeout=8)
            if result.returncode:
                raise RuntimeError('Speaker volume change failed')
            self.refresh()
            if self.state.current_percent != target:
                self.note(f'Actual speaker volume {self.state.current_percent}%')
            else:
                self.note(f'Speaker volume {target}%')
            return self.state.current_percent
        return work()

    def toggle_recording(self):
        enabled = not self.glados_status().get('recording_enabled', False)
        self.confirmation.ask('Enable GLaDOS recording' if enabled else 'Lock GLaDOS recording',
            ['Stops / blocks GLaDOS launch.', 'Other programs are unaffected.'],
            lambda: self.perform(lambda: self._recording(enabled)))

    def _recording(self, enabled):
        self.set_recording(enabled)
        self.note('GLaDOS recording enabled' if enabled else 'GLaDOS recording locked; other apps unaffected')

    def items(self):
        status = self.glados_status()
        volume = f'{self.state.current_percent}%' if self.available else 'Unavailable'
        enabled = status.get('recording_enabled', False)
        return [('Back', 'Return to Home', self._request_exit),
                ('Refresh status', 'Read audio controls', self.refresh_async),
                ('Volume +10%', 'Current ' + volume, lambda: self.volume(min(100, self.state.current_percent + 10))),
                ('Volume -10%', 'Current ' + volume, lambda: self.volume(max(0, self.state.current_percent - 10))),
                ('Mute / restore', 'Current ' + volume, lambda: self.volume(0 if self.state.current_percent else self.restore_volume)),
                ('GLaDOS recording', 'Enabled' if enabled else 'Locked', self.toggle_recording),
                ('Microphone gain', 'Unavailable' if self.mic is None else f'{self.mic} (not a mute switch)',
                 lambda: self.note('Recording lock affects GLaDOS only; gain is never changed')),
                ('Audio device', self.state.card if self.available else 'Unavailable', self.refresh_async),
                ('Voice input mode', self.ptt, lambda: self.note(self.ptt))]
