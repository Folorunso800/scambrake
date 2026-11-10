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
    b=await p.chromium.launch(executable_path='/usr/bin/google-chrome',args=['--headless=new','--disable-blink-features=AutomationControlled'])
    c=await b.new_context(viewport={'width':1600,'height':1000},user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36',color_scheme='dark')
    for k,u in U.items():
      pg=await c.new_page()
      try:
        await pg.goto(u,wait_until='domcontentloaded',timeout=45000);await asyncio.sleep(10)
        await pg.screenshot(path=f'shots/{k}.png');print(k,await pg.title())
      except Exception as e:print(k,'ERR',e)
      await pg.close()
    await b.close()
asyncio.run(main())
