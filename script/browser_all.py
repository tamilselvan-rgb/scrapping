import asyncio
from playwright.async_api import async_playwright
async def main():
 async with async_playwright() as p:
  b=await p.chromium.launch(headless=True)
  page=await b.new_page()
  await page.goto('https://www.hausundbau.at/ausstellerverzeichnis/?nowprocket=1',wait_until='networkidle',timeout=90000)
  last=0
  for i in range(20):
   n=await page.locator('.jet-listing-grid--330 .jet-listing-grid__item').count()
   print(i,n)
   if n==last or not await page.locator('#mehr').is_visible(): break
   last=n
   await page.locator('#mehr').evaluate('(e)=>e.click()')
   try: await page.wait_for_function('(old)=>document.querySelectorAll(".jet-listing-grid--330 .jet-listing-grid__item").length > old', last, timeout=15000)
   except Exception: await page.wait_for_timeout(5000)
  print('final',await page.locator('.jet-listing-grid--330 .jet-listing-grid__item').count())
  open('hausbau_all.html','w',encoding='utf-8').write(await page.content())
  await b.close()
asyncio.run(main())
