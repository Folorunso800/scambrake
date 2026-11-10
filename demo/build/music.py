import numpy as np, wave
import sys;sr=44100;bpm=100;beat=60/bpm;T=float(sys.argv[1]);N=int(T*sr);out=np.zeros((N,2))
rng=np.random.default_rng(1)
def n2f(n):return 440*2**((n-69)/12)
def add(sig,t0,ch=(1,1)):
  i=int(t0*sr);j=min(N,i+len(sig))
  if i>=N:return
  out[i:j,0]+=sig[:j-i]*ch[0];out[i:j,1]+=sig[:j-i]*ch[1]
def env(n,a,r):
  e=np.ones(n);ai=int(a*sr);e[:ai]=np.linspace(0,1,ai);e*=np.exp(-np.arange(n)/(r*sr));return e
def lp(x,k=0.15):
  y=np.zeros_like(x);s=0
  for i in range(len(x)):s+=k*(x[i]-s);y[i]=s
  return y
chords=[[57,60,64,67],[53,57,60,64],[48,52,55,59],[55,59,62,65]] # Am7 Fmaj7 Cmaj7 G7
bass=[45,41,48,43]
bar=4*beat;nb=int(T/bar)+1
# precompute pad
for b in range(nb):
  c=chords[b%4];t0=b*bar;n=int(bar*sr*1.05);t=np.arange(n)/sr
  s=sum(np.sin(2*np.pi*n2f(m)*t*(1+d))*(0.5 if d else 1) for m in c for d in (0,0.003))
  s+=0.25*sum(np.sin(2*np.pi*2*n2f(m)*t) for m in c)
  e=np.minimum(1,t/0.4)*np.minimum(1,(bar*1.05-t)/0.3)
  add(0.035*s*e*(0.85+0.15*np.sin(2*np.pi*t/beat)),t0)
  # bass: root on 1, 2.5, 3
  for off,dur in((0,1.4),(1.5,.4),(2,1.8)):
    n2=int(dur*beat*sr);tt=np.arange(n2)/sr;f=n2f(bass[b%4])
    bs=np.sin(2*np.pi*f*tt)+0.3*np.sin(4*np.pi*f*tt)
    add(0.22*bs*env(n2,0.005,0.5),t0+off*beat)
  # drums
  for k in range(4):
    tb=t0+k*beat
    if k in(0,2) or (k==3 and b%2):
      n2=int(.35*sr);tt=np.arange(n2)/sr;ph=2*np.pi*np.cumsum(50+90*np.exp(-tt*30))/sr
      add(0.55*np.sin(ph)*np.exp(-tt*9),tb if k!=3 else tb+beat/2)
    if k in(1,3):
      n2=int(.25*sr);tt=np.arange(n2)/sr
      sn=lp(rng.standard_normal(n2),0.5)*np.exp(-tt*18)*0.5+0.3*np.sin(2*np.pi*190*tt)*np.exp(-tt*25)
      add(0.22*sn,tb)
    for h in (0,0.5):
      n2=int(.06*sr);tt=np.arange(n2)/sr;hn=rng.standard_normal(n2);hn=hn-lp(hn,0.6)
      add(0.06*hn*np.exp(-tt*70)*(1 if h else .6),tb+h*beat+(0.02 if h else 0),(0.7,1))
# melody: pentatonic plucks, from bar 2, sparse
pent=[69,72,74,76,79,81]
mel_rng=np.random.default_rng(7);motif=[mel_rng.choice(pent,8) for _ in range(4)]
for b in range(2,nb):
  m=motif[b%4]
  for k,step in enumerate([0,1,1.5,2.5,3,3.5]):
    if (b+k)%3==0:continue
    n2=int(.6*sr);tt=np.arange(n2)/sr;f=n2f(m[k]+(12 if b%8>=6 else 0)-12)
    pl=(np.sin(2*np.pi*f*tt)+0.4*np.sin(4*np.pi*f*tt)+0.15*np.sin(6*np.pi*f*tt))*np.exp(-tt*6)
    add(0.06*pl,b*bar+step*beat,(1,0.75) if k%2 else (0.75,1))
fade=np.ones(N);fi=int(1.5*sr);fade[:fi]=np.linspace(0,1,fi);fo=int(4*sr);fade[-fo:]=np.linspace(1,0,fo)
out*=fade[:,None];out/=np.abs(out).max()*1.1
w=wave.open('music.wav','wb');w.setnchannels(2);w.setsampwidth(2);w.setframerate(sr);w.writeframes((out*32767).astype('<i2').tobytes());w.close()
