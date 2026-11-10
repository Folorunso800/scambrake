import os;os.environ['OMP_NUM_THREADS']='6'
import json,pathlib,soundfile as sf
from kokoro_onnx import Kokoro
P=pathlib.Path(__file__).parent
k=Kokoro('/workspace/voice-models/kokoro/kokoro-v1.0.onnx','/workspace/voice-models/kokoro/voices-v1.0.bin')
sc=json.loads((P/'script.json').read_text());tot=0
for s in sc:
  a,sr=k.create(s.get('say',s['voice']),voice='bm_george',speed=1.1,lang='en-gb');sf.write(P/'vo'/f"{s['id']}.wav",a,sr)
  s['vd']=len(a)/sr;tot+=s['vd'];print(s['id'],round(s['vd'],2),flush=True)
(P/'script_timed.json').write_text(json.dumps(sc,indent=1));print('voice total',round(tot,1))
