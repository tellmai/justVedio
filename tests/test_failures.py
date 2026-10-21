import asyncio
import pytest
from PySide6.QtWidgets import QApplication
from justvedio.models import VideoOptions
from justvedio.video import watch_playlist, watch_video, VideoFailure
from test_flows import setup_worker, launch
from test_integration import wait


def test_playlist_really_plays_second_media(local_site, chrome):
    origin, _ = local_site
    async def run():
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=chrome, headless=True)
            try:
                page = await browser.new_page()
                await page.goto(origin+'/watch')
                await page.evaluate("""() => {
                    const b=document.createElement('button');b.id='next';b.textContent='下一段';
                    b.onclick=()=>{document.querySelector('video').src='/media?part=2';b.remove()};
                    document.body.appendChild(b);
                }""")
                result = await watch_playlist(page, VideoOptions(play_selector='#play', next_selector='#next', video_timeout_seconds=15, stall_timeout_seconds=5))
                assert result['videos_completed'] == 2 and result['elapsed_seconds'] >= 2
            finally:
                await browser.close()
    asyncio.run(run())


def test_page_closed_during_playback_is_not_completed(local_site, chrome):
    origin, _ = local_site
    async def run():
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=chrome, headless=True)
            try:
                page = await browser.new_page()
                await page.goto(origin+'/watch')
                task = asyncio.create_task(watch_video(page, VideoOptions(play_selector='#play', video_timeout_seconds=10)))
                await asyncio.sleep(.4)
                await page.close()
                with pytest.raises(Exception):
                    await task
            finally:
                await browser.close()
    asyncio.run(run())


def test_expiry_during_video_cancels_and_releases_resources(local_site, chrome, tmp_path, monkeypatch):
    origin, _ = local_site
    app, worker, finished, errors = setup_worker(monkeypatch)
    try:
        launch(worker, origin, chrome, tmp_path)
        wait(app, lambda: worker.last_store and worker.last_store.records[0].status == 'watching')
        monkeypatch.setattr('justvedio.controller.is_expired', lambda: True)
        wait(app, lambda: not worker.isRunning())
        assert errors and errors[-1] == '软件已过期，请联系1564532736@qq.com'
        assert worker.last_store.records[0].status == 'stopped'
        assert all(r.status == 'pending' for r in worker.last_store.records[1:])
        assert worker.browser is None and not worker.sessions and not worker.power_guard.active
    finally:
        worker.shutdown()
        wait(app, lambda: not worker.isRunning())
