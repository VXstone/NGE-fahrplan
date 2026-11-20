"""Verkehrsperioden (VP) der grafischen Fahrpläne SBB -> Wochentage.
Quelle: Zeichenerklärung zum grafischen Fahrplan SBB (Fahrplan 2015, SYFA-Kalender).
1=Mo … 7=So. 'WT' = Werktags-Variante (xy9 / 68 78 69 79): Feiertage gelten als So.
Rückgabe: dict(tage=[..], wt=bool, folgetag=+1/-1/0, begrenzt=bool, roh=str, unklar=bool)
"""
import re
GEN2={'10':[1,3],'20':[2,4],'30':[3,5],'40':[4,6],'50':[5,7],'60':[1,6],'70':[2,7]}
WT2={'68':(1,5),'78':(7,4),'69':(6,7),'79':(5,6)}
def span(x,y):
    out=[x]
    while out[-1]!=y: out.append(out[-1]%7+1)
    return out
def decode(code):
    r=dict(roh=code,tage=[],wt=False,folgetag=0,begrenzt=False,unklar=False)
    m=re.fullmatch(r'([+-]?)(\d{2,3})(\*?)',code.strip())
    if not m: r['unklar']=True; return r
    s,c,st=m.groups(); r['folgetag']={'+':1,'-':-1,'':0}[s]; r['begrenzt']=bool(st)
    if len(c)==2:
        if c=='00': r['unklar']=True                     # fakultativ/extra
        elif c in GEN2: r['tage']=GEN2[c]
        elif c in WT2: r['tage']=span(*WT2[c]); r['wt']=True
        elif c[0]=='0': r['tage']=[int(c[1])]
        elif '1'<=c[0]<='7' and '1'<=c[1]<='7': r['tage']=span(int(c[0]),int(c[1]))
        else: r['unklar']=True
    else:
        x,y,z=map(int,c)
        if z==9 and 1<=x<=7 and 1<=y<=7: r['tage']=span(x,y); r['wt']=True
        elif y==0: r['tage']=sorted({x,z})
        elif z==8: r['tage']=span(x,y); r['unklar']=True   # «xy8»: weitere Tage nur in der VP-Liste
        elif x<y<z: r['tage']=[x,y,z]
        else: r['tage']=[d for d in span(x,y) if d!=z]
    return r
if __name__=='__main__':
    for c in ['15','17*','+15*','25*','57','67','11','12*','269*','+369*','159','+559','749*','259*','105','145','153','316','+64','22*','56','128','00']:
        d=decode(c); print(f"{c:6} {d['tage']} wt={d['wt']} +{d['folgetag']} begrenzt={d['begrenzt']} {'UNKLAR' if d['unklar'] else ''}")
