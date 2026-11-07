"""Per-day Excel records of learned and failed identities."""
import os
from datetime import datetime
from pathlib import Path

from . import paths

HEADERS = ('所在的区县', '姓名', '身份证号')


def _write_workbook(target, people):
    """Write one 3-column workbook atomically."""
    from openpyxl import Workbook
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    book = Workbook()
    try:
        sheet = book.active
        sheet.title = '人员信息'
        sheet.append(list(HEADERS))
        for person in people:
            values = [person['district'], person['name'], person['id_number']]
            sheet.append(values)
            for cell, value in zip(sheet[sheet.max_row], values):
                if isinstance(value, str):
                    cell.data_type, cell.number_format = 's', '@'
        for column, width in zip('ABC', (20, 18, 28)):
            sheet.column_dimensions[column].width = width
        sheet.freeze_panes = 'A2'
        temporary = target.with_suffix('.tmp.xlsx')
        book.save(temporary)
        os.replace(temporary, target)
    finally:
        book.close()
    return target


def _write(folder, prefix, stamp, records):
    folder = Path(folder)
    target = folder / f'{prefix}_{stamp}.xlsx'
    if target.exists():
        suffix = 2
        while (folder / f'{prefix}_{stamp}_{suffix}.xlsx').exists():
            suffix += 1
        target = folder / f'{prefix}_{stamp}_{suffix}.xlsx'
    people = [{'district': record.candidate.district,
               'name': record.candidate.name,
               'id_number': record.candidate.id_number} for record in records]
    return _write_workbook(target, people)


def read_outcome_file(target):
    """Read district/name/identity rows from one outcome workbook."""
    from openpyxl import load_workbook
    people = []
    try:
        book = load_workbook(target, read_only=True, data_only=True)
    except Exception:
        return people
    try:
        sheet = book.active
        for row in sheet.iter_rows(min_row=2, values_only=True):
            if not row:
                continue
            district = '' if row[0] is None else str(row[0]).strip()
            name = '' if len(row) < 2 or row[1] is None else str(row[1]).strip()
            identity = '' if len(row) < 3 or row[2] is None else str(row[2]).strip()
            if identity:
                people.append({'district': district, 'name': name, 'id_number': identity})
    except Exception:
        pass
    finally:
        book.close()
    return people


def read_outcome_people(folder, prefix, day_token):
    """Read every file for a day, including older timestamped batches."""
    folder = Path(folder)
    if not folder.is_dir():
        return []
    people = []
    for target in sorted(folder.glob(f'{prefix}_{day_token}*.xlsx')):
        if '.tmp' in target.name:
            continue
        people.extend(read_outcome_file(target))
    return people


def write_daily_outcomes(records, started_at=None, base=None):
    """Merge this run into one completed/failed workbook per local day.

    Completed wins over failed, identities are deduplicated, and older
    timestamped files from the same day are folded into the daily file.
    Already-completed identities discovered on the site are shown in the UI
    and daily ledger but are not written as a new learning completion.
    """
    started_at = started_at or datetime.now()
    token = started_at.strftime('%Y%m%d')
    completed_folder = paths.completed_folder(base)
    failed_folder = paths.failed_folder(base)
    completed = {}
    for person in read_outcome_people(completed_folder, '学习完成', token):
        completed.setdefault(person['id_number'], person)
    failed = {}
    for person in read_outcome_people(failed_folder, '学习失败', token):
        failed.setdefault(person['id_number'], person)
    completed_today = set(completed)
    for record in records:
        candidate = record.candidate
        person = {'district': candidate.district, 'name': candidate.name,
                  'id_number': candidate.id_number}
        if record.status == 'completed':
            completed_today.add(candidate.id_number)
            if not getattr(record, 'already_completed', False):
                completed[candidate.id_number] = person
        elif record.status in {'failed', 'stopped'}:
            failed.setdefault(candidate.id_number, person)
    for identity in completed_today:
        failed.pop(identity, None)
    completed_path = _write_workbook(completed_folder / f'学习完成_{token}.xlsx',
                                     list(completed.values()))
    failed_path = _write_workbook(failed_folder / f'学习失败_{token}.xlsx',
                                  list(failed.values()))
    return {'completed': completed_path, 'failed': failed_path, 'day': started_at.date()}


def write_outcomes(records, started_at=None, base=None):
    """Write one timestamped file per folder (kept for explicit checks)."""
    started_at = started_at or datetime.now()
    stamp = started_at.strftime('%Y%m%d_%H%M%S')
    records = list(records)
    completed = [record for record in records if record.status == 'completed']
    failed = [record for record in records if record.status in {'failed', 'stopped'}]
    return {
        'completed': _write(paths.completed_folder(base), '学习完成', stamp, completed),
        'failed': _write(paths.failed_folder(base), '学习失败', stamp, failed),
    }
