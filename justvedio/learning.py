"""Site learning flow: enter 旁听学习, start playback, wait, confirm, return home."""
import asyncio
import re
import time
from urllib.parse import urlsplit


class LearningFailure(RuntimeError):
    pass


STATE_JS = """v => ({current:v.currentTime, duration:Number.isFinite(v.duration)?v.duration:null,
    ended:v.ended, paused:v.paused, error:v.error ? v.error.code : 0, ready:v.readyState})"""


def _root(page, options):
    return page.frame_locator(options.frame_selector) if options.frame_selector else page


def _same_path(first, second):
    try:
        return urlsplit(first).path.rstrip('/') == urlsplit(second).path.rstrip('/')
    except Exception:
        return False


async def _click_first(page, pattern, include_text=True):
    locators = [page.get_by_role('button', name=pattern), page.get_by_role('link', name=pattern)]
    if include_text:
        locators.append(page.get_by_text(pattern, exact=True))
    for locator in locators:
        try:
            count = await locator.count()
        except Exception:
            continue
        for index in range(min(count, 6)):
            item = locator.nth(index)
            try:
                if not await item.is_visible() or not await item.is_enabled():
                    continue
                await item.click(timeout=8000)
                return True
            except Exception:
                continue
    return False


async def open_learning(page, options, report):
    """Click 开始/继续旁听学习. Returns the page that shows the video, or None."""
    entry = (options.learning_entry_text or '开始旁听学习|继续旁听学习').strip()
    pattern = re.compile(entry)
    pages_before = len(page.context.pages)
    if not await _click_first(page, pattern):
        return None
    await asyncio.sleep(0.3)
    target = page
    try:
        if len(page.context.pages) > pages_before:
            target = page.context.pages[-1]
        await target.wait_for_load_state('domcontentloaded', timeout=30000)
    except Exception:
        pass
    report('已点击旁听学习入口，正在打开视频页')
    return target


async def _state(video):
    return await video.evaluate(STATE_JS)


async def start_playback(page, options, report):
    """Click the player's play control and prove that the media advances."""
    root = _root(page, options)
    video = root.locator(options.video_selector).first
    try:
        await video.wait_for(state='visible', timeout=30000)
    except Exception:
        raise LearningFailure('视频页未找到视频播放器') from None
    deadline = time.monotonic() + 40
    state = None
    while time.monotonic() < deadline:
        try:
            state = await _state(video)
        except Exception:
            raise LearningFailure('视频播放器无法读取，页面可能已关闭') from None
        if state['error']:
            raise LearningFailure('视频加载失败，请检查网络或网站状态')
        if (state['ready'] or 0) >= 2:
            break
        await asyncio.sleep(0.4)
    if not state or (state['ready'] or 0) < 2:
        raise LearningFailure('视频尚未加载完成，未开始学习')
    if state['ended']:
        raise LearningFailure('视频已处于结束状态，无法重新学习')
    if not state['paused'] and (state['current'] or 0) > 0:
        report('视频已在播放')
        return video
    clicked = False
    if options.play_selector:
        try:
            button = root.locator(options.play_selector).first
            if await button.count() and await button.is_visible():
                await button.click(timeout=6000)
                clicked = True
        except Exception:
            clicked = False
    if not clicked:
        for selector in ('.vjs-big-play-button', '[class*="play-button"]', '[class*="play-btn"]',
                         'button[aria-label*="播放"]', 'button:has-text("播放")', '[class*="xgplayer-start"]'):
            try:
                button = root.locator(selector).first
                if await button.count() and await button.is_visible():
                    await button.click(timeout=5000)
                    clicked = True
                    break
            except Exception:
                continue
    if not clicked:
        # The white triangle is normally an overlay above the media; clicking
        # the video centre reaches whichever element is on top.
        try:
            box = await video.bounding_box()
            if box:
                await page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
                clicked = True
        except Exception:
            clicked = False
    started = time.monotonic()
    while time.monotonic() - started < 25:
        try:
            state = await _state(video)
        except Exception:
            raise LearningFailure('视频播放器页面已关闭，未能开始播放') from None
        if state['error']:
            raise LearningFailure('视频加载或解码失败，请检查网络和网站状态')
        if not state['paused'] and (state['current'] or 0) > 0:
            report('视频已开始正常播放')
            return video
        await asyncio.sleep(0.5)
    try:
        await video.evaluate('v => v.play()')
    except Exception:
        pass
    started = time.monotonic()
    while time.monotonic() - started < 10:
        try:
            state = await _state(video)
        except Exception:
            break
        if not state['paused'] and (state['current'] or 0) > 0:
            report('视频已开始正常播放')
            return video
        await asyncio.sleep(0.5)
    raise LearningFailure('视频未能开始播放，请检查播放按钮或网站限制')


async def watch_until_complete(page, video, options, update, report, browser=None, home_url=''):
    """Leave the browser alone and wait for the media to finish."""
    started = time.monotonic()
    last_current = 0.0
    last_note = started
    while time.monotonic() - started < options.video_timeout_seconds:
        if page.is_closed():
            raise LearningFailure('学习页面已关闭，学习未完成')
        if browser is not None and not browser.is_connected():
            raise LearningFailure('浏览器已被关闭，学习未完成')
        try:
            state = await _state(video)
        except Exception:
            if page.is_closed() or (browser is not None and not browser.is_connected()):
                raise LearningFailure('浏览器或学习页面已关闭，学习未完成') from None
            await asyncio.sleep(1)
            continue
        if state['error']:
            raise LearningFailure('视频播放失败，未记为学习完成')
        if state['ended']:
            update(progress=100.0, elapsed_seconds=time.monotonic() - started)
            return
        if home_url and _same_path(page.url, home_url):
            update(progress=100.0, elapsed_seconds=time.monotonic() - started)
            return
        current = float(state['current'] or 0)
        if current > last_current + 0.05:
            last_current = current
        duration = state['duration']
        percent = min(99.9, current / duration * 100) if duration and duration > 0 else 0.0
        update(progress=percent, elapsed_seconds=time.monotonic() - started)
        now = time.monotonic()
        if now - last_note >= 60:
            last_note = now
            report(f'学习进行中：已播放 {percent:.0f}%，已用 {(now - started) / 60:.1f} 分钟')
        await asyncio.sleep(1)
    raise LearningFailure('超过最长等待时间，学习未完成')


async def confirm_completion(page, options, report):
    """Click 确认完成学习 when the site offers it; the video end is enough otherwise."""
    if page.is_closed():
        return False
    pattern = re.compile((options.confirm_text or '确认完成学习').strip())
    if await _click_first(page, pattern):
        report('已点击完成确认')
        try:
            await page.wait_for_load_state('domcontentloaded', timeout=15000)
        except Exception:
            pass
        return True
    return False


async def return_home(page, options, home_url, report):
    """Return to the login home page before the browser is closed."""
    if page.is_closed():
        return False
    if home_url and _same_path(page.url, home_url):
        return True
    pattern = re.compile((options.home_text or '返回考生主页').strip())
    if await _click_first(page, pattern, include_text=False):
        try:
            await page.wait_for_load_state('domcontentloaded', timeout=20000)
        except Exception:
            pass
        if home_url and _same_path(page.url, home_url):
            report('已返回考生主页')
            return True
    if page.is_closed():
        return False
    if not home_url:
        return False
    try:
        await page.goto(home_url, wait_until='domcontentloaded', timeout=30000)
    except Exception:
        return False
    report('已返回考生主页')
    return True
