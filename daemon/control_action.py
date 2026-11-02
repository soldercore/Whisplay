#!/usr/bin/python3 -I
"""Optional root-owned fixed-action helper. Never import daemon/user modules here."""
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid

SERVICES = {'ssh': 'ssh.service', 'ollama': 'ollama.service',
            'whisper': 'whisplay-whisper.service', 'piper': 'whisplay-piper.service'}
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C', 'HOME': '/root'}


def run(args, timeout=15):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                            check=False, env=ENV, stdin=subprocess.DEVNULL)
    if result.returncode:
        raise RuntimeError('Command rejected or failed')
    return result.stdout.strip()


def nm(*args, timeout=15):
    return run(['/usr/bin/nmcli', '--wait', '30', *args], timeout)


def dispatch(args, read_input):
    if len(args) == 2 and args[0] == 'wifi-radio' and args[1] in ('on', 'off'):
        nm('radio', 'wifi', args[1])
        if nm('-t', '-f', 'WIFI', 'radio') != ('enabled' if args[1] == 'on' else 'disabled'):
            raise RuntimeError('Radio state not confirmed')
    elif len(args) == 2 and args[0] == 'wifi-connect':
        identity = str(uuid.UUID(args[1]))
        if identity != args[1].lower():
            raise ValueError('Invalid profile UUID')
        if nm('-g', 'connection.type', 'connection', 'show', 'uuid', identity) != '802-11-wireless':
            raise ValueError('Only Wi-Fi profiles are allowed')
        nm('connection', 'up', 'uuid', identity, timeout=40)
    elif len(args) == 2 and args[0] == 'wifi-disconnect':
        device = args[1]
        if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,15}', device) or device.startswith('-'):
            raise ValueError('Invalid Wi-Fi device')
        if nm('-g', 'GENERAL.TYPE', 'device', 'show', device) != 'wifi':
            raise ValueError('Only Wi-Fi devices are allowed')
        nm('device', 'disconnect', device)
    elif args == ['wifi-join']:
        payload = json.loads(read_input(4097))
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
        identity = str(uuid.uuid4())
        # No secret ever appears in argv, logs or error messages. A failed join
        # leaves only this newly created profile, never deletes existing profiles.
        nm('connection', 'add', 'type', 'wifi', 'ifname', '*', 'con-name', 'Whisplay-' + identity[:8],
           'connection.uuid', identity, 'ssid', ssid)
        if security != 'open':
            nm('connection', 'modify', 'uuid', identity, 'wifi-sec.key-mgmt', security)
        with tempfile.TemporaryDirectory(prefix='whisplay-secret-', dir='/run') as directory:
            path = os.path.join(directory, 'password')
            with open(path, 'x', encoding='utf-8') as secret:
                os.chmod(path, 0o600)
                secret.write('802-11-wireless-security.psk:' + password + '\n')
            nm('connection', 'up', 'uuid', identity, 'passwd-file', path, timeout=40)
    elif len(args) == 3 and args[0] == 'service' and args[1] in ('start', 'restart') and args[2] in SERVICES:
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
        dispatch(sys.argv[1:], sys.stdin.read)
    except Exception:
        # subprocess/JSON exceptions can contain credentials. Never echo them.
        print('Control action failed; permissions, device or service unavailable', file=sys.stderr)
        return 1
    print('Accepted')
    return 0


if __name__ == '__main__':
    sys.exit(main())
