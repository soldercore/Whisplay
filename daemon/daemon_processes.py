"""Linux process-group identity snapshots for children launched by this daemon."""
from pathlib import Path


def process_group_members(group_id):
    root = Path('/proc')
    if not root.is_dir():
        return None
    members = {}
    try:
        entries = list(root.iterdir())
    except OSError:
        return None
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            # comm may contain spaces and ')'; the rest starts after its last ')'.
            rest = (entry / 'stat').read_text().rsplit(') ', 1)[1].split()
            if int(rest[2]) == group_id:
                members[int(entry.name)] = int(rest[19])  # starttime prevents PID reuse.
        except PermissionError:
            return None  # Cannot prove the group is empty when /proc is restricted.
        except (OSError, ValueError, IndexError):
            continue  # A process can disappear between directory read and stat.
    return members
