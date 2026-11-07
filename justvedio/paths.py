"""Application data locations next to the EXE (or the source checkout)."""
import os
import sys
from pathlib import Path

IDENTITIES = '人员信息'
COMPLETED = '学习完成'
FAILED = '学习失败'
RESULTS = 'results'
LIFETIME_STATS = '学习累计统计.json'


def application_base():
    """Directory that owns user data: next to the frozen EXE, or the project root.

    ``JUSTVEDIO_BASE`` exists so automated checks never write beside real data.
    """
    override = os.environ.get('JUSTVEDIO_BASE')
    if override:
        return Path(override).expanduser().resolve()
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _folder(name, base=None):
    return Path(base).expanduser().resolve() / name if base else application_base() / name


def identities_folder(base=None):
    return _folder(IDENTITIES, base)


def completed_folder(base=None):
    return _folder(COMPLETED, base)


def failed_folder(base=None):
    return _folder(FAILED, base)


def results_folder(base=None):
    return _folder(RESULTS, base)


def lifetime_stats_file(base=None):
    return results_folder(base) / LIFETIME_STATS


def ensure_folders(base=None):
    base = Path(base).expanduser().resolve() if base else application_base()
    folders = (identities_folder(base), completed_folder(base), failed_folder(base))
    for folder in folders:
        folder.mkdir(parents=True, exist_ok=True)
    note = identities_folder(base) / '说明.txt'
    if not note.exists():
        note.write_text(
            '把包含“所在的区县、姓名、身份证号”三列表头的 .xlsx 身份表放在本文件夹。\n'
            '软件启动时会自动加载本文件夹下所有 .xlsx，并按身份证号合并、去重。\n'
            '身份证号请使用文本格式。\n',
            encoding='utf-8',
        )
    return folders
