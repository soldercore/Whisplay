#!/usr/bin/python3 -I
"""Explicit installer only. No daemon/service/radio operations and no imports of user code."""
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import sys
import tempfile

TARGET = Path('/usr/lib/whisplay/control-action')
RULE = Path('/etc/sudoers.d/whisplay-control-center')
SOURCE = Path(__file__).with_name('control_action.py')
ENV = {'PATH': '/usr/sbin:/usr/bin:/sbin:/bin', 'LC_ALL': 'C', 'HOME': '/root'}


def trusted_directory(path):
    for parent in (path, *path.parents):
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            raise RuntimeError('Install parents must be root-owned, non-writable real directories')


def install(user):
    if os.geteuid() != 0 or not re.fullmatch(r'[a-z_][a-z0-9_-]*\$?', user):
        raise ValueError('Run as root with one daemon user')
    if pwd.getpwnam(user).pw_uid == 0:
        raise ValueError('Daemon must be unprivileged')
    trusted_directory(TARGET.parent.parent)
    trusted_directory(RULE.parent)
    if TARGET.parent.exists() or TARGET.parent.is_symlink():
        trusted_directory(TARGET.parent)
    for path in (TARGET, RULE):
        if path.exists() or path.is_symlink():
            raise RuntimeError('Existing helper/rule must be preserved and reviewed')
    data = SOURCE.read_bytes()
    if not data.startswith(b'#!/usr/bin/python3 -I\n'):
        raise ValueError('Helper requires isolated system Python and canonical LF source')
    compile(data, str(SOURCE), 'exec')  # Syntax validation only; never import/execute it.
    policy = (user + ' ALL=(root) NOPASSWD: /usr/lib/whisplay/control-action\n').encode('ascii')
    created = []
    try:
        # Validate the exact policy before installing anything.
        with tempfile.NamedTemporaryFile(dir='/run', prefix='whisplay-sudoers-', mode='wb') as temp:
            temp.write(policy);temp.flush()
            subprocess.run(['/usr/sbin/visudo', '-cf', temp.name], check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=ENV, cwd='/', timeout=5)
        try:
            TARGET.parent.mkdir(mode=0o755)
        except FileExistsError:
            pass
        else:
            os.chmod(TARGET.parent, 0o755)
        trusted_directory(TARGET.parent)
        for path, content, mode in ((TARGET, data, 0o755), (RULE, policy, 0o440)):
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
            created.append(path)
            with os.fdopen(fd, 'wb') as output:
                output.write(content);output.flush();os.fsync(output.fileno());os.fchmod(output.fileno(), mode)
            info = path.lstat()
            if info.st_uid != 0 or not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != mode:
                raise RuntimeError('Installed ownership or mode mismatch')
    except BaseException:
        for path in reversed(created):
            path.unlink()  # Only files exclusively created by this failed installation.
        raise


if __name__ == '__main__':
    try:
        if len(sys.argv) != 2:
            raise ValueError('One daemon user required')
        install(sys.argv[1])
    except Exception:
        print('Helper installation failed; existing files and policies were not replaced.', file=sys.stderr)
        sys.exit(1)
    print('Narrow helper installed. No service, radio or existing sudo policy changed.')
