"""Site learning flow: enter 旁听学习, start playback, wait, confirm, return home."""
import asyncio
import re
import time
from urllib.parse import urlsplit


class LearningFailure(RuntimeError):
    pass


STATE_JS = """v => ({current:v.currentTime, duration:Number.isFinite(v.duration)?v.duration:null,
    ended:v.ended, paused:v.paused, error:v.error ? v.error.code : 0, ready:v.readyState})"""

# Common controls of the site's custom player and of the players bundled with
# it. The centre of the picture is tried first because the site's white
# triangle sits there, but these remain as fallbacks when the overlay changes.
PLAY_SELECTORS = (
    '.vjs-big-play-button',
    '.xgplayer-start',
    '.prism-play-btn',
    '.dplayer-play-icon',
    '[class*="big-play"]',
    '[class*="video-play"]',
    '[class*="play-btn"]',
    '[class*="play-button"]',
    '[class*="play-icon"]',
    '[aria-label*="播放"]',
    'button:has-text("播放")',
)


def _same_path(first, second):
    try:
        return urlsplit(first).path.rstrip('/') == urlsplit(second).path.rstrip('/')
    except Exception:
        return False


def _page_roots(page):
    """The page itself plus any child frames, so players and buttons in an
    iframe are reachable without requiring the user to configure a selector."""
    try:
        frames = list(page.frames)
        main = page.main_frame
    except Exception:
        return [page]
    return [page] + [frame for frame in frames if frame != main]


async def _visible(locator):
    try:
        return await locator.count() > 0 and await locator.first.is_visible()
    except Exception:
        return False


async def _any_visible_text(page, text, exact=True):
    for root in _page_roots(page):
        if await _visible(root.get_by_text(text, exact=exact)):
            return True
    return False


async def _any_visible_label(page, label, exact=True):
    """Match the text of a link/button as well as an input's accessible name."""
    for root in _page_roots(page):
        for locator in (root.get_by_role('button', name=label, exact=exact),
                        root.get_by_role('link', name=label, exact=exact),
                        root.get_by_text(label, exact=exact)):
            if await _visible(locator):
                return True
    return False


async def _entry_visible(page, pattern):
    for root in _page_roots(page):
        for locator in (root.get_by_role('button', name=pattern),
                        root.get_by_role('link', name=pattern),
                        root.get_by_text(pattern, exact=True)):
            if await _visible(locator):
                return True
    return False


def _entry_pattern(options):
    """The completion check also treats a visible 进入考试 as unfinished."""
    text = (options.learning_entry_text or '开始旁听学习|继续旁听学习').strip()
    return re.compile(f'(?:{text})|进入考试')


def _click_candidates(root, pattern, include_text=True):
    result = [root.get_by_role('button', name=pattern), root.get_by_role('link', name=pattern)]
    if include_text:
        result.append(root.get_by_text(pattern, exact=True))
    return result


async def _try_click(root, pattern, include_text=True):
    for locator in _click_candidates(root, pattern, include_text):
        try:
            count = await locator.count()
        except Exception:
            continue
        for index in range(min(count, 8)):
            item = locator.nth(index)
            try:
                if not await item.is_visible() or not await item.is_enabled():
                    continue
                await item.click(timeout=4000)
                return True
            except Exception:
                continue
    return False


async def _click_first_anywhere(page, pattern, include_text=True, timeout=0):
    """Poll the page and its frames for a matching visible control."""
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        for root in _page_roots(page):
            if await _try_click(root, pattern, include_text):
                return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.4)


async def _completion_prompt_visible(page, options):
    text = (options.confirm_text or '确认完成学习').strip()
    try:
        pattern = re.compile(f'(?:{text})|确认完成|网考流程已完成')
    except re.error:
        pattern = re.compile('确认完成学习|完成学习|确认完成|网考流程已完成')
    for root in _page_roots(page):
        for locator in (root.get_by_role('button', name=pattern),
                        root.get_by_role('link', name=pattern),
                        root.get_by_text(pattern, exact=True),
                        root.get_by_text('网考流程已完成', exact=False)):
            if await _visible(locator):
                return True
    return False


async def _locate_video(page, options):
    """Find the first visible video in the page or any of its frames."""
    selector = options.video_selector
    if options.frame_selector:
        root = page.frame_locator(options.frame_selector)
        video = root.locator(selector).first
        try:
            await video.wait_for(state='visible', timeout=30000)
        except Exception:
            raise LearningFailure('视频页未找到视频播放器') from None
        return root, video
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        for root in _page_roots(page):
            try:
                locator = root.locator(selector)
                count = await locator.count()
            except Exception:
                continue
            for index in range(min(count, 4)):
                item = locator.nth(index)
                try:
                    if await item.is_visible():
                        return root, item
                except Exception:
                    continue
        await asyncio.sleep(0.3)
    raise LearningFailure('视频页未找到视频播放器')


async def _state(video):
    return await video.evaluate(STATE_JS)


async def _wait_until_playing(video, seconds):
    deadline = time.monotonic() + max(0.0, seconds)
    while True:
        state = await _state(video)
        if state['error']:
            raise LearningFailure('视频加载或解码失败，请检查网络和网站状态')
        if state['ended']:
            return True
        if not state['paused'] and (state['current'] or 0) > 0:
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.3)


async def _click_video_area(page, video):
    try:
        await video.scroll_into_view_if_needed(timeout=5000)
    except Exception:
        pass
    try:
        box = await video.bounding_box()
    except Exception:
        return False
    if not box or box['width'] < 2 or box['height'] < 2:
        return False
    try:
        await page.mouse.click(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
        return True
    except Exception:
        return False


async def _click_video_element(video):
    try:
        box = await video.bounding_box()
        if not box or box['width'] < 2 or box['height'] < 2:
            return False
        await video.click(position={'x': box['width'] / 2, 'y': box['height'] / 2},
                          force=True, timeout=5000)
        return True
    except Exception:
        return False


async def _dispatch_click(video):
    try:
        await video.evaluate("""v => {
            const options = {bubbles: true, cancelable: true, view: window};
            for (let element = v; element; element = element.parentElement) {
                element.dispatchEvent(new MouseEvent('click', options));
                if (element === document.body) break;
            }
        }""")
        return True
    except Exception:
        return False


async def _play_from_api(video):
    try:
        return bool(await video.evaluate("""async v => {
            try {
                v.muted = true;
                await v.play();
                return true;
            } catch (error) {
                return false;
            }
        }"""))
    except Exception:
        return False


async def open_learning(page, options, report):
    """Click 开始/继续旁听学习. Returns the page that shows the video, or None."""
    entry = (options.learning_entry_text or '开始旁听学习|继续旁听学习').strip()
    pattern = re.compile(entry)
    pages_before = len(page.context.pages)
    if not await _click_first_anywhere(page, pattern, include_text=True, timeout=20):
        # The exam home may offer only "进入考试" until the exam is done.
        try:
            enter_exam = re.compile('进入考试')
            if (await _entry_visible(page, enter_exam)
                    and not await _entry_visible(page, pattern)):
                raise LearningFailure('发现进入考试按钮，请先完成考试')
        except LearningFailure:
            raise
        except Exception:
            pass
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


async def start_playback(page, options, report):
    """Click the picture / play control and prove that media actually advances."""
    root, video = await _locate_video(page, options)
    try:
        await video.evaluate('(v, muted) => { v.muted = !!muted; }', options.muted)
    except Exception:
        pass
    state = None
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            state = await _state(video)
        except Exception:
            raise LearningFailure('视频播放器无法读取，页面可能已关闭') from None
        if state['error']:
            raise LearningFailure('视频加载失败，请检查网络或网站状态')
        if state['ended']:
            raise LearningFailure('视频已处于结束状态，无法重新学习')
        # Some players only load the media after the first click. Do not wait
        # for readyState here; a known duration or readyState 1 is enough.
        if state['duration'] and state['duration'] > 0:
            break
        if (state['ready'] or 0) >= 1:
            break
        await asyncio.sleep(0.3)
    if state is None:
        raise LearningFailure('视频播放器无法读取，页面可能已关闭')
    if state['ended']:
        raise LearningFailure('视频已处于结束状态，无法重新学习')
    if not state['paused']:
        if await _wait_until_playing(video, 10):
            report('视频已开始正常播放')
            return video
        if await _play_from_api(video) and await _wait_until_playing(video, 12):
            report('视频已开始正常播放')
            return video
        raise LearningFailure('视频已请求播放但没有进度，请检查网络或网站限制')

    async def click_selector(selector):
        try:
            locator = root.locator(selector).first
            if await locator.count() and await locator.is_visible() and await locator.is_enabled():
                await locator.click(timeout=5000)
                return True
        except Exception:
            pass
        return False

    async def attempt(action):
        try:
            await action()
        except Exception:
            return 'idle'
        if await _wait_until_playing(video, 3):
            return 'playing'
        try:
            state = await _state(video)
        except Exception:
            return 'idle'
        if not state['paused']:
            if await _wait_until_playing(video, 10):
                return 'playing'
            return 'stalled'
        return 'idle'

    actions = []
    if options.play_selector:
        actions.append(lambda: click_selector(options.play_selector))
    actions.append(lambda: _click_video_area(page, video))
    actions.append(lambda: _click_video_element(video))
    for selector in PLAY_SELECTORS:
        actions.append(lambda selector=selector: click_selector(selector))
    actions.append(lambda: _dispatch_click(video))
    for action in actions:
        result = await attempt(action)
        if result == 'playing':
            report('视频已开始正常播放')
            return video
        if result == 'stalled':
            break
    if await _play_from_api(video) and await _wait_until_playing(video, 12):
        report('视频已开始正常播放')
        return video
    if await _wait_until_playing(video, 10):
        report('视频已开始正常播放')
        return video
    raise LearningFailure('视频未能开始播放，已尝试点击画面中央、播放按钮并调用播放接口，请检查网站限制')


async def watch_until_complete(page, video, options, update, report, browser=None, home_url=''):
    """Leave the browser alone and wait for the media or confirmation UI to finish."""
    started = time.monotonic()
    last_current = 0.0
    last_note = started
    last_prompt = started
    observed = False
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
            if await _completion_prompt_visible(page, options):
                update(progress=100.0, elapsed_seconds=time.monotonic() - started)
                return
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
            observed = True
        duration = state['duration']
        percent = min(99.9, current / duration * 100) if duration and duration > 0 else 0.0
        update(progress=percent, elapsed_seconds=time.monotonic() - started)
        now = time.monotonic()
        if now - last_note >= 60:
            last_note = now
            report(f'学习进行中：已播放 {percent:.0f}%，已用 {(now - started) / 60:.1f} 分钟')
        # The site can replace the player with a confirmation dialog instead of
        # keeping the video element until it reports ended.
        if observed and percent >= 95 and now - last_prompt >= 1.5:
            last_prompt = now
            if await _completion_prompt_visible(page, options):
                update(progress=100.0, elapsed_seconds=time.monotonic() - started)
                return
        await asyncio.sleep(1)
    raise LearningFailure('超过最长等待时间，学习未完成')


async def _completion_modal_visible(page, options):
    # "网考流程已完成" is the heading shown after the 确认完成 click. Matching
    # the button alone is unsafe because the video page also has a top
    # "返回考生主页" control.
    return await _any_visible_text(page, '网考流程已完成', exact=False)


async def _wait_completion_modal(page, options, seconds):
    deadline = time.monotonic() + max(0.0, seconds)
    while True:
        if page.is_closed():
            return False
        if await _completion_modal_visible(page, options):
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.3)


async def confirm_completion(page, options, report):
    """Click 确认完成 and require the “网考流程已完成” modal to appear."""
    if page.is_closed():
        return False
    pattern = re.compile((options.confirm_text or '确认完成学习').strip())
    if await _completion_modal_visible(page, options):
        return True
    for _ in range(2):
        clicked = await _click_first_anywhere(page, pattern, include_text=True, timeout=20)
        if clicked:
            report('已点击完成确认')
            try:
                await page.wait_for_load_state('domcontentloaded', timeout=8000)
            except Exception:
                pass
            if await _wait_completion_modal(page, options, 20):
                return True
        if await _completion_modal_visible(page, options):
            return True
    return False


async def _click_lowest_home_control(page, pattern):
    """Click the lowest visible 返回考生主页 control in the completion modal."""
    best = None
    for root in _page_roots(page):
        for locator in (root.get_by_role('button', name=pattern),
                        root.get_by_role('link', name=pattern, exact=True),
                        root.get_by_text(pattern, exact=True)):
            try:
                count = await locator.count()
            except Exception:
                continue
            for index in range(min(count, 6)):
                item = locator.nth(index)
                try:
                    if not await item.is_visible() or not await item.is_enabled():
                        continue
                    box = await item.bounding_box()
                    if box and box['width'] > 1 and box['height'] > 1:
                        if best is None or box['y'] > best['y']:
                            best = box
                except Exception:
                    continue
    if best is None:
        return False
    try:
        await page.mouse.click(best['x'] + best['width'] / 2,
                               best['y'] + best['height'] / 2)
        return True
    except Exception:
        return False


async def _click_return_home_button(page, options, timeout=30):
    """Wait for “网考流程已完成”, then click its 返回考生主页 control."""
    pattern = re.compile((options.home_text or '返回考生主页').strip())
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        if page.is_closed():
            return False
        if await _completion_modal_visible(page, options):
            if await _click_lowest_home_control(page, pattern):
                return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.4)


async def _wait_completed(page, options, seconds):
    deadline = time.monotonic() + max(0.0, seconds)
    while True:
        if page.is_closed():
            return False
        if await is_learning_completed(page, options, timeout=0):
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.5)


async def return_home(page, options, home_url, report):
    """Click the completion modal's 返回考生主页 and wait for the finished home."""
    if page.is_closed():
        return False
    if await is_learning_completed(page, options, timeout=0):
        return True
    if not await _click_return_home_button(page, options, timeout=30):
        return False
    if await _wait_completed(page, options, 30):
        report('已点击“返回考生主页”，主页已显示学习完成状态')
        return True
    return False


async def is_learning_completed(page, options, timeout=8):
    """True when the home position shows 再次考试 and no learning/exam entry."""
    entry = _entry_pattern(options)
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        if page.is_closed():
            return False
        try:
            entry_visible = await _entry_visible(page, entry)
            again = await _any_visible_label(page, '再次考试', exact=True)
            done = await _any_visible_label(page, '本年度网考已完成', exact=False)
        except Exception:
            entry_visible = again = done = False
        if not entry_visible and (again or done):
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.3)


async def verify_learning_completed(page, options, report, timeout=30):
    """Require 再次考试/本年度网考已完成 and no 开始/继续旁听学习 or 进入考试."""
    entry = _entry_pattern(options)
    deadline = time.monotonic() + max(0.0, timeout)
    saw_entry = False
    while True:
        if page.is_closed():
            raise LearningFailure('返回主页后页面已关闭，未确认学习完成')
        try:
            entry_visible = await _entry_visible(page, entry)
            again = await _any_visible_label(page, '再次考试', exact=True)
            done = await _any_visible_label(page, '本年度网考已完成', exact=False)
        except Exception:
            entry_visible = again = done = False
        if entry_visible:
            saw_entry = True
        if not entry_visible and (again or done):
            report('已确认学习完成：旁听学习/进入考试入口已消失，页面显示“再次考试/本年度网考已完成”')
            return True
        if time.monotonic() >= deadline:
            break
        await asyncio.sleep(0.5)
    if saw_entry:
        raise LearningFailure('返回考生主页后仍显示“开始/继续旁听学习”或“进入考试”，未记为完成')
    raise LearningFailure('返回考生主页后未检测到“再次考试/本年度网考已完成”，未记为完成')
