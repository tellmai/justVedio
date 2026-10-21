"""Power request scoped to the lifetime of an active batch."""
import ctypes
import sys
from ctypes import wintypes


class PowerGuard:
    """Acquire and release on the same worker thread; allow the display to sleep."""
    def __init__(self):
        self.active = False
        self.api = None
        if sys.platform == 'win32':
            self.api = ctypes.WinDLL('kernel32', use_last_error=True).SetThreadExecutionState
            self.api.argtypes = [wintypes.DWORD]
            self.api.restype = wintypes.DWORD

    def acquire(self):
        if self.api and not self.api(0x80000001):
            raise RuntimeError('无法申请运行期间阻止自动休眠，请检查电源设置')
        self.active = True

    def release(self):
        if self.active and self.api:
            self.api(0x80000000)
        self.active = False
