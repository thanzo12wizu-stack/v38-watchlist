#!/usr/bin/env python3
import json, urllib.request

URL='https://scanner.tradingview.com/america/scan'
TARGETS={'ASML','ARM','SKHY'}
cols=['name','description','type','typespecs','exchange','market_cap_basic','close','sector','industry']
flt=[{'left':'exchange','operation':'in_range','right':['NYSE','NASDAQ','AMEX']},
     {'left':'market_cap_basic','operation':'egreater','right':200_000_000},
     {'left':'close','operation':'egreater','right':1}]
found={}
counts={}
for start in range(0,20000,1000):
    body={'filter':flt,'columns':cols,'sort':{'sortBy':'market_cap_basic','sortOrder':'desc'},'range':[start,start+1000]}
    req=urllib.request.Request(URL,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','User-Agent':'Mozilla/5.0'})
    with urllib.request.urlopen(req,timeout=40) as fh:
        data=json.load(fh).get('data') or []
    for item in data:
        d=item.get('d') or []
        if len(d)<len(cols): continue
        rec=dict(zip(cols,d))
        t=str(rec.get('name') or '').upper()
        typ=str(rec.get('type') or '')
        counts[typ]=counts.get(typ,0)+1
        if t in TARGETS:
            found[t]=rec
    if len(data)<1000: break
out={'targets':found,'type_counts':counts,'missing':sorted(TARGETS-set(found))}
print(json.dumps(out,ensure_ascii=False,indent=2))
with open('tv_symbol_probe.json','w',encoding='utf-8') as f:
    json.dump(out,f,ensure_ascii=False,indent=2)
