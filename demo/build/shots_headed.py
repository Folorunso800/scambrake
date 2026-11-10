import asyncio,json,re
from playwright.async_api import async_playwright
txt=open('live-fresh.txt').read()
tx=re.findall(r'txns/([A-Za-z0-9]+)',txt)
print(tx)
U={'paid_vendor':'https://testnet.nearblocks.io/txns/'+tx[0],'paid_newcomer':'https://testnet.nearblocks.io/txns/'+tx[1],
 'refused_blocklist':'https://testnet.nearblocks.io/txns/'+tx[2],'refused_cap':'https://testnet.nearblocks.io/txns/'+tx[3],
 'guard_keys':'https://testnet.nearblocks.io/address/guard.scambrake-owner.testnet?tab=accesskeys',
 'guard':'https://testnet.nearblocks.io/address/guard.scambrake-owner.testnet'}
json.dump(tx,open('txs.json','w'))
async def main():
  async with async_playwright() as p:
    b=await p.chromium.launch(executable_path='/usr/bin/google-chrome',headless=False,args=['--window-size=1600,1100','--disable-blink-features=AutomationControlled'])
    c=await b.new_context(viewport={'width':1600,'height':1000},color_scheme='dark')
    for k,u in U.items():
      pg=await c.new_page()
      try:
        await pg.goto(u,wait_until='domcontentloaded',timeout=45000)
        for i in range(10):
          await asyncio.sleep(6)
          if 'Just' not in await pg.title():break
        await asyncio.sleep(6)
        await pg.screenshot(path=f'shots/{k}.png');print(k,await pg.title())
      except Exception as e:print(k,'ERR',e)
      await pg.close()
    await b.close()
asyncio.run(main())
