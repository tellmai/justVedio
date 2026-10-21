"""Real HTML media playback. Never changes currentTime, playbackRate or completion APIs."""
import asyncio
import math
import time

class VideoFailure(RuntimeError):
    pass


async def watch_video(page, options, progress=lambda **_: None):
    root = page.frame_locator(options.frame_selector) if options.frame_selector else page
    video = root.locator(options.video_selector).first
    await video.wait_for(state="visible")
    # A visible placeholder can precede the real player by several seconds.
    # Re-resolve the locator until actual media is ready before clicking it.
    loading = time.monotonic()
    while True:
        readiness = await video.evaluate("v => ({ready:v.readyState, error:v.error ? v.error.code : 0})")
        if readiness["error"]:
            raise VideoFailure("视频媒体加载失败，请检查网络和视频格式")
        if (readiness["ready"] or 0) >= 2:
            break
        if time.monotonic() - loading > min(options.stall_timeout_seconds, options.video_timeout_seconds):
            raise VideoFailure("等待视频播放器加载超时，媒体尚未就绪")
        await asyncio.sleep(0.2)
    await video.evaluate("(v, muted) => { v.muted = muted; }", options.muted)
    initial = await video.evaluate("v => ({paused:v.paused, ended:v.ended})")
    if initial["ended"]:
        raise VideoFailure("视频已经处于结束状态，未进行本次观看；请打开未观看的视频")
    if initial["paused"]:
        if options.play_selector:
            await root.locator(options.play_selector).first.click()
        else:
            controls = root.locator('.bpx-player-ctrl-play').first
            if await controls.count() and await controls.is_visible():
                await controls.click()
            else:
                await video.click()
            # Native media controls vary; play() only requests ordinary playback.
            if await video.evaluate("v => v.paused"):
                await video.evaluate("v => v.play()")
    started = moved = time.monotonic()
    previous = 0.0
    observed = False
    while time.monotonic() - started < options.video_timeout_seconds:
        if page.is_closed():
            raise VideoFailure("观看网页已关闭")
        state = await video.evaluate("""v => ({current:v.currentTime, duration:Number.isFinite(v.duration)?v.duration:null,
            ended:v.ended, paused:v.paused, error:v.error ? v.error.code : 0})""")
        if state["error"]:
            raise VideoFailure("视频加载或解码失败，请检查网络、视频地址或浏览器格式支持")
        current = float(state["current"] or 0)
        if current > previous + 0.01:
            observed, moved = True, time.monotonic()
        previous = current
        duration = state["duration"]
        percent = min(99.9, current / duration * 100) if duration and math.isfinite(duration) and duration > 0 else 0
        progress(progress=percent, elapsed_seconds=time.monotonic() - started)
        if state["ended"] and observed:
            if options.complete_selector:
                await root.locator(options.complete_selector).first.wait_for(state="visible")
            progress(progress=100, elapsed_seconds=time.monotonic() - started)
            return time.monotonic() - started
        if time.monotonic() - moved > options.stall_timeout_seconds:
            raise VideoFailure("播放长时间没有进展，请检查缓冲、暂停状态或网站是否要求前台观看")
        await asyncio.sleep(0.5)
    raise VideoFailure("超过单个视频最长等待时间，未记为完成")


async def watch_playlist(page, options, progress=lambda **_: None):
    total_elapsed = 0
    for count in range(1, options.max_videos + 1):
        def update(**changes):
            changes["elapsed_seconds"] = total_elapsed + changes.get("elapsed_seconds", 0)
            progress(**changes)
        total_elapsed += await watch_video(page, options, update)
        progress(videos_completed=count, elapsed_seconds=total_elapsed)
        if not options.next_selector:
            return {"videos_completed": count, "elapsed_seconds": total_elapsed}
        root = page.frame_locator(options.frame_selector) if options.frame_selector else page
        button = root.locator(options.next_selector).first
        if not await button.count() or not await button.is_visible() or not await button.is_enabled() or await button.get_attribute("aria-disabled") == "true":
            return {"videos_completed": count, "elapsed_seconds": total_elapsed}
        if count == options.max_videos:
            raise VideoFailure("达到连续视频数量上限，页面仍有下一视频；未记为全部完成")
        old = await root.locator(options.video_selector).first.evaluate("v => v.currentSrc")
        await button.click()
        # SPA players can retain the same video element. Await a new source/reset.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                changed = await root.locator(options.video_selector).first.evaluate("(v, old) => v.currentSrc !== old || (!v.ended && v.currentTime < 1)", old)
                if changed:
                    break
            except Exception:
                pass
            await asyncio.sleep(0.2)
        else:
            raise VideoFailure("点击下一视频后播放器没有切换")
