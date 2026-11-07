"""One deduplicated learning status per identity per local day.

The ledger is the authoritative daily roster used by the UI and the next
batch. Completed always wins over failed; the same identity is stored once.
Legacy per-batch workbooks from the same day are folded in when the ledger is
first created, so upgrading in the middle of a day does not re-run people who
already finished.
"""
import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path

from . import paths
from .records import read_outcome_people

FOLDER = '每日学习'
_COMPLETED = 'completed'
_FAILED = 'failed'
_LOCK = threading.Lock()


def day_key(when=None):
    value = when or datetime.now()
    return value.strftime('%Y-%m-%d')


def daily_file(day=None, base=None):
    return paths.results_folder(base) / FOLDER / f'{day or day_key()}.json'


def _read(path):
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return {}
    people = payload.get('people') if isinstance(payload, dict) else None
    if not isinstance(people, dict):
        return {}
    result = {}
    for identity, info in people.items():
        if not isinstance(info, dict):
            continue
        status = info.get('status')
        if status not in {_COMPLETED, _FAILED}:
            continue
        result[str(identity)] = {
            'status': status,
            'source': 'already' if info.get('source') == 'already' else 'learned',
            'reason': str(info.get('reason') or ''),
            'name': str(info.get('name') or ''),
            'district': str(info.get('district') or ''),
            'updated': str(info.get('updated') or ''),
        }
    return result


def _write(path, day, people):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    payload = {'version': 1, 'application': 'justVedio', 'date': day,
               'updated': datetime.now().isoformat(timespec='seconds'),
               'people': people}
    try:
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def _from_workbooks(day, base=None):
    token = day.replace('-', '')
    people = {}
    for person in read_outcome_people(paths.completed_folder(base), '学习完成', token):
        identity = person['id_number']
        people[identity] = {'status': _COMPLETED, 'source': 'learned', 'reason': '',
                            'name': person['name'], 'district': person['district'],
                            'updated': ''}
    for person in read_outcome_people(paths.failed_folder(base), '学习失败', token):
        identity = person['id_number']
        if identity in people:
            continue
        people[identity] = {'status': _FAILED, 'source': 'learned', 'reason': '本日未完成',
                            'name': person['name'], 'district': person['district'],
                            'updated': ''}
    return people


def load_day(day=None, base=None):
    """Return the day's identity -> status mapping, seeding it if needed."""
    day = day or day_key()
    path = daily_file(day, base)
    with _LOCK:
        if path.is_file():
            people = _read(path)
            if people:
                return people
        people = _from_workbooks(day, base)
        try:
            _write(path, day, people)
        except OSError:
            pass
        return people


def statuses_for(candidates, day=None, base=None):
    people = load_day(day, base)
    return {candidate.id_number: people[candidate.id_number]
            for candidate in candidates if candidate.id_number in people}


def record_person(record, day=None, base=None):
    """Persist a terminal status; completed always wins over failed."""
    if record.status not in {_COMPLETED, 'failed', 'stopped'}:
        return
    day = day or day_key()
    path = daily_file(day, base)
    with _LOCK:
        people = _read(path) if path.is_file() else {}
        if not people:
            people = _from_workbooks(day, base)
        identity = record.candidate.id_number
        existing = people.get(identity)
        if record.status == _COMPLETED:
            already = bool(getattr(record, 'already_completed', False))
            if existing and existing.get('source') == 'learned':
                already = False
            people[identity] = {
                'status': _COMPLETED,
                'source': 'already' if already else 'learned',
                'reason': '' if already else '本日已完成',
                'name': record.candidate.name,
                'district': record.candidate.district,
                'updated': datetime.now().isoformat(timespec='seconds'),
            }
        elif not (existing and existing.get('status') == _COMPLETED):
            people[identity] = {
                'status': _FAILED,
                'source': 'learned',
                'reason': record.reason or '本日未完成',
                'name': record.candidate.name,
                'district': record.candidate.district,
                'updated': datetime.now().isoformat(timespec='seconds'),
            }
        try:
            _write(path, day, people)
        except OSError:
            pass


def completed_entries(base=None):
    """Unique (day, identity) actual learning completions for cumulative stats."""
    result = set()
    folder = paths.results_folder(base) / FOLDER
    if not folder.is_dir():
        return result
    for target in folder.glob('*.json'):
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}\.json', target.name):
            continue
        day = target.stem
        for identity, info in _read(target).items():
            if info.get('status') == _COMPLETED and info.get('source') != 'already':
                result.add((day, identity))
    return result
