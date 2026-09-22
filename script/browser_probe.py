import asyncio
from playwright.async_api import async_playwright

async def main():
 async with async_playwright() as p:
  browser=await p.chromium.launch(headless=True)
  page=await browser.new_page()
  await page.goto('https://www.hausundbau.at/ausstellerverzeichnis/',wait_until='domcontentloaded',timeout=60000)
  await page.wait_for_timeout(3000)
  for i in range(20):
   n=await page.locator('.jet-listing-grid--330 .jet-listing-grid__item').count()
   print(i,n)
   b=page.locator('#mehr')
   if not await b.is_visible(): break
   try:
    await b.click(timeout=5000)
    await page.wait_for_timeout(2000)
   except Exception as e:
    print('stop',type(e).__name__,str(e)[:200]); break
  html=await page.content()
  open('hausbau_all.html','w',encoding='utf-8').write(html)
  await browser.close()
asyncio.run(main())
