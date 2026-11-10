import os;os.environ['OMP_NUM_THREADS']='6'
import json,pathlib,numpy as np,soundfile as sf
from kokoro_onnx import Kokoro
P=pathlib.Path(__file__).parent;(P/'vo').mkdir(exist_ok=True)
SPEED=0.93;GAP=0.7
k=Kokoro('/workspace/voice-models/kokoro/kokoro-v1.0.onnx','/workspace/voice-models/kokoro/voices-v1.0.bin')
sc=json.loads((P/'script.json').read_text());tot=0
for s in sc:
  parts=[];t=0;sent=[];sr=24000
  for i,x in enumerate(s['sents']):
    cap=x[0];say=(x[1] if len(x)>1 and x[1] else cap);after=x[2] if len(x)>2 and x[2] else GAP
    a,sr=k.create(say,voice='bm_george',speed=SPEED,lang='en-gb')
    sent.append([t,t+len(a)/sr,cap]);parts.append(a);t+=len(a)/sr
    if i<len(s['sents'])-1:parts.append(np.zeros(int(after*sr),dtype=a.dtype));t+=after
  sf.write(P/'vo'/f"{s['id']}.wav",np.concatenate(parts),sr)
  s['vd']=t;s['sent']=sent;tot+=t;print(s['id'],round(t,2),flush=True)
(P/'script_timed.json').write_text(json.dumps(sc,indent=1));print('voice total',round(tot,1))
