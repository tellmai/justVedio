import asyncio

import pytest

from justvedio.browser import SiteSession
from justvedio.browser_pages import BrowserPages
from justvedio.models import Candidate, SiteConfig


def test_concurrent_pages_background_refill_and_identity_isolation(local_site, chrome, monkeypatch):
    origin, state = local_site

    async def scenario():
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=chrome, headless=True)
            pages = BrowserPages(browser)
            commands = []
            cdp = await browser.new_browser_cdp_session()
            pages._cdp = cdp
            send = cdp.send

            async def observe(method, params=None):
                if method == 'Target.createTarget':
                    commands.append(params.copy())
                return await send(method, params)

            monkeypatch.setattr(cdp, 'send', observe)

            class OCR:
                async def recognize(self, _):
                    return 'TEST'

            async def login(index):
                session = SiteSession(p, SiteConfig(origin + '/exam/', chrome, 10000, True),
                                      browser=browser, pages=pages)
                person = Candidate(index + 2, '黔江区', f'后台演示{index}', f'11010119900101{index:04}')
                await session.login(person, OCR())
                return session, person

            try:
                people = await asyncio.gather(*(login(i) for i in range(4)))
                assert len(browser.contexts) == 4 and state['posts'] == 4
                for session, person in people:
                    cookie = next(c for c in await session.context.cookies(origin) if c['name'] == 'person')
                    assert cookie['value'] == person.id_number
                    assert person.name in await session.page.locator('h1').inner_text()
                session, _ = people[0]
                exam = await session.new_page()
                assert exam.context is session.context and len(session.context.pages) == 2
                await exam.close()
                # Closing the first window must not reset the foreground rule.
                await session.close()
                replacement, _ = await login(4)
                assert len(browser.contexts) == 4
                assert [c['background'] for c in commands] == [False] + [True] * 5
                assert len({c['browserContextId'] for c in commands}) == 5
                await asyncio.gather(*(s.close() for s, _ in people[1:]), replacement.close())
                assert not browser.contexts and not pages._context_ids
            finally:
                await browser.close()

    asyncio.run(scenario())


def test_context_lookup_failure_closes_context_without_foreground_fallback(chrome, monkeypatch):
    async def scenario():
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=chrome, headless=True)
            pages = BrowserPages(browser)
            cdp = await browser.new_browser_cdp_session()
            pages._cdp = cdp
            send = cdp.send
            queries = 0

            async def fail_lookup(method, params=None):
                nonlocal queries
                if method == 'Target.getBrowserContexts':
                    queries += 1
                    if queries == 2:
                        raise RuntimeError('context lookup failed')
                return await send(method, params)

            monkeypatch.setattr(cdp, 'send', fail_lookup)
            try:
                with pytest.raises(RuntimeError, match='context lookup failed'):
                    await pages.new_context()
                assert not browser.contexts and not pages._context_ids
                assert not pages._opened_first_page
            finally:
                await browser.close()

    asyncio.run(scenario())
