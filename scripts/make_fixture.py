"""Generate an original short WebM for offline tests using a canvas recording."""
import asyncio
import base64
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from justvedio.browsers import launch_browser

async def main():
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser, _ = await launch_browser(p, headless=True)
        try:
            page = await browser.new_page()
            await page.goto('about:blank')
            content = await page.evaluate('''async () => {
                const canvas=document.createElement('canvas');canvas.width=240;canvas.height=120;
                const ctx=canvas.getContext('2d'), stream=canvas.captureStream(12);
                const recorder=new MediaRecorder(stream,{mimeType:'video/webm;codecs=vp8'}), chunks=[];
                const done=new Promise(resolve=>recorder.onstop=resolve);
                recorder.ondataavailable=e=>chunks.push(e.data);recorder.start();
                const begin=performance.now();
                while(performance.now()-begin<1800){ctx.fillStyle='#173457';ctx.fillRect(0,0,240,120);ctx.fillStyle='#71e2b4';ctx.fillRect(15,75,(performance.now()-begin)/10,8);ctx.font='18px sans-serif';ctx.fillText('Video playback test',15,45);await new Promise(r=>setTimeout(r,80));}
                recorder.stop();await done;stream.getTracks().forEach(t=>t.stop());
                const bytes=new Uint8Array(await new Blob(chunks).arrayBuffer());return btoa(String.fromCharCode(...bytes));
            }''')
            out = Path('tests/fixtures/test.webm')
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(base64.b64decode(content))
            print(str(out), out.stat().st_size)
        finally:
            await browser.close()

asyncio.run(main())
