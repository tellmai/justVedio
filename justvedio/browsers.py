"""Discover installed Chromium browsers without invoking a shell or user profiles."""
import asyncio
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BrowserChoice:
    name: str
    path: str
    priority: int


KNOWN = {
    "chrome.exe": ("Google Chrome", 0),
    "msedge.exe": ("Microsoft Edge", 1),
    "brave.exe": ("Brave", 2),
    "vivaldi.exe": ("Vivaldi", 2),
    "opera.exe": ("Opera", 2),
    "360chrome.exe": ("360 极速浏览器", 2),
    "360se.exe": ("360 安全浏览器", 2),
    "qqbrowser.exe": ("QQ 浏览器", 2),
    "chromium.exe": ("Chromium", 2),
}


def executable_from_command(command):
    command = os.path.expandvars(str(command)).strip()
    match = re.match(r'^"([^"]+\.exe)"|^(.+?\.exe)(?:\s|$)', command, re.I)
    return (match[1] or match[2]) if match else ""


def _registry_paths():
    paths = []
    try:
        import winreg
    except ImportError:
        return paths
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            for exe in KNOWN:
                try:
                    with winreg.OpenKey(hive, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe}", 0, winreg.KEY_READ | view) as key:
                        paths.append(winreg.QueryValue(key, None))
                except OSError:
                    pass
            try:
                with winreg.OpenKey(hive, r"SOFTWARE\Clients\StartMenuInternet", 0, winreg.KEY_READ | view) as root:
                    for index in range(winreg.QueryInfoKey(root)[0]):
                        name = winreg.EnumKey(root, index)
                        try:
                            with winreg.OpenKey(root, name + r"\shell\open\command") as key:
                                paths.append(winreg.QueryValue(key, None))
                        except OSError:
                            pass
            except OSError:
                pass
    return paths


def discover_browsers():
    raw = list(_registry_paths())
    locations = (
        "Google/Chrome/Application/chrome.exe", "Microsoft/Edge/Application/msedge.exe",
        "BraveSoftware/Brave-Browser/Application/brave.exe", "Vivaldi/Application/vivaldi.exe",
        "Programs/Opera/opera.exe", "Opera/opera.exe", "Chromium/Application/chrome.exe",
        "360/360Chrome/Chrome/Application/360chrome.exe", "360/360se6/Application/360se.exe",
        "Tencent/QQBrowser/QQBrowser.exe",
    )
    for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        if os.environ.get(variable):
            raw.extend(str(Path(os.environ[variable]) / path) for path in locations)
    choices, seen = [], set()
    for value in raw:
        path = executable_from_command(value)
        key = path.casefold()
        name = Path(path).name.lower()
        if path and name in KNOWN and key not in seen and Path(path).is_file():
            label, priority = KNOWN[name]
            choices.append(BrowserChoice(label, path, priority))
            seen.add(key)
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    for relative in ("chrome/chrome-win64/chrome.exe", "tools/chrome/chrome-win64/chrome.exe"):
        path = base / relative
        if path.is_file() and str(path).casefold() not in seen:
            choices.append(BrowserChoice("随附 Chrome", str(path), 3))
            seen.add(str(path).casefold())
    return sorted(choices, key=lambda item: item.priority)


async def launch_browser(playwright, explicit="", headless=False, progress=lambda _: None):
    choices = [BrowserChoice("手动指定浏览器", explicit, -1)] if explicit else discover_browsers()
    if not choices:
        raise ValueError("未找到兼容浏览器，请选择 Chrome / Edge 程序或检查随附浏览器文件")
    for choice in choices:
        try:
            browser = await playwright.chromium.launch(executable_path=choice.path, headless=headless)
        except Exception:
            progress(f"{choice.name} 启动失败，正在检查其他可用浏览器" if not explicit else "手动指定的浏览器启动失败")
            continue
        progress(f"使用浏览器：{choice.name}")
        return browser, choice
    raise ValueError("可用浏览器均启动失败，请检查软件文件或手动选择兼容浏览器程序")


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


@dataclass
class RunningBrowser:
    """A browser started by justVedio and connected over CDP.

    Owned by the process rather than by Playwright, so it survives a client
    disconnect (closing the application leaves an in-flight learning session
    running). ``close`` is the per-identity completion step.
    """
    choice: BrowserChoice
    browser: object
    process: object
    profile: Path
    port: int
    log_stream: object = None
    log_path: Path = None

    def is_open(self):
        return self.process is not None and self.process.poll() is None

    async def close(self, timeout=15):
        if self.process is None:
            return True
        try:
            if getattr(self.browser, 'is_connected', lambda: False)():
                # For a CDP connection browser.close() only disconnects, so ask
                # Chrome itself to exit; the process ending is our signal.
                cdp = await self.browser.new_browser_cdp_session()
                try:
                    await cdp.send('Browser.close')
                except Exception:
                    pass
        except Exception:
            pass
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self._cleanup_files()
                return True
            await asyncio.sleep(0.1)
        try:
            self.process.terminate()
            self.process.wait(timeout=5)
        except Exception:
            pass
        self._cleanup_files()
        return self.process.poll() is not None

    def _cleanup_files(self):
        try:
            if self.log_stream is not None:
                self.log_stream.close()
                self.log_stream = None
        except Exception:
            pass
        try:
            if self.log_path is not None:
                self.log_path.unlink(missing_ok=True)
                self.log_path = None
        except Exception:
            pass
        shutil.rmtree(self.profile, ignore_errors=True)


async def launch_process(playwright, choice, headless=False, progress=lambda _: None):
    """Start a fresh browser with its own profile and connect over CDP."""
    port = _free_port()
    profile = Path(tempfile.mkdtemp(prefix='justvedio-browser-'))
    arguments = [
        choice.path,
        f'--user-data-dir={profile}',
        f'--remote-debugging-port={port}',
        '--remote-allow-origins=*',
        '--no-first-run',
        '--no-default-browser-check',
        '--autoplay-policy=no-user-gesture-required',
        '--disable-background-timer-throttling',
        '--disable-renderer-backgrounding',
        '--disable-backgrounding-occluded-windows',
        '--disable-session-crashed-bubble',
        '--hide-crash-restore-bubble',
        '--window-size=1280,900',
    ]
    if headless:
        arguments.append('--headless=new')
    creationflags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    log_path = Path(tempfile.mkstemp(prefix='justvedio-chrome-', suffix='.log')[1])
    log_stream = log_path.open('wb')
    process = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=log_stream, creationflags=creationflags)
    deadline = time.monotonic() + 30
    ready = False
    last_error = ''
    while time.monotonic() < deadline:
        if process.poll() is not None:
            break
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=1):
                ready = True
                break
        except Exception as error:
            last_error = f'{type(error).__name__}: {error}'
            await asyncio.sleep(0.2)

    def failure_detail():
        parts = []
        try:
            log_stream.flush()
            lines = log_path.read_text(encoding='utf-8', errors='replace').strip().splitlines()
            if lines:
                parts.append(' / '.join(lines[-2:]))
        except Exception:
            pass
        if last_error:
            parts.append(last_error)
        return f'：{"；".join(parts)}' if parts else ''

    if not ready:
        detail = failure_detail()
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:
            pass
        try:
            log_stream.close()
            log_path.unlink(missing_ok=True)
        except Exception:
            pass
        shutil.rmtree(profile, ignore_errors=True)
        raise ValueError(f'{choice.name} 启动失败{detail}' if detail else f'{choice.name} 启动失败，请检查浏览器程序是否可用')
    try:
        browser = await playwright.chromium.connect_over_cdp(f'http://127.0.0.1:{port}')
    except Exception as error:
        detail = failure_detail()
        try:
            process.terminate()
            process.wait(timeout=5)
        except Exception:
            pass
        try:
            log_stream.close()
            log_path.unlink(missing_ok=True)
        except Exception:
            pass
        shutil.rmtree(profile, ignore_errors=True)
        raise ValueError(f'无法连接 {choice.name}{detail}') from error
    progress(f"使用浏览器：{choice.name}")
    return RunningBrowser(choice, browser, process, profile, port, log_stream, log_path)
