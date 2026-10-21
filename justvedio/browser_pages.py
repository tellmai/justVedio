"""Create isolated Chromium pages without repeatedly activating their windows."""
import asyncio


class BrowserPages:
    """One factory per browser/batch; only its first page opens in foreground."""

    def __init__(self, browser):
        self.browser = browser
        self._cdp = None
        self._lock = asyncio.Lock()
        self._context_ids = {}
        self._opened_first_page = False

    async def new_context(self, **options):
        async with self._lock:
            if self._cdp is None:
                self._cdp = await self.browser.new_browser_cdp_session()
            before = await self._cdp.send('Target.getBrowserContexts')
            context = await self.browser.new_context(**options)
            try:
                after = await self._cdp.send('Target.getBrowserContexts')
                # Playwright has no public context ID accessor. Serialize context
                # creation to identify it through CDP without private attributes.
                created = set(after['browserContextIds']) - set(before['browserContextIds'])
                if len(created) != 1:
                    raise RuntimeError('无法确定独立浏览器会话，已停止创建页面')
                self._context_ids[context] = created.pop()
                context.on('close', lambda _: self._context_ids.pop(context, None))
                return context
            except BaseException:
                await context.close()
                raise

    async def new_page(self, context):
        async with self._lock:
            # context.new_page() defaults to foreground, including the first
            # window of each isolated context. CDP background=True also opens
            # those new windows inactive; it does not merge identity storage.
            # https://chromedevtools.github.io/devtools-protocol/tot/Target/#method-createTarget
            async with context.expect_page() as opened:
                parameters = {
                    'url': 'about:blank',
                    'browserContextId': self._context_ids[context],
                    # Keep the page visible within its own inactive window.
                    # Background tabs suspend animation frames and can stall
                    # Playwright actionability checks and normal video playback.
                    'newWindow': True,
                    'background': self._opened_first_page,
                    'focus': not self._opened_first_page,
                }
                await self._cdp.send('Target.createTarget', parameters)
                self._opened_first_page = True
            page = await opened.value
            return page
