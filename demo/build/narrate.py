# Voice matched to the posted OddsHedge demo: edge-tts en-US-AndrewNeural, rate +4%, one request per scene (native sentence pauses)
import asyncio,json,pathlib,subprocess,edge_tts
P=pathlib.Path(__file__).parent;(P/'vo').mkdir(exist_ok=True)
VOICE='en-US-AndrewNeural';RATE='+4%'
sc=json.loads((P/'script.json').read_text())
def dur(f):return float(subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',f],capture_output=True,text=True).stdout)
async def one(s):
  for k in range(6):
    try:
      c=edge_tts.Communicate(s['say'],VOICE,rate=RATE,boundary='SentenceBoundary');aud=bytearray();bd=[]
      async for m in c.stream():
        if m['type']=='audio':aud+=m['data']
        elif m['type']=='SentenceBoundary':bd.append((m['offset']/1e7,(m['offset']+m['duration'])/1e7,m['text']))
      if not aud:raise RuntimeError('no audio')
      return bytes(aud),bd
    except Exception as e:
      print('retry',s['id'],e,flush=True);await asyncio.sleep(2)
  raise SystemExit('failed '+s['id'])
async def main():
  tot=0
  for s in sc:
    aud,bd=await one(s);mp3=P/'vo'/f"{s['id']}.mp3";mp3.write_bytes(aud)
    subprocess.run(['ffmpeg','-y','-loglevel','error','-i',str(mp3),'-ar','44100','-ac','1',str(P/'vo'/f"{s['id']}.wav")],check=True)
    s['vd']=dur(str(mp3));s['sent']=[list(b) for b in bd];tot+=s['vd'];print(s['id'],round(s['vd'],2),len(bd),flush=True)
  (P/'script_timed.json').write_text(json.dumps(sc,indent=1));print('voice total',round(tot,1))
asyncio.run(main())
