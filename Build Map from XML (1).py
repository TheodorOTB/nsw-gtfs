#!/usr/bin/env python3
"""Build the NSW public transport map (index.html) from a TfNSW complete GTFS zip.
Usage: python3 build_map.py gtfs.zip site/index.html"""
import sys, re, json, time, zipfile, collections, datetime as dt
import numpy as np, pandas as pd
from shapely.geometry import LineString
T0=time.time()
def log(*a): print(f'[{time.time()-T0:5.0f}s]',*a,flush=True)
ZIP=sys.argv[1] if len(sys.argv)>1 else 'gtfs.zip'; OUT=sys.argv[2] if len(sys.argv)>2 else 'site/index.html'
zf=zipfile.ZipFile(ZIP)
rd=lambda n,**k: pd.read_csv(zf.open(n),dtype=str,encoding='utf-8-sig',low_memory=False,**k)

def enc(coords):
    out=[];pl=0;pn=0
    for lon,lat in coords:
        la=int(round(lat*1e5)); lo=int(round(lon*1e5))
        for v in (la-pl,lo-pn):
            v=~(v<<1) if v<0 else v<<1
            while v>=0x20: out.append(chr((0x20|(v&0x1f))+63)); v>>=5
            out.append(chr(v+63))
        pl,pn=la,lo
    return ''.join(out)

r=rd('routes.txt'); a=rd('agency.txt'); t=rd('trips.txt',usecols=['route_id','shape_id','trip_id','direction_id','trip_headsign'])
r=r.merge(a[['agency_id','agency_name']],on='agency_id',how='left')
r=r[r.route_type.isin(['700','712','714','204','205','2','106','401','900','4'])].copy()

# ---------- classify ----------
REP=re.compile(r'^\d{1,2}A?(T\d|HU|BM|CN|SC|SH|M)$')
TL={'31':'Sydney – Brisbane XPT','32':'Sydney – Brisbane XPT','33':'Sydney – Casino XPT','34':'Sydney – Casino XPT','35':'Sydney – Grafton XPT','36':'Sydney – Grafton XPT',
 '621':'Sydney – Melbourne XPT','622':'Sydney – Melbourne XPT','623':'Sydney – Melbourne XPT','624':'Sydney – Melbourne XPT','427':'Sydney – Dubbo XPT','428':'Sydney – Dubbo XPT',
 '631':'Sydney – Canberra Xplorer','632':'Sydney – Canberra Xplorer','633':'Sydney – Canberra Xplorer','634':'Sydney – Canberra Xplorer','635':'Sydney – Canberra Xplorer','636':'Sydney – Canberra Xplorer',
 '223':'Sydney – Armidale Xplorer','224':'Sydney – Armidale Xplorer','243':'Sydney – Moree Xplorer','244':'Sydney – Moree Xplorer','445':'Sydney – Broken Hill Outback Xplorer','446':'Sydney – Broken Hill Outback Xplorer',
 '641':'Sydney – Griffith Xplorer','642':'Sydney – Griffith Xplorer','643':'Sydney – Griffith Xplorer','644':'Sydney – Griffith Xplorer'}
TLC={'Sydney – Brisbane XPT':'XPT N','Sydney – Casino XPT':'XPT C','Sydney – Grafton XPT':'XPT G','Sydney – Melbourne XPT':'XPT S','Sydney – Dubbo XPT':'XPT W','Sydney – Canberra Xplorer':'XPL C','Sydney – Armidale Xplorer':'XPL A','Sydney – Moree Xplorer':'XPL M','Sydney – Broken Hill Outback Xplorer':'OXP','Sydney – Griffith Xplorer':'XPL G'}
FULL={'F1','F2','F3','F4','F5','F6','F7','F8','F9','F10','MFF','Stkn','BRKL'}; PAY={'CCLC','CCSH','CCTZ','CCWB','CCWM'}; UNSURE={'CHCP','EMPB','BUNC','CRF'}
LRN={'L1':('L1 Inner West','L1 Inner West (Dulwich Hill)'),'L2':('L2 Randwick','L2 Randwick'),'L3':('L3 Juniors Kingsford','L3 Juniors Kingsford'),'L4':('L4 Parramatta','L4 Parramatta (Westmead – Carlingford)'),'NLR':('NLR Newcastle','Newcastle Light Rail'),'LX':('LX Special events','LX Special event services')}
def group(x):
    rt=x.route_type; c=str(x.route_short_name); ln=x.route_long_name if x.route_long_name!='Unknown' else ''
    if rt in ('700','712','714','204','205'):
        if rt=='712': k='School bus'
        elif REP.match(c) or c in ('SW1','SW2','SW3','SC01','SH100','11M'): k='Rail replacement bus'
        elif rt=='714': k='Event & other temporary bus'
        elif rt=='204': k='TrainLink coach'
        elif rt=='205': k='Temporary coach'
        elif re.match(r'^N\d+$',c): k='Night bus'
        elif 'X' in c.upper(): k='Express bus'
        elif 'coach' in str(x.route_desc).lower(): k='Private coach'
        else: k='Regular bus'
        return ('bus',k,c,ln,x.route_id)          # one entity per bus route_id
    if rt=='2': return ('train','Sydney Trains' if x.agency_name=='Sydney Trains' else 'Intercity trains',c,ln,'')
    if rt=='401': return ('train','Sydney Metro',c,ln,'')
    if rt=='106': nm=TL.get(c,c); return ('train','NSW TrainLink',TLC.get(nm,c),nm,'')
    if rt=='900': k,nm=LRN.get(c,(c,ln)); return ('lr',k,c,nm,'')
    if rt=='4':
        k='Full Opal' if c in FULL else 'Opal Pay' if c in PAY else 'No Opal payment'
        return ('ferry',k,c,ln[len(c)+1:] if ln.startswith(c+' ') else ln,'')
r['g']=r.apply(group,axis=1)
gm=dict(zip(r.route_id,r.g)); t=t[t.route_id.isin(gm)].copy()
t['direction_id']=t.direction_id.fillna('0')
t['g']=[gm[ri]+((d,) if gm[ri][0]=='bus' else ('',)) for ri,d in zip(t.route_id,t.direction_id)]
log('routes',len(r),'groups',r.g.nunique())

# ---------- shapes ----------
want={}; NML={}
for g,sub in t.dropna(subset=['shape_id']).groupby('g'):
    cnt=sub.shape_id.value_counts()
    if g[0]=='bus':
        mains=[cnt.index[0]]
        want[g]=mains+[s for s,n in cnt.items() if s not in mains and n/cnt.sum()>=0.005][:4]; NML[g]=1
    else: want[g]=list(cnt.index)   # all variants; reduced below by coverage
allw=set(s for v in want.values() for s in v)
pts=collections.defaultdict(list)
for ch in pd.read_csv(zf.open('shapes.txt'),dtype={'shape_id':str},encoding='utf-8-sig',chunksize=4000000,usecols=['shape_id','shape_pt_lat','shape_pt_lon','shape_pt_sequence']):
    ch=ch[ch.shape_id.isin(allw)]
    for sid,g in ch.groupby('shape_id'): pts[sid].append(g[['shape_pt_sequence','shape_pt_lon','shape_pt_lat']].values)
def line(sid,tol):
    arr=np.concatenate(pts[sid]); arr=arr[arr[:,0].argsort()]
    return enc(LineString(arr[:,1:3]).simplify(tol).coords)
log('shapes read',len(pts))
# trains / light rail / ferries: pick the fewest paths that cover every piece of track the line uses
def cells(sid):
    arr=np.concatenate(pts[sid]); return {(int(lo/0.002),int(la/0.002)) for _,lo,la in arr}
for g in list(want):
    if g[0]=='bus': continue
    cand=[x for x in want[g] if x in pts]; cs={x:cells(x) for x in cand}; cov=set(); pick=[]
    while len(pick)<20:
        best=max(cand,key=lambda x:(len(cs[x]-cov),-cand.index(x)),default=None)
        if best is None or len(cs[best]-cov)<3: break
        pick.append(best); cov|=cs[best]; cand.remove(best)
    want[g]=pick or want[g][:1]
log('rail paths chosen')

# ---------- stops ----------
s=rd('stops.txt',usecols=['stop_id','stop_name','stop_lat','stop_lon','parent_station']).set_index('stop_id')
st=pd.read_csv(zf.open('stop_times.txt'),encoding='utf-8-sig',usecols=['trip_id','stop_id','stop_sequence','pickup_type','drop_off_type'],dtype=str)
st=st[st.trip_id.isin(set(t.trip_id))]
st=st[~((st.pickup_type=='1')&(st.drop_off_type=='1'))]
st['q']=st.stop_sequence.astype(int); st['g']=st.trip_id.map(dict(zip(t.trip_id,t.g)))
mainshape={g:set(v[:NML.get(g,len(v))]) for g,v in want.items()}
t['ismain']=[sh in mainshape.get(g,()) for sh,g in zip(t.shape_id,t.g)]
st['main']=st.trip_id.map(dict(zip(t.trip_id,t.ismain))).fillna(False).astype(int)
st['len']=st.trip_id.map(st.groupby('trip_id').size())
st=st.sort_values(['g','main','len','trip_id','q'],ascending=[True,False,False,True,True])
log('stop_times',len(st))
S=[]; key={}; cache={}
def sidx(sid,station):
    ck=(sid,station)
    if ck in cache: return cache[ck]
    row=s.loc[sid]
    if station and isinstance(row.parent_station,str) and row.parent_station in s.index: row=s.loc[row.parent_station]
    nm=row.stop_name
    if station: nm=re.sub(r', (Side [AB]|Platform \d+)$','',nm)
    k=(int(round(float(row.stop_lat)*1e5)),int(round(float(row.stop_lon)*1e5)),nm)
    if k not in key: key[k]=len(S); S.append(list(k))
    cache[ck]=key[k]; return key[k]
SO={}; NM={}
for g,sub in st.groupby('g',sort=False):
    stn=g[0]!='bus'
    allst=list(dict.fromkeys(sidx(x,stn) for x in sub.stop_id))
    m=sub[sub.main==1]
    if g[0]=='bus' and len(m):
        first=m.trip_id.iloc[0]
        mains=list(dict.fromkeys(sidx(x,stn) for x in m[m.trip_id==first].stop_id))
        rest_main=[x for x in dict.fromkeys(sidx(y,stn) for y in m.stop_id) if x not in set(mains)]
        mains=mains+rest_main
        SO[g]=mains+[x for x in allst if x not in set(mains)]; NM[g]=len(mains)
    else: SO[g]=allst; NM[g]=len(allst)
log('stops',len(S))

# ---------- entities ----------
trips=t.groupby('g').size(); E=[]; EG=[]
order=sorted(t.g.unique(),key=lambda g:({'bus':3,'train':0,'lr':1,'ferry':2}[g[0]],g[2],g[4],g[5]))
rsub={g:sub for g,sub in r.groupby('g')}
hs=t.groupby('g').trip_headsign.agg(lambda x:x.value_counts().index[0] if x.notna().any() else '') if 'trip_headsign' in t else {}
def short(n): 
    n=re.sub(r' (Station|Interchange|Light Rail|Wharf)?,? ?(Stand|Platform|Side) [A-Z0-9]+$','',str(n)); return n.split(',')[0].replace(' Station','')
for g in order:
    mode,cat,code,name,_,dirn=g; sub=rsub[g[:5]]
    if mode=='bus' and SO.get(g):
        o_=SO[g]; first=S[o_[0]][2]; last=S[o_[NM.get(g,len(o_))-1]][2]
        dest=hs.get(g,'') if hasattr(hs,'get') else ''
        others=[x for x in hs.index if x[:5]==g[:5] and x!=g] if hasattr(hs,'index') else []
        orig=hs.get(others[0],'') if others else ''
        if not orig or orig==dest: orig=short(first)
        name=f"{orig} to {dest or short(last)}"
        name+=f"  ·  {g[3]}" if False else ''
    lines=[line(x,(0.00025 if i==0 else 0.0004) if mode=='bus' else 0.00005) for i,x in enumerate(want.get(g,[])) if x in pts]
    if not lines: continue
    o=SO.get(g,[]); col=sub.route_color.dropna()
    E.append([mode,code,name,', '.join(sorted(set(sub.agency_name.dropna()))),cat,(sub.route_desc.iloc[0] if mode=='bus' else ''),int(trips.get(g,0)),lines,
              ([o[0]]+[b-a for a,b in zip(o,o[1:])]) if o else [],'#'+col.iloc[0] if len(col) and mode!='bus' else '',1 if code in UNSURE else 0,NM.get(g,len(o)),NML.get(g,len(lines)),(g[4] if mode=='bus' else '')+'|'+g[3],
              ]); EG.append(g)
feed=dt.date.today().strftime('%-d %b %Y')
try:
    fi=rd('feed_info.txt'); feed=dt.datetime.strptime(fi.feed_start_date.iloc[0],'%Y%m%d').strftime('%-d %b %Y')
except Exception: pass
# ---------- shared-stretch networks ----------
GRID=0.0004   # ~40 m cells
def build_network(items, step=0.00018):
    """items: list of (entity_id, Nx2 array lon,lat). Returns list of (encoded_line_coords, [entity ids])"""
    T=time.time()
    eids=[];ca=[];cb=[];sx=[];sy=[];cell_all=[]
    for eid,arr in items:
        if len(arr)<2: continue
        seg=np.diff(arr,axis=0); d=np.hypot(seg[:,0],seg[:,1]); n=np.maximum(1,np.ceil(d/step).astype(int))
        idx=np.repeat(np.arange(len(seg)),n); frac=np.concatenate([np.arange(k)/k for k in n])
        p=np.vstack([arr[idx]+seg[idx]*frac[:,None],arr[-1:]])
        cx=np.floor(p[:,0]/GRID).astype(np.int64); cy=np.floor(p[:,1]/GRID).astype(np.int64)
        c=cx*1000003+cy
        keep=np.r_[True,c[1:]!=c[:-1]]; c=c[keep]
        cell_all.append(pd.DataFrame({'c':cx*1000003+cy,'x':p[:,0],'y':p[:,1]}))
        if len(c)<2: continue
        a=np.minimum(c[:-1],c[1:]); b=np.maximum(c[:-1],c[1:])
        ca.append(a); cb.append(b); eids.append(np.full(len(a),eid))
    cells=pd.concat(cell_all).groupby('c')[['x','y']].mean()
    ed=pd.DataFrame({'a':np.concatenate(ca),'b':np.concatenate(cb),'e':np.concatenate(eids)}).drop_duplicates()
    sig=ed.groupby(['a','b']).e.agg(lambda s:tuple(sorted(s))).reset_index()
    print('edges',len(sig),'cells',len(cells),round(time.time()-T,1),'s')
    # chain edges with identical route sets into polylines
    out=[]
    cxy=cells.to_dict('index')
    for s,g in sig.groupby('e'):
        adj=collections.defaultdict(list)
        for a,b in zip(g.a.values,g.b.values): adj[a].append(b); adj[b].append(a)
        used=set()
        def walk(start,nxt):
            line=[start,nxt]; used.add((min(start,nxt),max(start,nxt))); prev,cur=start,nxt
            while len(adj[cur])==2:
                o=adj[cur][0] if adj[cur][1]==prev else adj[cur][1]
                k=(min(cur,o),max(cur,o))
                if k in used: break
                used.add(k); line.append(o); prev,cur=cur,o
            return line
        for v in adj:
            if len(adj[v])!=2:
                for w in adj[v]:
                    if (min(v,w),max(v,w)) not in used: out.append((walk(v,w),list(s)))
        for v in adj:                      # pure loops
            for w in adj[v]:
                if (min(v,w),max(v,w)) not in used: out.append((walk(v,w),list(s)))
    res=[([(cxy[c]['x'],cxy[c]['y']) for c in line],ids) for line,ids in out]
    print('segments',len(res),round(time.time()-T,1),'s')
    return res

def raw(sid):
    arr=np.concatenate(pts[sid]); return arr[arr[:,0].argsort()][:,1:3]
def net_for(sel):
    items=[]
    for i,(e,g) in enumerate(zip(E,EG)):
        if not sel(e): continue
        shapes=want[g][:1] if e[0]=='bus' else want[g]
        for sid in shapes:
            if sid in pts: items.append((i,raw(sid)))
    res=build_network(items,step=GRID*0.45)
    L=[];C=[];I=[]
    for coords,ids in res:
        if len(coords)<2: continue
        ls=LineString(coords)
        L.append(enc(ls.simplify(0.0001).coords)); C.append(enc(ls.simplify(0.0015).coords)); I.append(ids)
    return dict(L=L,C=C,I=I)
import os
outdir=os.path.dirname(OUT) or '.'; os.makedirs(outdir+'/data',exist_ok=True)
def dump(name,obj):
    p=f"{outdir}/data/{name}.json"; json.dump(obj,open(p,'w'),separators=(',',':')); log('wrote',p,round(os.path.getsize(p)/1e6,1),'MB')
rec=lambda i,e:[i]+e[:7]+[[],[]]+e[9:]          # metadata only; paths + stop lists go in geo_* files
geo=lambda sel:{str(i):[e[7],e[8]] for i,e in enumerate(E) if sel(e)}
isb=lambda e:e[0]=='bus'; issch=lambda e:e[0]=='bus' and e[4]=='School bus'
isr=lambda e:not isb(e); isbus=lambda e:isb(e) and not issch(e)
dump('stops',dict(S=S))
for nm,f in (('rail',isr),('bus',isbus),('school',issch)):
    dump(nm,dict(E=[rec(i,e) for i,e in enumerate(E) if f(e)])); dump('geo_'+nm,geo(f))
GRID=0.0004; dump('net_rail',net_for(lambda e:not isb(e)))
GRID=0.0005; dump('net_bus',net_for(lambda e:isb(e) and not issch(e)))
dump('net_school',net_for(issch))
html=open(sys.argv[3] if len(sys.argv)>3 else 'template.html').read().replace('__FEED__',feed).replace('__VER__',dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d%H%M'))
open(OUT,'w').write(html); log('wrote',OUT,collections.Counter((e[0]) for e in E))
