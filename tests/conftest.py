import base64
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from justvedio.fixtures import SyntheticSite

@pytest.fixture
def local_site():
    with SyntheticSite(Path(__file__).parent/'fixtures/test.webm') as site:
        yield site.origin, site.state

@pytest.fixture
def chrome():
    from justvedio.browser import find_chrome
    path=os.environ.get('TEST_CHROME_PATH') or find_chrome()
    if not path:
        pytest.fail('浏览器集成测试需要 Chrome/Edge，请设置 TEST_CHROME_PATH')
    return path
