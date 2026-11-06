#!/usr/bin/env python3
"""Build the stopping-pattern page (Intercity, Sydney Trains, ferries) from a TfNSW GTFS zip.
Usage: python3 build_patterns.py gtfs.zip site/patterns.html patterns_template.html
Writes site/patterns.html and site/data/patterns.json."""
import sys, os, io, csv, math, json, zipfile, datetime as dt, collections, re, time
T0=time.time()
def log(*a): print(f'[{time.time()-T0:5.0f}s]',*a,flush=True)
ZIP=sys.argv[1] if len(sys.argv)>1 else 'gtfs.zip'
OUT=sys.argv[2] if len(sys.argv)>2 else 'site/patterns.html'
TPL=sys.argv[3] if len(sys.argv)>3 else 'patterns_template.html'
zf=zipfile.ZipFile(ZIP)
def rows(name): return csv.DictReader(io.TextIOWrapper(zf.open(name),encoding='utf-8-sig'))

# ---------- load ----------
stn={r['stop_id']:r for r in rows('stops.txt')}
def nm(s):
    p=stn[s]['parent_station'] or s
    return stn.get(p,stn[s])['stop_name'].replace(' Station','').split(',')[0]
routes={r['route_id']:r for r in rows('routes.txt')}
def net(r):
    if r['route_desc']=='Intercity Trains Network': return 'I'
    if r['route_desc']=='Sydney Trains Network': return 'T'
    if r['route_type']=='4': return 'F'
want={k:net(r) for k,r in routes.items() if net(r)}
trips={r['trip_id']:r for r in rows('trips.txt') if r['route_id'] in want}
seq=collections.defaultdict(list)
for r in rows('stop_times.txt'):
    if r['trip_id'] in trips and not (r['pickup_type']=='1' and r['drop_off_type']=='1'):
        seq[r['trip_id']].append((int(r['stop_sequence']),nm(r['stop_id']),r['arrival_time'],r['departure_time']))
for t in seq: seq[t].sort()
log('trips',len(seq))
def mins(t): h,m,_=t.split(':'); return int(h)*60+int(m)
SN=lambda t: routes[trips[t]['route_id']]['route_short_name']

# ---------- join trips the feed splits in two (same train/ferry, same line) ----------
byblock=collections.defaultdict(list)
for t,r in trips.items():
    if r.get('block_id') and t in seq: byblock[(r['block_id'],r['service_id'])].append(t)
merged=0
for ts in byblock.values():
    ts.sort(key=lambda t: mins(seq[t][0][3] or seq[t][0][2]))
    for a,b in zip(ts,ts[1:]):
        if a in seq and b in seq and len(seq[a])>1 and len(seq[b])>1:
            A,B=seq[a],seq[b]
            if A[-1][1]==B[0][1] and 0<=mins(B[0][3])-mins(A[-1][2])<=2 and B[1][1]!=A[-2][1] and SN(a)==SN(b):
                seq[b]=A[:-1]+[(A[-1][0],A[-1][1],A[-1][2],B[0][3])]+B[1:]; del seq[a]; merged+=1
log('joined split trips',merged)

# ---------- calendar ----------
cal={r['service_id']:r for r in rows('calendar.txt')}
cd=collections.defaultdict(dict)
for r in rows('calendar_dates.txt'): cd[r['service_id']][r['date']]=r['exception_type']
alld=[c['start_date'] for c in cal.values()]+[c['end_date'] for c in cal.values()]+[d for x in cd.values() for d in x]
P=lambda s: dt.date(int(s[:4]),int(s[4:6]),int(s[6:]))
FEED=(P(min(alld)),P(max(alld)))
DW=['monday','tuesday','wednesday','thursday','friday','saturday','sunday']
dc={}
def days(s):
    if s in dc: return dc[s]
    c=cal.get(s); out=set(); d=FEED[0]
    while d<=FEED[1]:
        k=d.strftime('%Y%m%d')
        if (cd[s][k]=='1') if k in cd[s] else (c is not None and c['start_date']<=k<=c['end_date'] and c[DW[d.weekday()]]=='1'): out.add(d)
        d+=dt.timedelta(1)
    dc[s]=out; return out
DN=['Mon','Tue','Wed','Thu','Fri','Sat','Sun']
def label(ds):
    ds=sorted(ds)
    if len(ds)<=4: return ', '.join(f"{DN[d.weekday()]} {d.day} {d.strftime('%b')}" for d in ds)
    w=sorted(set(d.weekday() for d in ds)); out=[]; s=p=w[0]
    for x in w[1:]:
        if x==p+1: p=x
        else: out.append((s,p)); s=p=x
    out.append((s,p))
    l=', '.join(DN[a] if a==b else (DN[a]+'–'+DN[b] if b-a>1 else DN[a]+', '+DN[b]) for a,b in out)
    if ds[0]-FEED[0]>dt.timedelta(6): l+=f" from {ds[0].day} {ds[0].strftime('%b')}"
    if FEED[1]-ds[-1]>dt.timedelta(6): l+=f" until {ds[-1].day} {ds[-1].strftime('%b')}"
    return l

# ---------- geography: tell expresses from detours ----------
LL={}
for r in stn.values():
    n=nm(r['stop_id'])
    if n not in LL and r['stop_lat']: LL[n]=(float(r['stop_lat']),float(r['stop_lon']))
def dist(a,b): (y1,x1),(y2,x2)=LL[a],LL[b]; return math.hypot((y1-y2)*111,(x1-x2)*92)+1e-6
def pathlen(p): return sum(dist(a,b) for a,b in zip(p,p[1:]))
def physset(tl):
    """Pairs of stations that are next to each other on the track."""
    ps=set(tuple(x[1] for x in seq[t]) for t in tl); pairs=set(); skip=set()
    for p in ps:
        for a,b in zip(p,p[1:]):
            if a!=b: pairs.add(frozenset((a,b)))
        for i in range(len(p)):
            for j in range(i+2,min(len(p),i+17)):
                if p[i]!=p[j] and len(set(p[i:j+1]))==j-i+1 and pathlen(p[i:j+1])<=1.5*dist(p[i],p[j]): skip.add(frozenset((p[i],p[j])))
    return {tuple(e) for e in pairs-skip}

# ---------- hand-drawn intercity layouts ----------
IC={
'CCN':[['Western',['Blacktown','Parramatta']],['Main North',['Central','Redfern','Strathfield','Epping']],['North Shore',['Town Hall','Wynyard','Milsons Point','North Sydney','Waverton','Wollstonecraft','St Leonards','Artarmon','Chatswood','Gordon']],['Hornsby – Newcastle',['Hornsby','Asquith','Mount Colah','Mount Kuring-gai','Berowra','Cowan','Hawkesbury River','Wondabyne','Woy Woy','Koolewong','Tascott','Point Clare','Gosford','Narara','Niagara Park','Lisarow','Ourimbah','Tuggerah','Wyong','Warnervale','Wyee','Morisset','Dora Creek','Awaba','Fassifern','Booragul','Teralba','Cockle Creek','Cardiff','Kotara','Adamstown','Broadmeadow','Hamilton','Newcastle Interchange']]],
'BMT':[['Central – Bathurst',['Central','Redfern','Strathfield','Lidcombe','Parramatta','Westmead','Blacktown','Penrith','Emu Plains','Lapstone','Glenbrook','Blaxland','Warrimoo','Valley Heights','Springwood','Faulconbridge','Linden','Woodford','Hazelbrook','Lawson','Bullaburra','Wentworth Falls','Leura','Katoomba','Medlow Bath','Blackheath','Mount Victoria','Bell','Zig Zag','Lithgow','Rydal','Tarana','Bathurst']]],
'SHL':[['Central – Goulburn',['Central','Glenfield','Campbelltown','Macarthur','Menangle Park','Menangle','Douglas Park','Picton','Tahmoor','Bargo','Yerrinbool','Mittagong','Bowral','Burradoo','Moss Vale','Exeter','Bundanoon','Penrose','Wingello','Tallong','Marulan','Goulburn']]],
'HUN':[['Newcastle – Maitland',['Newcastle Interchange','Hamilton','Waratah','Warabrook','Sandgate','Hexham','Tarro','Beresfield','Thornton','Metford','Victoria Street','East Maitland','High Street','Maitland']],['To Scone',['Lochinvar','Greta','Branxton','Singleton','Muswellbrook','Aberdeen','Scone']],['To Dungog',['Telarah','Mindaribba','Paterson','Martins Creek','Hilldale','Wallarobba','Wirragulla','Dungog']]],
'SCO':[['Eastern Suburbs',['Bondi Junction','Edgecliff','Kings Cross','Martin Place','Town Hall']],['Central – Waterfall',['Central','Redfern','Sydenham','Tempe','Wolli Creek','Arncliffe','Banksia','Rockdale','Kogarah','Carlton','Allawah','Hurstville','Penshurst','Mortdale','Oatley','Como','Jannali','Sutherland','Loftus','Engadine','Heathcote','Waterfall']],['Illawarra',['Helensburgh','Otford','Stanwell Park','Coalcliff','Scarborough','Wombarra','Coledale','Austinmer','Thirroul','Bulli','Woonona','Bellambi','Corrimal','Towradgi','Fairy Meadow','North Wollongong','Wollongong','Coniston','Unanderra','Kembla Grange','Dapto','Albion Park','Oak Flats','Shellharbour Junction','Minnamurra','Bombo','Kiama']],['Kiama – Bomaderry',['Gerringong','Berry','Bomaderry']],['Port Kembla branch',['Lysaghts','Cringila','Port Kembla North','Port Kembla']]]}
ICNAME={'CCN':'Central Coast & Newcastle','BMT':'Blue Mountains','SCO':'South Coast','SHL':'Southern Highlands','HUN':'Hunter'}
def ic_rank(k,st):
    idx={s:i for i,s in enumerate(st)}; rank={s:float(i) for i,s in enumerate(st)}
    if k=='SCO':
        for j,s in enumerate(['Lysaghts','Cringila','Port Kembla North','Port Kembla']): rank[s]=idx['Coniston']+0.1*(j+1)
    if k=='CCN':
        rank['Blacktown']=-2; rank['Parramatta']=-1
        for j,s in enumerate(IC['CCN'][2][1]): rank[s]=idx['Central']+0.05*(j+1)
    if k=='HUN':
        for j,s in enumerate(IC['HUN'][2][1]): rank[s]=idx['Maitland']+0.01*(j+1)
    return rank

# ---------- one line ----------
def dd(p):
    o=[]
    for s in p:
        if s not in o: o.append(s)
    return o
def order_of(paths):
    nodes=[]; E=set()
    for p in paths:
        for s in p:
            if s not in nodes: nodes.append(s)
        for a,b in zip(p,p[1:]):
            if a!=b: E.add((a,b))
    indeg={n:0 for n in nodes}; succ=collections.defaultdict(set)
    for a,b in E: succ[a].add(b)
    for a in succ:
        for b in succ[a]: indeg[b]+=1
    out=[]; stack=[n for n in reversed(nodes) if indeg[n]==0]
    while stack:
        n=stack.pop(); out.append(n)
        for b in sorted(succ[n],key=nodes.index,reverse=True):
            indeg[b]-=1
            if indeg[b]==0: stack.append(b)
    return out+[n for n in nodes if n not in out]

def build(tlist,phys,fixed=None):
    pats=collections.Counter(tuple(x[1] for x in seq[t]) for t in tlist)
    ps=sorted(pats,key=lambda p:(-len(set(p)),-pats[p]))
    edge=lambda x,y:(x,y) in phys or (y,x) in phys
    if fixed:
        lay=[s for _,l in fixed for s in l]; extra=[s for p in ps for s in p if s not in lay]
        lay+=dd(extra); rank=ic_rank(fixed_key,lay)
        orient={p:(0 if rank[p[0]]<rank[p[-1]] else 1) for p in ps}
        sec=[]; i=0
        for t,l in fixed: sec.append([t,i,i+len(l)-1]); i+=len(l)
        if extra: sec.append(['Other',i,len(lay)-1])
        adj=None
    else:
        orient={ps[0]:0}; rest=ps[1:]; changed=True
        while rest and changed:
            changed=False
            pos={s:i for i,s in enumerate(order_of([p if orient[p]==0 else p[::-1] for p in orient]))}; nr=[]
            for p in rest:
                sh=[s for s in p if s in pos]
                if len(set(sh))>=2:
                    a=sh[0]; b=[s for s in sh if s!=a][-1]; orient[p]=0 if pos[a]<pos[b] else 1; changed=True
                else: nr.append(p)
            rest=nr
        for p in rest: orient[p]=0
        opc=sorted([(p if orient[p]==0 else p[::-1],pats[p]) for p in ps],key=lambda x:-x[1])
        lay=dd(max(opc,key=lambda x:x[1]*len(set(x[0])))[0]); allst=set(s for p,_ in opc for s in p); changed=True
        while changed and len(lay)<len(allst):
            changed=False
            for p,_ in opc:
                p=dd(p)
                for k,s in enumerate(p):
                    if s in lay: continue
                    pv=p[k-1] if k>0 else None; nx=p[k+1] if k+1<len(p) else None
                    if pv in lay:
                        i=lay.index(pv)
                        if i==len(lay)-1 or not edge(pv,lay[i+1]): lay.insert(i+1,s)
                        else: lay.append(s)
                        changed=True
                    elif nx in lay:
                        i=lay.index(nx)
                        if i==0: lay.insert(0,s)
                        elif not edge(lay[i-1],nx): lay.insert(i,s)
                        else: lay.append(s)
                        changed=True
        blocks=[[lay[0]]]
        for i in range(1,len(lay)):
            if edge(lay[i-1],lay[i]): blocks[-1].append(lay[i])
            else: blocks.append([lay[i]])
        m=True
        while m and len(blocks)>1:
            m=False
            for i in range(len(blocks)):
                for j in range(1,len(blocks)):
                    if i==j: continue
                    A,B=blocks[i],blocks[j]; nb=None
                    if edge(A[-1],B[0]): nb=A+B
                    elif edge(A[-1],B[-1]): nb=A+B[::-1]
                    elif i==0 and edge(A[0],B[-1]): nb=B+A
                    elif i==0 and edge(A[0],B[0]): nb=B[::-1]+A
                    if nb: blocks[i]=nb; del blocks[j]; m=True; break
                if m: break
        lay=[s for b in blocks for s in b]
        adj=[edge(lay[i],lay[i+1]) for i in range(len(lay)-1)]
        sec=[]; s0=0
        for i,a in enumerate(adj):
            if not a: sec.append([lay[s0]+' – '+lay[i] if i>s0 else lay[s0],s0,i]); s0=i+1
        sec.append([lay[s0]+' – '+lay[-1] if len(lay)-1>s0 else lay[s0],s0,len(lay)-1])
    idx={s:i for i,s in enumerate(lay)}; Pt={}
    for t in tlist:
        l=seq[t]; names=tuple(x[1] for x in l); ids=[idx[n] for n in names]; tm=[mins(x[3] or x[2]) for x in l]
        o=orient[names]; e=Pt.setdefault(tuple(sorted(set(ids))),{'c':[0,0],'path':None,'runs':{}})
        ds=days(trips[t]['service_id']); e['c'][o]+=len(ds)
        if o==0 and e['path'] is None: e['path']=ids
        e['runs'].setdefault((o,tuple(ids),tuple(tm)),set()).update(ds)
    pl=[]
    for e in Pt.values():
        if sum(e['c'])==0: continue
        path=e['path'] or list(reversed(next(iter(e['runs']))[1]))
        runs=sorted([[d,list(i),list(m),label(s)] for (d,i,m),s in e['runs'].items() if s],key=lambda x:(x[0],x[2][0]))
        pl.append([path,e['c'][0],e['c'][1],runs])
    pl.sort(key=lambda p:-(p[1]+p[2]))
    out={'st':lay,'sec':sec,'p':pl}
    if adj is not None: out['adj']=adj
    return out

groups=collections.defaultdict(list)
for t in seq:
    r=routes[trips[t]['route_id']]; groups[(want[r['route_id']],r['route_short_name'],r['route_long_name'])].append(t)
GPHYS={'T':physset([t for (n,_,_),tl in groups.items() if n=='T' for t in tl])}
def num(c): m=re.search(r'\d+',c); return int(m.group()) if m else 999
RES={'I':[],'T':[],'F':[]}
for (n,sn,ln),tl in sorted(groups.items(),key=lambda x:(x[0][0],0 if re.fullmatch(r'[TF]\d+',x[0][1]) else 1,num(x[0][1]),x[0][1])):
    if n=='I' and sn not in IC: continue
    fixed_key=sn
    phys=(GPHYS['T'] if n=='T' else set())|physset(tl)
    d=build(tl,phys,IC.get(sn) if n=='I' else None)
    d.update(k=sn,n=ICNAME.get(sn) or (ln[len(sn)+1:] if ln.startswith(sn+' ') else ln))
    RES[n].append(d); log(sn,len(d['st']),'stations',len(d['p']),'patterns')
RES['I'].sort(key=lambda L:list(ICNAME).index(L['k']))

# ---------- branches ----------
def sp(s): return [x.strip() for x in s.split(',')]
CC=sp('Central, Museum, St James, Circular Quay, Wynyard, Town Hall')
NSH=sp('Waitara, Wahroonga, Warrawee, Turramurra, Pymble, Gordon, Killara, Lindfield, Roseville, Chatswood, Artarmon, St Leonards, Wollstonecraft, Waverton, North Sydney, Milsons Point, Wynyard, Town Hall, Central')
BER=sp('Berowra, Mount Kuring-gai, Mount Colah, Asquith, Hornsby')
IW=sp('Redfern, Macdonaldtown, Newtown, Stanmore, Petersham, Lewisham, Summer Hill, Ashfield, Croydon, Burwood, Strathfield, Homebush, Flemington, Lidcombe, Auburn, Clyde, Granville, Olympic Park')
WT=['Central']+IW+sp('Harris Park, Parramatta, Westmead, Wentworthville, Pendle Hill, Toongabbie, Seven Hills, Blacktown')
SW=sp('Merrylands, Guildford, Yennora, Fairfield, Canley Vale, Cabramatta, Warwick Farm, Liverpool, Casula, Glenfield')
MAC=sp('Glenfield, Macquarie Fields, Ingleburn, Minto, Leumeah, Campbelltown, Macarthur')
RICH=sp('Marayong, Quakers Hill, Schofields, Riverstone, Vineyard, Mulgrave, Windsor, Clarendon, East Richmond, Richmond')
EMU=sp('Doonside, Rooty Hill, Mount Druitt, St Marys, Werrington, Kingswood, Penrith, Emu Plains')
T4S=CC+sp('Bondi Junction, Edgecliff, Kings Cross, Martin Place, Redfern, Erskineville, St Peters, Sydenham, Tempe, Wolli Creek, Arncliffe, Banksia, Rockdale, Kogarah, Carlton, Allawah, Hurstville, Penshurst, Mortdale, Oatley, Como, Jannali, Sutherland')
EH=sp('Wolli Creek, Turrella, Bardwell Park, Bexley North, Kingsgrove, Beverly Hills, Narwee, Riverwood, Padstow, Revesby, Panania, East Hills, Holsworthy')+MAC
W5=sp('Blacktown, Seven Hills, Toongabbie, Pendle Hill, Wentworthville, Westmead, Parramatta')
SEC=lambda k,t:[s for x,l in IC[k] if x==t for s in l]
HN=SEC('CCN','Hornsby – Newcastle'); NS=SEC('CCN','North Shore'); ILL=SEC('SCO','Central – Waterfall')+SEC('SCO','Illawarra')
BMT=[s for _,l in IC['BMT'] for s in l]; SHL=[s for _,l in IC['SHL'] for s in l]
B={
'T1':[['North Shore Line','Berowra to Central via Gordon',BER+NSH],['Western Line','Central to Emu Plains',WT+EMU],['Richmond Line','Central to Richmond via Blacktown',WT+RICH]],
'T2':[['Leppington Line','City Circle to Leppington via Granville',CC+IW+SW+['Edmondson Park','Leppington']],['Parramatta Line','City Circle to Parramatta via the Inner West',CC+IW+['Harris Park','Parramatta']],['Macarthur extras','Glenfield to Macarthur',MAC]],
'T4':[['Cronulla Line','Bondi Junction to Cronulla',T4S+sp('Kirrawee, Gymea, Miranda, Caringbah, Woolooware, Cronulla')],['Illawarra Line','Bondi Junction to Waterfall',T4S+sp('Loftus, Engadine, Heathcote, Waterfall')]],
'T5':[['Cumberland Line','Richmond to Leppington via Parramatta',RICH+W5+['Harris Park']+SW+['Edmondson Park','Leppington']],['Macarthur shuttle','Leppington or Glenfield to Macarthur',['Leppington','Edmondson Park']+MAC],['Penrith extras','Penrith to Parramatta',EMU[:-1]+W5]],
'T7':[['Olympic Park shuttle','Lidcombe to Olympic Park',['Lidcombe','Olympic Park']],['Event specials','Central or Blacktown to Olympic Park','ALLBUT:Lidcombe']],
'T8':[['Airport Line','City Circle to Macarthur via the Airport',CC+sp('Green Square, Mascot, Domestic Airport, International Airport')+EH],['Sydenham Line','City Circle to Macarthur via Sydenham',CC+sp('Redfern, Erskineville, St Peters, Sydenham, Tempe')+EH],['Leppington Line','Glenfield to Leppington',['Glenfield','Edmondson Park','Leppington']]],
'T9':[['North Shore Line','Hornsby to Central via Gordon',['Hornsby']+NSH],['Main North Line','Central to Hornsby via Strathfield',sp('Central, Redfern, Macdonaldtown, Newtown, Stanmore, Petersham, Lewisham, Summer Hill, Ashfield, Croydon, Burwood, Strathfield, North Strathfield, Concord West, Rhodes, Meadowbank, West Ryde, Denistone, Eastwood, Epping, Cheltenham, Beecroft, Pennant Hills, Thornleigh, Normanhurst, Hornsby')],['Berowra shuttle','Hornsby to Berowra',BER]],
'CCN':[['Via Strathfield','Central to Newcastle via Epping',['Central','Redfern','Strathfield','Epping']+HN],['Via North Shore','Central to the Central Coast via Gordon',['Central']+NS+HN],['From Blacktown','Via-Gordon runs from Blacktown',['Blacktown','Parramatta']]],
'BMT':[['Blue Mountains','Central to Lithgow',BMT[:BMT.index('Lithgow')+1]],['Bathurst','Lithgow to Bathurst',BMT[BMT.index('Lithgow'):]]],
'SCO':[['Illawarra','Central to Kiama',ILL],['Port Kembla branch','Coniston to Port Kembla',['Coniston']+SEC('SCO','Port Kembla branch')],['Shoalhaven','Kiama to Bomaderry',['Kiama']+SEC('SCO','Kiama – Bomaderry')],['Eastern Suburbs through-runs','Bondi Junction to the South Coast',SEC('SCO','Eastern Suburbs')+['Central']]],
'SHL':[['Southern Highlands','Campbelltown to Moss Vale',SHL[:SHL.index('Moss Vale')+1]],['Goulburn','Moss Vale to Goulburn',SHL[SHL.index('Moss Vale'):]]],
'HUN':[['Newcastle to Maitland','Including Telarah',SEC('HUN','Newcastle – Maitland')+['Telarah']],['Dungog branch','Telarah to Dungog',['Maitland']+SEC('HUN','To Dungog')],['Scone branch','Maitland to Scone',['Maitland']+SEC('HUN','To Scone')]]}
for L in RES['I']+RES['T']:
    if L['k'] not in B: continue
    st=L['st']; L['br']=[]
    for n,dsc,names in B[L['k']]:
        if isinstance(names,str): ex=names.split(':')[1]; names=[s for s in st if s!=ex]
        L['br'].append([n,dsc,sorted(set(st.index(x) for x in names if x in st))])

os.makedirs(os.path.join(os.path.dirname(OUT) or '.','data'),exist_ok=True)
RES['feed']=[FEED[0].isoformat(),FEED[1].isoformat()]
jp=os.path.join(os.path.dirname(OUT) or '.','data','patterns.json')
json.dump(RES,open(jp,'w'),separators=(',',':'),ensure_ascii=False); log('wrote',jp,round(os.path.getsize(jp)/1e6,1),'MB')
f=lambda d: f"{d.day} {d.strftime('%B %Y')}"
html=open(TPL).read().replace('__VER__',dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d%H%M')).replace('__RANGE__',f"{f(FEED[0])} to {f(FEED[1])}")
open(OUT,'w').write(html); log('wrote',OUT)
