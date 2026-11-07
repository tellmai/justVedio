"""Cumulative count of completed learning sessions, kept across batches.

Every successful completion adds one, even when the same person learns again.
The counter lives beside the application data so a new batch never resets it.
When the counter file does not exist yet (for example after upgrading from an
older build), the existing ``学习完成`` workbooks seed the starting value.
"""
import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path

from . import paths
from .daily import completed_entries
from .records import read_outcome_file

_STORAGE_KEY = 'completed_learning'
_VERSION = 1
_LOCK = threading.Lock()


def _read_total(path):
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return None
    value = payload.get(_STORAGE_KEY) if isinstance(payload, dict) else None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _write_total(path, total):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    try:
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump({'version': _VERSION, 'application': 'justVedio',
                       _STORAGE_KEY: total, 'updated': datetime.now().isoformat(timespec='seconds')},
                      stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def _seed_from_completed_records(base=None):
    """Count unique completed identities per day across ledger and workbooks."""
    seen = set(completed_entries(base))
    folder = paths.completed_folder(base)
    if not folder.is_dir():
        return len(seen)
    for target in sorted(folder.glob('学习完成_*.xlsx')):
        if '.tmp' in target.name:
            continue
        match = re.match(r'学习完成_(\d{8})', target.stem)
        day = match.group(1) if match else target.stem
        for person in read_outcome_file(target):
            identity = person['id_number']
            if identity:
                seen.add((day, identity))
    return len(seen)


def _load_or_seed(path, base=None):
    if path.is_file():
        total = _read_total(path)
        if total is not None:
            return total, False
    return _seed_from_completed_records(base), True


def load_completed_learning(base=None):
    """Return the cumulative completion count, seeding it once if necessary."""
    path = paths.lifetime_stats_file(base)
    with _LOCK:
        total, seed = _load_or_seed(path, base)
        if seed:
            try:
                _write_total(path, total)
            except OSError:
                pass
        return total


def record_completed_learning(base=None):
    """Add one completed learning session and return the new cumulative count."""
    path = paths.lifetime_stats_file(base)
    with _LOCK:
        total, _ = _load_or_seed(path, base)
        total += 1
        try:
            _write_total(path, total)
        except OSError:
            # Learning completion itself must never fail because statistics
            # could not be written; the next read rebuilds from saved records.
            pass
        return total
