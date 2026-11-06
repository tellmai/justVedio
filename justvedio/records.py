"""Per-batch Excel records of learned and failed identities."""
import os
from datetime import datetime
from pathlib import Path

from . import paths

HEADERS = ('所在的区县', '姓名', '身份证号')


def _write(folder, prefix, stamp, records):
    from openpyxl import Workbook
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f'{prefix}_{stamp}.xlsx'
    if target.exists():
        suffix = 2
        while (folder / f'{prefix}_{stamp}_{suffix}.xlsx').exists():
            suffix += 1
        target = folder / f'{prefix}_{stamp}_{suffix}.xlsx'
    book = Workbook()
    try:
        sheet = book.active
        sheet.title = '人员信息'
        sheet.append(list(HEADERS))
        for record in records:
            candidate = record.candidate
            sheet.append([candidate.district, candidate.name, candidate.id_number])
            for cell, value in zip(sheet[sheet.max_row], (candidate.district, candidate.name, candidate.id_number)):
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


def write_outcomes(records, started_at=None, base=None):
    """Write one file per folder named after the batch start time."""
    started_at = started_at or datetime.now()
    stamp = started_at.strftime('%Y%m%d_%H%M%S')
    records = list(records)
    completed = [record for record in records if record.status == 'completed']
    failed = [record for record in records if record.status in {'failed', 'stopped'}]
    return {
        'completed': _write(paths.completed_folder(base), '学习完成', stamp, completed),
        'failed': _write(paths.failed_folder(base), '学习失败', stamp, failed),
    }
