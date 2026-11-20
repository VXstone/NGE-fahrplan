# Linienart: Zeichenerklärung 2015 – voll = linkes Gleis (Regel), gestrichelt = rechtes Gleis, punktiert = 3. Gleis; Strichpunkt 2026 noch ungeklärt.
"""Prototyp: Güterzüge (blau) aus einem grafischen Fahrplan der SBB extrahieren."""
import pymupdf as f, re, math, sys, json, collections
BLUE=(0x3b/255,0x65/255,0xa3/255)
def colkey(c): return tuple(round(v,2) for v in c) if c else None
def parse(fn):
    d=f.open(fn); out=[]
    for pno,p in enumerate(d):
        W=p.get_text('words')
        tim=[(int(w[4][:2])*60+int(w[4][3:]),(w[1]+w[3])/2) for w in W if re.fullmatch(r'\d\d:\d\d',w[4]) and w[0]<60]
        if len(tim)<5: continue
        # lineare Regression y->Minute
        n=len(tim); mx=sum(t for t,_ in tim)/n; my=sum(y for _,y in tim)/n
        b=sum((t-mx)*(y-my) for t,y in tim)/sum((y-my)**2 for _,y in tim); a=mx-b*my
        y2t=lambda y:a+b*y
        # Stationen: Kopfzeile (Abkürzungen oberhalb der ersten Zeitmarke)
        y0=min(y for _,y in tim)
        st=[(w[4],(w[0]+w[2])/2) for w in W if re.fullmatch(r'[A-Z]{1,6}\d?',w[4]) and w[3]<y0 and w[1]>50]
        # vertikale Stationslinien (schwarz) bestimmen x genauer
        vx=sorted({round(it[1].x,1) for dr in p.get_drawings() if colkey(dr.get('color'))==(0,0,0) for it in dr['items'] if it[0]=='l' and abs(it[1].x-it[2].x)<0.1 and abs(it[1].y-it[2].y)>200})
        stx=[]
        for nme,x in st:
            cand=[v for v in vx if abs(v-x)<25]
            stx.append((nme,min(cand,key=lambda v:abs(v-x)) if cand else x))
        def x2st(x):
            nme,sx=min(stx,key=lambda s:abs(s[1]-x)); return nme if abs(sx-x)<1.5 else None
        segs=[]
        for dr in p.get_drawings():
            if colkey(dr.get('color'))!=colkey(BLUE): continue
            ds=str(dr.get('dashes') or ''); dash='voll' if ds in ('','[] 0') else ('gestrichelt' if len(ds.split())<=4 else 'strichpunkt')
            for it in dr['items']:
                if it[0]=='l' and abs(it[1].x-it[2].x)>1: segs.append((it[1],it[2],dash))
        # Labels (blaue Spans)
        labs=[]
        for bl in p.get_text('dict')['blocks']:
            for l in bl.get('lines',[]):
                toks=[(s['text'],s['bbox']) for s in l['spans'] if '%06x'%s['color']=='3b65a3']
                txt=' '.join(t for t,_ in toks).split()
                if not txt: continue
                m=re.fullmatch(r'(\d{5}[A-Za-z]*)',txt[0])
                if m:
                    bb=l['bbox']; labs.append((m.group(1),' '.join(txt[1:]),((bb[0]+bb[2])/2,(bb[1]+bb[3])/2)))
        def dist(pt,s):
            a_,b_=s[0],s[1];dx,dy=b_.x-a_.x,b_.y-a_.y;L=dx*dx+dy*dy
            t=max(0,min(1,((pt[0]-a_.x)*dx+(pt[1]-a_.y)*dy)/L));return math.hypot(a_.x+t*dx-pt[0],a_.y+t*dy-pt[1])
        for s in segs:
            near=[(dist(c,s),z,vp) for z,vp,c in labs if dist(c,s)<9]
            zug,vp=(min(near)[1],min(near)[2]) if near else (None,None)
            A,B=(s[0],s[1]) if s[0].x<s[1].x else (s[1],s[0])
            out.append(dict(page=pno,zug=zug,vp=vp,linie=s[2],
                 von=x2st(A.x),t_von=round(y2t(A.y),1),bis=x2st(B.x),t_bis=round(y2t(B.y),1)))
    return out
if __name__=='__main__':
    r=parse(sys.argv[1])
    json.dump(r,open(sys.argv[2],'w'),ensure_ascii=False,indent=0) if len(sys.argv)>2 else None
    lab=sum(1 for x in r if x['zug']); print(len(r),'blaue Segmente,',lab,'mit Zugnummer')
    for x in r[:25]: print(x)
