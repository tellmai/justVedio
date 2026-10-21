import asyncio
import pytest
from justvedio.models import VideoOptions
from justvedio.video import watch_video, watch_playlist, VideoFailure
from justvedio.local_video import LocalVideoServer

def test_real_video_reaches_end(local_site, chrome):
    origin,_=local_site
    async def run():
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser=await p.chromium.launch(executable_path=chrome,headless=True)
            try:
                page=await browser.new_page()
                await page.goto(origin+'/watch')
                updates=[]
                result=await watch_playlist(page,VideoOptions(play_selector='#play',complete_selector='#completed',stall_timeout_seconds=5,video_timeout_seconds=15),lambda **patch:updates.append(patch))
                assert result['videos_completed']==1
                assert result['elapsed_seconds']>=1
                assert await page.locator('video').evaluate('v=>v.ended')
                assert updates[-1]['videos_completed']==1
            finally:
                await browser.close()
    asyncio.run(run())

def test_paused_or_stalled_never_counts_complete(local_site, chrome):
    origin,_=local_site
    async def run():
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser=await p.chromium.launch(executable_path=chrome,headless=True)
            try:
                page=await browser.new_page()
                await page.goto(origin+'/watch')
                await page.locator('#play').evaluate("b=>b.onclick=()=>{}")
                with pytest.raises(VideoFailure,match='没有进展'):
                    await watch_video(page,VideoOptions(play_selector='#play',stall_timeout_seconds=1,video_timeout_seconds=5))
            finally:
                await browser.close()
    asyncio.run(run())

def test_local_server_ranges_and_no_path_browsing():
    from pathlib import Path
    from urllib.request import Request,urlopen
    from urllib.error import HTTPError
    path=Path(__file__).parent/'fixtures/test.webm'
    server=LocalVideoServer(path)
    try:
        url=server.url.replace('/player','/media')
        with urlopen(Request(url,headers={'Range':'bytes=0-9'})) as response:
            assert response.status==206 and response.read()==path.read_bytes()[:10]
        with pytest.raises(HTTPError) as error:
            urlopen(Request(url,headers={'Range':'bytes=999999999-'}))
        assert error.value.code==416
        with pytest.raises(HTTPError):
            urlopen(server.url.replace('/player','/../../main.py'))
    finally:
        server.close()

def test_waits_for_delayed_media_initialization(local_site,chrome):
    origin,_=local_site
    async def run():
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser=await p.chromium.launch(executable_path=chrome,headless=True)
            try:
                page=await browser.new_page()
                await page.goto(origin+'/watch')
                await page.set_content(f'''<video width="240" height="120" muted></video><button id="play">播放</button><script>
                    setTimeout(()=>{{const v=document.querySelector('video');v.src='{origin}/media';document.querySelector('#play').onclick=()=>v.play();}},700);
                    </script>''')
                result=await watch_playlist(page,VideoOptions(play_selector='#play',video_timeout_seconds=15,stall_timeout_seconds=5))
                assert result['videos_completed']==1
            finally:
                await browser.close()
    asyncio.run(run())
