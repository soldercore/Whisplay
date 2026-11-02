"""No caller-controlled executable or shell. Installation is a separate approval."""
import json

class ControlBlocked(RuntimeError):
    pass


HELPER = '/usr/lib/whisplay/control-action'


def control(run, *args, payload=None):
    kwargs = {'timeout': 50}
    if payload is not None:
        kwargs['input_text'] = json.dumps(payload)
    result = run(['/usr/bin/sudo', '-n', HELPER, *args], **kwargs)
    if result.returncode:
        if result.returncode == 3 and (result.stderr or '').strip() == '{"error":"ssh_session_active"}':
            raise ControlBlocked('Active SSH session: disruptive network changes and SSH restart are blocked. Disconnect SSH before local confirmation.')
        raise RuntimeError('Action failed: permissions/device/service unavailable')
    return result
