"""No caller-controlled executable or shell. Installation is a separate approval."""
import json

HELPER = '/usr/lib/whisplay/control-action'


def control(run, *args, payload=None):
    kwargs = {'timeout': 50}
    if payload is not None:
        kwargs['input_text'] = json.dumps(payload)
    result = run(['/usr/bin/sudo', '-n', HELPER, *args], **kwargs)
    if result.returncode:
        raise RuntimeError('Action failed: permissions/device/service unavailable')
    return result
