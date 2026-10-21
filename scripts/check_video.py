"""Manually invoked public-video playback check; never logs in with identities."""
import asyncio
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from justvedio.models import VideoOptions
from justvedio.browsers import launch_browser
from justvedio.video import watch_playlist
from justvedio.browser_pages import BrowserPages

async def check(background=True):
    from playwright.async_api import async_playwright
    from justvedio.version import VERSION
    output = Path(f'build/video-check-{VERSION}')
    output.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        browser, choice = await launch_browser(p, headless=background)
        result = {'browser': choice.name, 'url': VideoOptions().video_url, 'background': background, 'headless': background}
        try:
            pages = BrowserPages(browser)
            context = await pages.new_context(locale='zh-CN')
            page = await pages.new_page(context)
            page.set_default_timeout(30000)
            response = await page.goto(VideoOptions().video_url, wait_until='domcontentloaded')
            result.update(http_status=response.status, title=await page.title())
            await page.screenshot(path=str(output / 'video-before.png'))
            result.update(await watch_playlist(page, VideoOptions(video_timeout_seconds=120, stall_timeout_seconds=35)))
            result['ok'] = True
            await page.screenshot(path=str(output / 'video-completed.png'))
        except Exception as error:
            result.update(ok=False, error=str(error).split('Call log:')[0])
        finally:
            await browser.close()
        (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result.get('ok') else 1

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--foreground', action='store_true', help='显示浏览器；默认按后台执行方式验证')
    args = parser.parse_args()
    raise SystemExit(asyncio.run(check(not args.foreground)))
