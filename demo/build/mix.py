import json,subprocess,pathlib
P=pathlib.Path(__file__).parent;tl=json.loads((P/'timeline.json').read_text());T=tl[-1]['start']+tl[-1]['dur']
cmd=['ffmpeg','-y','-loglevel','error'];f=[]
for i,s in enumerate(tl):
  cmd+=['-i',str(P/'vo'/f"{s['id']}.wav")];f.append(f"[{i}:a]aresample=48000,adelay={int((s['start']+s['lead'])*1000)}:all=1[v{i}]")
f.append(''.join(f'[v{i}]' for i in range(len(tl)))+f'amix=inputs={len(tl)}:normalize=0,apad=whole_dur={T},atrim=duration={T}[voice]')
cmd+=['-filter_complex',';'.join(f),'-map','[voice]','-ac','2',str(P/'voice.wav')];subprocess.run(cmd,check=True)
subprocess.run(['ffmpeg','-y','-loglevel','error','-i',str(P/'voice.wav'),'-i',str(P/'music.wav'),'-filter_complex',f'[0:a]loudnorm=I=-16:TP=-2:LRA=10[v];[1:a]aresample=48000,volume=0.04,atrim=duration={T},afade=t=out:st={T-4}:d=4[m];[v][m]amix=inputs=2:normalize=0,alimiter=limit=0.9,afade=t=out:st={T-1.5}:d=1.5[a]','-map','[a]','-ar','48000','-t',str(T),str(P/'mix.wav')],check=True)
def stamp(x):
  ms=round(x*1000);return f'{ms//3600000:02d}:{ms//60000%60:02d}:{ms//1000%60:02d},{ms%1000:03d}'
print('mixed',T)
