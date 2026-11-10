import asyncio
from playwright.async_api import async_playwright
async def main():
  async with async_playwright() as p:
    b=await p.chromium.launch(executable_path='/usr/bin/google-chrome',headless=False,args=['--disable-blink-features=AutomationControlled','--window-size=1600,1100'])
    c=await b.new_context(viewport={'width':1600,'height':1000},color_scheme='dark')
    pg=await c.new_page()
    await pg.goto('https://testnet.nearblocks.io/address/guard.scambrake-owner.testnet',wait_until='domcontentloaded',timeout=45000)
    for i in range(10):
      await asyncio.sleep(6)
      if 'Just' not in await pg.title():break
    await asyncio.sleep(5)
    await pg.locator('button,a,div,span').filter(has_text=__import__('re').compile(r'^Access Keys$')).locator('visible=true').first.click();await asyncio.sleep(8)
    await pg.screenshot(path='shots/guard_keys.png');await b.close()
asyncio.run(main())
