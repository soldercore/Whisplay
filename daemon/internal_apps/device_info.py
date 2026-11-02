"""Lightweight public Linux metrics. Missing data is None, never an invented zero."""
import subprocess
from pathlib import Path
import shutil
import time

from .menu import MenuApp


def cpu_ticks():
    try:
        fields = Path('/proc/stat').read_text().splitlines()[0].split()
        if fields[0] != 'cpu' or len(fields) < 9:
            return None
        values = [int(value) for value in fields[1:9]]
        return sum(values), values[3] + values[4]
    except (OSError, ValueError, IndexError):
        return None


def linux_metrics(run, battery=None):
    result = dict(cpu=None, temperature=None, memory_used=None, memory_available=None,
                  disk_used=None, disk_free=None, uptime=None, throttled=None, battery=battery)
    first = cpu_ticks()
    time.sleep(.1)  # Worker only; never blocks a physical button or renderer.
    second = cpu_ticks()
    if first and second and second[0] > first[0]:
        elapsed, idle = second[0] - first[0], second[1] - first[1]
        if 0 <= idle <= elapsed:
            result['cpu'] = 100 * (elapsed - idle) / elapsed
    try:
        kind = Path('/sys/class/thermal/thermal_zone0/type').read_text().lower()
        value = int(Path('/sys/class/thermal/thermal_zone0/temp').read_text()) / 1000
        if ('cpu' in kind or 'soc' in kind) and -40 <= value <= 200:
            result['temperature'] = value
    except (OSError, ValueError):
        pass
    try:
        memory = {}
        for line in Path('/proc/meminfo').read_text().splitlines():
            key, _, rest = line.partition(':')
            if key in ('MemTotal', 'MemAvailable'):
                memory[key] = int(rest.split()[0]) * 1024
        total, available = memory['MemTotal'], memory['MemAvailable']
        if 0 <= available <= total:
            result.update(memory_used=total - available, memory_available=available)
    except (OSError, ValueError, KeyError, IndexError):
        pass
    try:
        disk = shutil.disk_usage('/')
        result.update(disk_used=disk.used, disk_free=disk.free)
    except OSError:
        pass
    try:
        value = float(Path('/proc/uptime').read_text().split()[0])
        if value >= 0:
            result['uptime'] = value
    except (OSError, ValueError, IndexError):
        pass
    command = shutil.which('vcgencmd')
    if command:
        try:
            output = run([command, 'get_throttled'], timeout=2)
            if output.returncode == 0 and output.stdout.strip().startswith('throttled=0x'):
                result['throttled'] = int(output.stdout.strip().split('=', 1)[1], 16)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            pass
    return result


def quantity(value, unit):
    return 'Unavailable' if value is None else f'{value:.1f} {unit}'


def gib(value):
    return 'Unavailable' if value is None else f'{value / 1024**3:.2f} GiB'


class InformationApp(MenuApp):
    APP_ID, TITLE, ICON, PRIORITY = 'whisplay-information', 'System Info', 'SI', 155

    def __init__(self, *args, battery=lambda: None):
        super().__init__(*args)
        self._battery = battery
        self.metrics = {}

    def refresh(self):
        metrics = linux_metrics(self._run_command, self._battery())
        with self._lock:
            self.metrics = metrics
        self.note('Actual measurements; hold Refresh to resample')

    def items(self):
        m = self.metrics
        up = m.get('uptime')
        uptime = 'Unavailable' if up is None else f'{int(up)//3600}h {int(up)//60%60}m'
        throttle = m.get('throttled')
        throttling = 'Unavailable' if throttle is None else ('None reported' if throttle == 0 else f'Flags 0x{throttle:x}')
        rows = [('CPU temperature', quantity(m.get('temperature'), 'C')),
                ('CPU utilization', quantity(m.get('cpu'), '%')),
                ('RAM used', gib(m.get('memory_used'))), ('RAM available', gib(m.get('memory_available'))),
                ('Storage used', gib(m.get('disk_used'))), ('Storage free', gib(m.get('disk_free'))),
                ('Uptime', uptime), ('Battery', quantity(m.get('battery'), '%')),
                ('Throttling', throttling)]
        return super().items() + [('Refresh', 'Read current measurements', self.refresh_async)] + [
            (title, value, lambda value=value: self.note(value)) for title, value in rows]
