import asyncio
import json
import time
import pytest
from PySide6.QtWidgets import QApplication
from justvedio.models import Candidate, SiteConfig, VideoOptions
from justvedio.controller import BrowserWorker
from justvedio.browser import SiteSession, CaptchaFailure

def wait(app,condition,seconds=60):
    deadline=time.monotonic()+seconds
    while not condition() and time.monotonic()<deadline:
        app.processEvents()
        time.sleep(.01)
    assert condition(), 'worker timed out'

@pytest.mark.parametrize('background', [True, False])
def test_switch_off_twelve_logins_only_retains_isolated_home_pages(local_site,chrome,tmp_path,monkeypatch,background):
    origin,state=local_site
    from justvedio.browsers import launch_browser as real_launch
    real_login=SiteSession.login
    async def headless(p,explicit='',headless=False,progress=lambda _:None):
        return await real_launch(p,explicit,True,progress)
    monkeypatch.setattr('justvedio.controller.launch_browser',headless)
    app=QApplication.instance() or QApplication([])
    worker=BrowserWorker()
    async def recognize(_):
        return 'TEST'
    monkeypatch.setattr(worker.ocr,'recognize',recognize)
    seen=[]
    peak=[]
    async def observing(session,*args,**kwargs):
        result=await real_login(session,*args,**kwargs)
        cookies=await session.context.cookies(origin)
        seen.append(next(c['value'] for c in cookies if c['name']=='person'))
        peak.append(len(worker.browser.contexts))
        return result
    monkeypatch.setattr(SiteSession,'login',observing)
    ready,finished,errors=[],[],[]
    worker.ready.connect(lambda:ready.append(True))
    worker.job_finished.connect(lambda:finished.append(True))
    worker.failed.connect(errors.append)
    worker.start()
    try:
        wait(app,lambda:ready)
        candidates=[Candidate(i+2,'黔江区',f'演示{i}',f'11010119900101{i:04}') for i in range(12)]
        config=SiteConfig(origin+'/exam/',chrome,10000,True)
        options=VideoOptions(video_url='not-a-url',video_selector='',background=background)
        worker.start_job('watch',config,candidates,str(tmp_path),options=options)
        wait(app,lambda:finished)
        assert not errors
        assert state['posts']==12 and len(set(seen))==12
        assert max(peak)<=10 and max(peak)>1
        assert all(r.status=='completed' and r.stage=='登录验证完成' and r.videos_completed==0 for r in worker.last_store.records)
        assert not state['watch_visits']
        assert worker.browser is None and not worker.sessions
        assert len(worker.retained_sessions)==10 and len(worker.retained_browser.contexts)==10
        assert all(s.page.url==origin+'/exam/user/home' for s in worker.retained_sessions.values())
        focused=[]
        messages=[]
        worker.progress.connect(messages.append)
        selected=next(iter(worker.retained_sessions))
        async def focus_selected():
            focused.append(selected)
        monkeypatch.setattr(worker.retained_sessions[selected].page,'bring_to_front',focus_selected)
        worker.focus(selected)
        wait(app,lambda:messages if background else focused)
        assert focused==([] if background else [selected])
        assert worker.retained_background is background
        retained=worker.retained_browser
        worker.start_job('export',config)
        wait(app,lambda:len(finished)==2)
        assert worker.retained_browser is retained and retained.is_connected() and len(retained.contexts)==10
        saved=json.loads((worker.last_store.folder/'人员状态.json').read_text(encoding='utf-8'))
        assert all(r['status']=='completed' for r in saved['records'])
        assert saved['test_mode'] is False
        assert saved['execution_settings']['background'] is background
    finally:
        worker.shutdown()
        wait(app,lambda:not worker.isRunning())
        assert worker.retained_browser is None and not worker.retained_sessions

def test_original_login_captcha_three_failures(local_site,chrome):
    import pytest
    origin,state=local_site
    state['bad_captcha']=True
    async def run():
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser=await p.chromium.launch(executable_path=chrome,headless=True)
            session=SiteSession(p,SiteConfig(origin+'/exam/',chrome,5000,True),browser=browser)
            class OCR:
                async def recognize(self,_):
                    return 'wrong'
            try:
                with pytest.raises(CaptchaFailure,match='三次'):
                    await session.login(Candidate(2,'黔江区','演示','110101199001010010'),OCR())
                assert state['posts']==3
                assert browser.is_connected()
                await session.close()
                assert browser.is_connected() and not browser.contexts
            finally:
                await browser.close()
    asyncio.run(run())
