#!/usr/bin/python3 -I
"""Optional root-owned fixed-action helper. Never import daemon/user modules here."""
from contextlib import contextmanager
from pathlib import Path
import stat
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid

SERVICES = {'ssh': 'ssh.service', 'ollama': 'ollama.service',
            'whisper': 'whisplay-whisper.service', 'piper': 'whisplay-piper.service'}
PROC = Path('/proc')
PROTOCOL = 2


class ControlBlocked(RuntimeError):
    pass


ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C', 'HOME': '/root'}


def run(args, timeout=15):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                            check=False, env=ENV, stdin=subprocess.DEVNULL, cwd='/')
    if result.returncode:
        raise RuntimeError('Command rejected or failed')
    return result.stdout.strip()


def nm(*args, timeout=15):
    return run(['/usr/bin/nmcli', '--wait', '30', *args], timeout)



def ssh_active():
    """Detect established OpenSSH server sockets, including nonstandard ports.

    Unreadable process/network state fails closed; never echo socket/user data.
    """
    sockets = set()
    for name in ('tcp', 'tcp6'):
        for line in (PROC / 'net' / name).read_text().splitlines()[1:]:
            fields = line.split()
            if len(fields) < 10:
                raise RuntimeError('Network state unavailable')
            if fields[3] == '01':
                sockets.add(fields[9])
    for process in PROC.iterdir():
        if not process.name.isdigit():
            continue
        try:
            if not (process / 'comm').read_text().strip().startswith('sshd'):
                continue
            for descriptor in (process / 'fd').iterdir():
                try:
                    target = os.readlink(descriptor)
                except FileNotFoundError:
                    continue
                if target.startswith('socket:[') and target[8:-1] in sockets:
                    return True
        except (FileNotFoundError, ProcessLookupError):
            continue  # Process exited; permission/read failures are not ignored.
    return False


def guard_ssh():
    if ssh_active():
        raise ControlBlocked('ssh_session_active')


def bus(method, *args):
    return run(['/usr/bin/busctl', '--system', '--timeout=3', 'call',
                'org.freedesktop.NetworkManager', '/org/freedesktop/NetworkManager',
                'org.freedesktop.NetworkManager', method, *args], timeout=5)


def object_path(reply, kind):
    match = re.fullmatch(r'o "(/org/freedesktop/NetworkManager/' + kind + r'/[0-9]+)"', reply)
    if not match:
        raise RuntimeError('Checkpoint response unavailable')
    return match[1]


@contextmanager
def wifi_checkpoint():
    # Only Wi-Fi interfaces. Never destroy another application's checkpoint or
    # delete existing/new profiles on rollback. NM owns the timer if we crash.
    devices = []
    for line in nm('-t', '-f', 'DEVICE,TYPE', 'device').splitlines():
        fields = line.rsplit(':', 1)
        if len(fields) == 2 and fields[1] == 'wifi':
            if not re.fullmatch(r'[A-Za-z0-9_.-]{1,15}', fields[0]) or fields[0].startswith('-'):
                raise RuntimeError('Wi-Fi device unavailable')
            devices.append(object_path(bus('GetDeviceByIpIface', 's', fields[0]), 'Devices'))
    if not devices or len(devices) > 8:
        raise RuntimeError('Wi-Fi recovery unavailable')
    checkpoint = object_path(bus('CheckpointCreate', 'aouu', str(len(devices)), *devices, '120', '0'), 'Checkpoint')
    try:
        guard_ssh()  # Recheck just before mutation; initial guard precedes setup.
    except BaseException:
        # Nothing changed yet: do not risk restoring a newly established session.
        bus('CheckpointDestroy', 'o', checkpoint)
        raise
    try:
        yield
        bus('CheckpointDestroy', 'o', checkpoint)
    except BaseException:
        try:
            bus('CheckpointRollback', 'o', checkpoint)
        except Exception:
            pass  # Do not commit: the independent 120-second NM timer remains.
        raise


@contextmanager
def operation_lock():
    import fcntl
    fd = os.open('/run/whisplay-control.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        info = os.fstat(fd)
        if info.st_uid != 0 or not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
            raise RuntimeError('Unsafe control lock')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def dispatch(args, read_input):
    if args == ['check-ssh']:
        guard_ssh()
    elif args == ['wifi-scan']:
        nm('device', 'wifi', 'rescan')
    elif len(args) == 2 and args[0] == 'wifi-radio' and args[1] in ('on', 'off'):
        if args[1] == 'off':
            guard_ssh()
        nm('radio', 'wifi', args[1])
        if nm('-t', '-f', 'WIFI', 'radio') != ('enabled' if args[1] == 'on' else 'disabled'):
            raise RuntimeError('Radio state not confirmed')
    elif len(args) == 2 and args[0] == 'wifi-connect':
        identity = str(uuid.UUID(args[1]))
        if identity != args[1].lower():
            raise ValueError('Invalid profile UUID')
        if nm('-g', 'connection.type', 'connection', 'show', 'uuid', identity) != '802-11-wireless':
            raise ValueError('Only Wi-Fi profiles are allowed')
        guard_ssh()
        with wifi_checkpoint():
            nm('connection', 'up', 'uuid', identity, timeout=40)
    elif len(args) == 2 and args[0] == 'wifi-disconnect':
        device = args[1]
        if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,15}', device) or device.startswith('-'):
            raise ValueError('Invalid Wi-Fi device')
        if nm('-g', 'GENERAL.TYPE', 'device', 'show', device) != 'wifi':
            raise ValueError('Only Wi-Fi devices are allowed')
        guard_ssh()
        with wifi_checkpoint():
            nm('device', 'disconnect', device)
    elif args == ['wifi-join']:
        raw = read_input(4097)
        if len(raw.encode('utf-8')) > 4096:
            raise ValueError('Network request too large')
        def unique(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise ValueError('Duplicate network parameter')
                result[key] = value
            return result
        payload = json.loads(raw, object_pairs_hook=unique)
        if not isinstance(payload, dict) or set(payload) != {'ssid', 'password', 'security'}:
            raise ValueError('Invalid network request')
        ssid, password, security = payload['ssid'], payload['password'], payload['security']
        if not isinstance(ssid, str) or not 1 <= len(ssid.encode('utf-8')) <= 32 or ssid.startswith('-'):
            raise ValueError('Invalid SSID')
        if not isinstance(password, str) or any(ord(c) < 32 or ord(c) == 127 for c in ssid + password):
            raise ValueError('Invalid network text')
        if security not in ('open', 'wpa-psk', 'sae'):
            raise ValueError('Unsupported network security')
        if security == 'open' and password or security != 'open' and not (
                8 <= len(password) <= 63 and all(32 <= ord(c) <= 126 for c in password)
                or len(password) == 64 and re.fullmatch('[0-9a-fA-F]{64}', password)):
            raise ValueError('Invalid WPA passphrase')
        guard_ssh()
        with wifi_checkpoint():
            identity = str(uuid.uuid4())
            # No secret ever appears in argv, logs or error messages. A failed join
            # leaves only this newly created profile, never deletes existing profiles.
            nm('connection', 'add', 'type', 'wifi', 'ifname', '*', 'con-name', 'Whisplay-' + identity[:8],
               'connection.uuid', identity, 'connection.autoconnect', 'no', 'ssid', ssid)
            if security != 'open':
                nm('connection', 'modify', 'uuid', identity, 'wifi-sec.key-mgmt', security)
            with tempfile.TemporaryDirectory(prefix='whisplay-secret-', dir='/run') as directory:
                path = os.path.join(directory, 'password')
                with open(path, 'x', encoding='utf-8') as secret:
                    os.chmod(path, 0o600)
                    secret.write('802-11-wireless-security.psk:' + password + '\n')
                nm('connection', 'up', 'uuid', identity, 'passwd-file', path, timeout=40)
    elif len(args) == 3 and args[0] == 'service' and args[1] in ('start', 'restart') and args[2] in SERVICES:
        if args[1:] == ['restart', 'ssh']:
            guard_ssh()
        run(['/usr/bin/systemctl', args[1], SERVICES[args[2]]], timeout=45)
        if run(['/usr/bin/systemctl', 'show', '-p', 'ActiveState', '--value', SERVICES[args[2]]]) != 'active':
            raise RuntimeError('Service is not active')
    elif len(args) == 2 and args[0] == 'power' and args[1] in ('reboot', 'poweroff'):
        run(['/usr/bin/systemctl', args[1]])
    else:
        raise ValueError('Action is not allowed')


def main():
    try:
        if os.geteuid() != 0:
            raise PermissionError('Root helper is not installed/authorized')
        if sys.argv[1:] == ['capabilities']:
            print(json.dumps({'api': PROTOCOL, 'ssh_guard': True, 'wifi_checkpoint_seconds': 120,
                              'actions': ['wifi-scan', 'wifi-radio', 'wifi-connect', 'wifi-disconnect', 'wifi-join', 'service', 'power']}))
            return 0
        with operation_lock():
            dispatch(sys.argv[1:], sys.stdin.read)
    except ControlBlocked:
        print('{"error":"ssh_session_active"}', file=sys.stderr)
        return 3
    except Exception:
        # subprocess/JSON exceptions can contain credentials. Never echo them.
        print('Control action failed; permissions, device or service unavailable', file=sys.stderr)
        return 1
    print('Accepted')
    return 0


if __name__ == '__main__':
    sys.exit(main())
