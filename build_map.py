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

r=rd('routes.txt'); a=rd('agency.txt'); t=rd('trips.txt',usecols=['route_id','shape_id','trip_id'])
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
gm=dict(zip(r.route_id,r.g)); t=t[t.route_id.isin(gm)]; t['g']=t.route_id.map(gm)
log('routes',len(r),'groups',r.g.nunique())

# ---------- shapes ----------
want={}
for g,sub in t.dropna(subset=['shape_id']).groupby('g'):
    cnt=sub.shape_id.value_counts()
    if g[0]=='bus': want[g]=[cnt.index[0]]
    else: want[g]=[s for s,n in cnt.items() if n/cnt.sum()>=0.02][:12] or [cnt.index[0]]
allw=set(s for v in want.values() for s in v)
pts=collections.defaultdict(list)
for ch in pd.read_csv(zf.open('shapes.txt'),dtype={'shape_id':str},encoding='utf-8-sig',chunksize=4000000,usecols=['shape_id','shape_pt_lat','shape_pt_lon','shape_pt_sequence']):
    ch=ch[ch.shape_id.isin(allw)]
    for sid,g in ch.groupby('shape_id'): pts[sid].append(g[['shape_pt_sequence','shape_pt_lon','shape_pt_lat']].values)
def line(sid,tol):
    arr=np.concatenate(pts[sid]); arr=arr[arr[:,0].argsort()]
    return enc(LineString(arr[:,1:3]).simplify(tol).coords)
log('shapes read',len(pts))

# ---------- stops ----------
s=rd('stops.txt',usecols=['stop_id','stop_name','stop_lat','stop_lon','parent_station']).set_index('stop_id')
st=pd.read_csv(zf.open('stop_times.txt'),encoding='utf-8-sig',usecols=['trip_id','stop_id','stop_sequence','pickup_type','drop_off_type'],dtype=str)
st=st[st.trip_id.isin(set(t.trip_id))]
st=st[~((st.pickup_type=='1')&(st.drop_off_type=='1'))]
st['q']=st.stop_sequence.astype(int); st['g']=st.trip_id.map(dict(zip(t.trip_id,t.g)))
st['len']=st.trip_id.map(st.groupby('trip_id').size())
st=st.sort_values(['g','len','trip_id','q'],ascending=[True,False,True,True])
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
SO={}
for g,sub in st.groupby('g',sort=False):
    stn=g[0]!='bus'
    SO[g]=list(dict.fromkeys(sidx(x,stn) for x in sub.stop_id))
log('stops',len(S))

# ---------- entities ----------
trips=t.groupby('g').size(); E=[]
order=sorted(r.g.unique(),key=lambda g:({'bus':3,'train':0,'lr':1,'ferry':2}[g[0]],g[2]))
for g in order:
    mode,cat,code,name,_=g; sub=r[r.g==g]
    lines=[line(x,0.00025 if mode=='bus' else 0.00005) for x in want.get(g,[]) if x in pts]
    if not lines: continue
    o=SO.get(g,[]); col=sub.route_color.dropna()
    E.append([mode,code,name,', '.join(sorted(set(sub.agency_name.dropna()))),cat,(sub.route_desc.iloc[0] if mode=='bus' else ''),int(trips.get(g,0)),lines,
              ([o[0]]+[b-a for a,b in zip(o,o[1:])]) if o else [],'#'+col.iloc[0] if len(col) and mode!='bus' else '',1 if code in UNSURE else 0])
feed=dt.date.today().strftime('%-d %b %Y')
try:
    fi=rd('feed_info.txt'); feed=dt.datetime.strptime(fi.feed_start_date.iloc[0],'%Y%m%d').strftime('%-d %b %Y')
except Exception: pass
data=json.dumps(dict(S=S,E=E,feed=feed),separators=(',',':'))
html=open(sys.argv[3] if len(sys.argv)>3 else 'template.html').read().replace('__DATA__',data)
import os; os.makedirs(os.path.dirname(OUT) or '.',exist_ok=True); open(OUT,'w').write(html)
log('wrote',OUT,round(len(html)/1e6,1),'MB',collections.Counter((e[0]) for e in E))
