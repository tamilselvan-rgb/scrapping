import asyncio
from playwright.async_api import async_playwright
async def main():
 async with async_playwright() as p:
  b=await p.chromium.launch(headless=True)
  page=await b.new_page()
  page.on('console',lambda m: print('CONSOLE',m.type,m.text[:300]))
  page.on('pageerror',lambda e: print('PAGEERR',str(e)[:500]))
  page.on('request',lambda r: print('REQ',r.method,r.url) if ('ajax' in r.url or 'jet' in r.url) else None)
  page.on('response',lambda r: print('RESP',r.status,r.url) if ('ajax' in r.url or 'jet' in r.url) else None)
  await page.goto('https://www.hausundbau.at/ausstellerverzeichnis/?nowprocket=1',wait_until='networkidle',timeout=90000)
  print('count',await page.locator('.jet-listing-grid--330 .jet-listing-grid__item').count())
  print('buttons',await page.locator('#mehr').count(),await page.locator('#mehr').is_visible())
  print(await page.locator('#mehr').evaluate('(e)=>({outer:e.outerHTML,onclick:e.onclick+"",parent:e.parentElement.outerHTML.slice(0,1000)})'))
  await page.locator('#mehr').evaluate('(e)=>e.click()')
  await page.wait_for_timeout(8000)
  print('after',await page.locator('.jet-listing-grid--330 .jet-listing-grid__item').count())
  await b.close()
asyncio.run(main())
