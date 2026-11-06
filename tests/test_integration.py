import asyncio
import json
import time
from datetime import datetime
import pytest
from PySide6.QtWidgets import QApplication
from justvedio.models import Candidate, SiteConfig, VideoOptions
from justvedio.controller import BrowserWorker
from justvedio.browser import SiteSession, CaptchaFailure
from justvedio.browsers import BrowserChoice

def wait(app,condition,seconds=60):
    deadline=time.monotonic()+seconds
    while not condition() and time.monotonic()<deadline:
        app.processEvents()
        time.sleep(.01)
    assert condition(), 'worker timed out'

def test_twelve_people_learn_with_one_browser_each(local_site,chrome,tmp_path,monkeypatch):
    origin,state=local_site
    from justvedio.browsers import launch_process as real_launch
    monkeypatch.setenv('JUSTVEDIO_BASE', str(tmp_path/'app-base'))
    launched=[]
    async def launch(playwright,choice,headless=False,progress=lambda _:None):
        running=await real_launch(playwright,choice,True,progress)
        launched.append(running)
        return running
    monkeypatch.setattr('justvedio.controller.launch_process',launch)
    app=QApplication.instance() or QApplication([])
    worker=BrowserWorker()
    async def recognize(_):
        return 'TEST'
    monkeypatch.setattr(worker.ocr,'recognize',recognize)
    ready,finished,errors=[],[],[]
    worker.ready.connect(lambda:ready.append(True))
    worker.job_finished.connect(lambda:finished.append(True))
    worker.failed.connect(errors.append)
    worker.start()
    try:
        wait(app,lambda:ready)
        candidates=[Candidate(i+2,'黔江区',f'演示{i}',f'11010119900101{i:04}') for i in range(12)]
        config=SiteConfig(origin+'/exam/',chrome,10000,True)
        browsers=[BrowserChoice('测试浏览器1',chrome,0),BrowserChoice('测试浏览器2',chrome,1)]
        options=VideoOptions(background=True,video_timeout_seconds=60)
        worker.start_job('watch',config,candidates,str(tmp_path/'statistics'),options=options,browsers=browsers,
                         started_at=datetime(2026,1,2,3,4,5),outcome_root=tmp_path/'records')
        wait(app,lambda:finished,180)
        assert not errors
        records=worker.last_store.records
        assert all(r.status=='completed' and r.stage=='学习完成' for r in records)
        assert [r.browser for r in records]==['测试浏览器1','测试浏览器2']*6
        assert len(launched)==12 and all(item.process.poll() is not None for item in launched)
        assert len(state['learning_visits'])==12 and state['confirmations']==12
        assert not worker.active_browsers and not worker.active_pages
        saved=json.loads((worker.last_store.folder/'人员状态.json').read_text(encoding='utf-8'))
        assert saved['version']==5 and saved['flow']=='learning'
        assert 'test_mode' not in saved
        assert saved['execution_settings']=={'browsers':['测试浏览器1','测试浏览器2'],'background':True,'concurrency':2}
        from openpyxl import load_workbook
        completed=list((tmp_path/'records'/'学习完成').glob('学习完成_20260102_030405*.xlsx'))
        failed=list((tmp_path/'records'/'学习失败').glob('学习失败_20260102_030405*.xlsx'))
        assert len(completed)==1 and len(failed)==1
        book=load_workbook(completed[0],read_only=True)
        try:
            assert book.active.max_row==13 and book.active.max_column==3
            assert [c.value for c in next(book.active.iter_rows(max_row=1))]==['所在的区县','姓名','身份证号']
        finally:
            book.close()
        book=load_workbook(failed[0],read_only=True)
        try:
            assert book.active.max_row==1
        finally:
            book.close()
    finally:
        worker.shutdown()
        wait(app,lambda:not worker.isRunning())
        assert not worker.active_browsers

def test_original_login_captcha_three_failures(local_site,chrome):
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
