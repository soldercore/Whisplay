"""Local daemon owner is administrator; tracked children have only app rights.

Never trust app_id, UID or session claims supplied in JSON. UID/PID come from
the kernel; app identity comes from a live daemon-owned process group.
"""
import hmac
import os
import socket
import struct


READS = {'health.ping', 'app.list', 'button.get_state'}
ADMIN = {'app.register', 'app.launch', 'app.autostart.set', 'app.exit.request'}
APP = {'app.focus.acquire', 'app.focus.release', 'framebuffer.acquire', 'events.subscribe'}
HARDWARE = {'backlight.set', 'led.set', 'led.fade'}


def peer_identity(connection):
    try:
        pid, uid, _ = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if pid <= 0 or uid != os.getuid():
            raise PermissionError('Daemon owner identity required')
        return pid
    except (AttributeError, OSError, ValueError, struct.error) as exc:
        raise PermissionError('Verified local Unix peer required') from exc


def tracked_app(daemon, pid):
    try:
        group = os.getpgid(pid)
    except OSError as exc:
        raise PermissionError('Peer process unavailable') from exc
    for app in daemon.apps.values():
        if app.is_running() and app.process.pid == group:
            return app
    return None


def authorize(daemon, command, payload, connection):
    pid = peer_identity(connection)  # Also required for read-only and unknown commands.
    if command in READS or command.startswith('control.'):
        return  # control.* applies its additional foreground/process policy.
    if command not in ADMIN | APP | HARDWARE:
        raise PermissionError('Unsupported IPC operation')
    caller = tracked_app(daemon, pid)
    app_id = payload.get('app_id')
    if command in ADMIN:
        if caller is None:
            return  # Explicitly trusted owner-UID management client, not an app.
        if command == 'app.register' and app_id == caller.app_id:
            # Runtime discovery may refresh presentation, never executable policy.
            if set(payload) - {'app_id', 'display_name', 'icon', 'persist'}:
                raise PermissionError('Apps cannot modify launch policy')
            if 'persist' in payload and (type(payload['persist']) is not bool or payload['persist'] != caller.persist):
                raise PermissionError('Apps cannot modify registration persistence')
            return
        if command == 'app.exit.request' and app_id == caller.app_id:
            return
        raise PermissionError('Application cannot perform administrative IPC')
    if command in HARDWARE:
        if caller is not None and daemon.foreground_app_id == caller.app_id:
            return
        if caller is None and daemon.foreground_app_id is None:
            return  # Owner's diagnostic client at Home only.
        raise PermissionError('Foreground application required')
    if command == 'events.subscribe' and not app_id and caller is None:
        return  # Owner diagnostics; events never expose session tokens.
    if caller is None or app_id != caller.app_id:
        raise PermissionError('Tracked application ownership required')
    if command in ('app.focus.release', 'framebuffer.acquire'):
        token = payload.get('session_token')
        if not isinstance(token, str) or not token or not caller.session_token or not hmac.compare_digest(token, caller.session_token):
            raise PermissionError('Invalid application session')
