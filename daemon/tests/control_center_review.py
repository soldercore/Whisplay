"""Off-screen review only: fake board, synthetic values, mocked mutations.

Run on a machine with Pillow/numpy. --read-only adds actual public metrics and
fixed status queries; it never starts the daemon, BlueZ agent or an app.
"""
import argparse
import json
import os
from pathlib import Path
import statistics
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageDraw
from cyber_ui.preview import FakeBoard
from cyber_ui import FallbackDesktopRenderer
from daemon_renderer import DesktopRenderer
from daemon_models import AppRecord
from daemon_processes import process_group_members
from internal_apps.manager import InternalAppManager
from internal_apps.device_info import linux_metrics
from internal_apps.wifi_app import WifiNetwork
import test_control_navigation as navigation


def summary(samples):
    ordered = sorted(samples)
    return {'samples': len(samples), 'median_ms': round(statistics.median(samples), 3),
            'p95_ms': round(ordered[min(len(samples)-1, int(len(samples)*.95))], 3),
            'maximum_ms': round(max(samples), 3)}


def measure(action, repetitions=50):
    times = []
    for _ in range(repetitions):
        started = time.perf_counter()
        action()
        times.append((time.perf_counter() - started) * 1000)
    return summary(times)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    parser.add_argument('--read-only', action='store_true')
    options = parser.parse_args()
    out = Path(options.out)
    out.mkdir(parents=True, exist_ok=True)
    d = navigation.NavigationTests().daemon()
    d.board = FakeBoard()
    d.board.set_rgb = Mock()
    d.board.set_backlight = Mock()
    d.status_poller = SimpleNamespace(wifi_signal_level=3, battery_level=None)
    d._brightness, d._led_rgb = 60, (0, 0, 0)
    manager = InternalAppManager(glados_status=lambda: {'registered': True, 'recording_enabled': True},
        get_display=lambda: {'brightness': 60, 'rgb': (0, 0, 0)})
    for app in manager._apps.values():
        app.refresh_async = Mock()  # No hardware, subprocess or network activity.
        app._run_command = Mock(return_value=SimpleNamespace(returncode=0, stdout='', stderr=''))
    d.internal_apps = manager
    d.apps = {app.app_id: app for app in manager.builtin_apps()}
    d.apps['whisplay-ai-chatbot'] = AppRecord('whisplay-ai-chatbot', 'GLaDOS')
    d.foreground_app_id = None
    script_dir = str(Path(__file__).resolve().parents[1])
    renderer = FallbackDesktopRenderer(d.board, script_dir)
    d.desktop = renderer
    d._render_desktop = lambda: renderer.render(d._home_apps(), d.selected_app_index)
    d._render_internal_app = lambda: renderer.render_internal_app(manager.get_view_model(d.foreground_app_id))
    frames = []

    def save(name, view=None):
        if view is None:
            d._render_desktop()
        else:
            renderer.render_internal_app(view)
        image = d.board.image()
        image.save(out / (name + '.png'))
        frames.append((name, image))
        # Both renderer paths consume the same live view model.
        if view:
            DesktopRenderer(d.board, script_dir).render_internal_app(view)
            d.board.image().save(out / (name + '-classic.png'))

    save('01-home')
    save('02-network', manager.network.view_model())
    wifi = manager.wifi
    wifi.radio, wifi.device = True, 'wlan0'
    wifi.state.status = 'Radio on; hold Refresh to update'
    wifi.state.networks = [WifiNetwork('Synthetic Lab', 83, 'WPA2', True, '192.0.2.5')]
    wifi.saved = [('12345678-1234-1234-1234-123456789abc', 'Saved Lab')]
    wifi.state.selected_index = 2
    save('03-wifi-radio', wifi.view_model())
    wifi.state.selected_index = 6
    save('04-wifi-status', wifi.view_model())
    wifi.select_network(WifiNetwork('Synthetic protected AP', 60, 'WPA2'))
    save('05-password-rows', wifi.view_model())
    wifi._key_open(1)
    wifi.key_index = 2
    save('06-password-keys', wifi.view_model())
    wifi.deactivate()
    wifi.ask('Disable Wi-Fi', lambda: None)
    save('07-wifi-confirm', wifi.view_model())
    wifi.deactivate()
    audio = manager.volume
    audio.available, audio.mic, audio.ptt = True, 80, 'Push-to-talk configured'
    audio.state.current_percent, audio.state.card = 80, '2 / whisplaysound'
    audio.state.status = 'Microphone gain unchanged'
    audio.state.selected_index = 3
    save('08-audio', audio.view_model())
    audio.toggle_recording()
    save('09-recording-lock', audio.view_model())
    save('10-display', manager.display.view_model())
    manager.information.metrics = dict(cpu=12.3, temperature=48.2, memory_used=3*1024**3,
        memory_available=12*1024**3, disk_used=20*1024**3, disk_free=30*1024**3,
        uptime=10000, battery=None, throttled=0)
    manager.information.state.selected_index = 2
    save('11-system-info', manager.information.view_model())
    manager.services.statuses = {'ssh': 'Running', 'ollama': 'Running', 'whisper': 'Starting',
                                 'piper': 'Failed', 'daemon': 'Running'}
    manager.services.state.selected_index = 4
    save('12-services', manager.services.view_model())
    manager.services.ask_service('ssh', 'restart')
    save('13-ssh-confirm', manager.services.view_model())
    manager.system.ask_power('poweroff')
    save('14-power-confirm', manager.system.view_model())
    wifi.ask('Join Wi-Fi', lambda: None, target='W' * 32)
    save('15-long-ssid-confirm', wifi.view_model())
    sheet = Image.new('RGB', (4*240, 4*300), '#172017')
    draw = ImageDraw.Draw(sheet)
    for index, (name, frame) in enumerate(frames):
        x, y = index % 4 * 240, index // 4 * 300
        sheet.paste(frame, (x, y+20))
        draw.text((x+5, y+3), name, fill='white')
    sheet.save(out / 'control-center-review.png')

    def short_press():
        d._button_press_started_at = time.time() - .05
        d._on_button_released()
    timings = {'home_input_plus_offscreen_render': measure(short_press)}
    # A deliberately blocked worker must not stall button feedback or rendering.
    blocked = threading.Event()
    manager.network._spawn_worker = manager._spawn_worker
    manager.network.perform(lambda: blocked.wait(timeout=5), 'Synthetic slow action')
    d.foreground_app_id = manager.network.APP_ID
    timings['menu_input_plus_offscreen_render_while_worker_blocked'] = measure(short_press)
    blocked.set()
    manager._threads['menu-whisplay-network'].join(timeout=1)
    d.foreground_app_id = None
    timings['mock_power_dispatch'] = measure(lambda: manager.system._run_power_action('reboot'))
    timings['owned_group_read_only_snapshot'] = measure(lambda: process_group_members(os.getpgrp()), 5)
    if options.read_only:
        def run(command, timeout=10, **kwargs):
            return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        timings['actual_public_linux_metrics'] = measure(lambda: linux_metrics(run), 5)
        manager.services._run_command = run
        timings['actual_fixed_service_status_queries'] = measure(manager.services.refresh, 3)
        wifi._run_command = run
        timings['actual_read_only_wifi_status_queries'] = measure(wifi.refresh, 3)
    (out / 'timings.json').write_text(json.dumps(timings, indent=2) + '\n')
    print(json.dumps(timings, indent=2))


if __name__ == '__main__':
    main()
