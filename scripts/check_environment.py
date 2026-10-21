import asyncio
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from justvedio.browser import inspect_environment
from justvedio.models import SiteConfig
from justvedio.ocr import LocalOCR

async def main():
    from playwright.async_api import async_playwright
    checks=[]
    ocr=LocalOCR()
    try:
        async with async_playwright() as p:
            ok=await inspect_environment(p,SiteConfig(),ocr,'',lambda label,passed,detail:checks.append({'label':label,'ok':passed,'detail':detail}))
        result={'ok':ok,'checks':checks,'real_login_submitted':False}
        output=Path('build/environment-check.json')
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False))
        return 0 if ok else 1
    finally:
        ocr.close()

raise SystemExit(asyncio.run(main()))
