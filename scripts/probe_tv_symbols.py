#!/usr/bin/env python3
import json, urllib.request

URL='https://scanner.tradingview.com/america/scan'
TARGETS={'ASML','ARM','SKHY'}
BASE=['name','description','close','change','volume','market_cap_basic','sector','industry','exchange','type','typespecs']

def scan(flt, cols, limit=20000):
    found={}; count=0
    for start in range(0,limit,1000):
        body={'filter':flt,'columns':cols,'sort':{'sortBy':'market_cap_basic','sortOrder':'desc'},'range':[start,start+1000]}
        req=urllib.request.Request(URL,data=json.dumps(body).encode(),headers={'Content-Type':'application/json','User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(req,timeout=40) as fh:
            data=json.load(fh).get('data') or []
        count += len(data)
        for item in data:
            d=item.get('d') or []
            if len(d)<len(cols): continue
            rec=dict(zip(cols,d)); t=str(rec.get('name') or '').upper()
            if t in TARGETS: found[t]=rec
        if len(data)<1000: break
    return count,found

baseflt=[{'left':'exchange','operation':'in_range','right':['NYSE','NASDAQ','AMEX']},
         {'left':'market_cap_basic','operation':'egreater','right':200_000_000},
         {'left':'close','operation':'egreater','right':1}]
out={}
for label,typ,rev in [('all',None,False),('dr_no_revenue','dr',False),('dr_with_revenue','dr',True),('stock_no_revenue','stock',False)]:
    flt=list(baseflt)
    if typ: flt.insert(0,{'left':'type','operation':'equal','right':typ})
    cols=list(BASE)+(['total_revenue'] if rev else [])
    try:
        n,found=scan(flt,cols)
        out[label]={'count':n,'targets':found,'error':None}
    except Exception as e:
        out[label]={'count':0,'targets':{},'error':type(e).__name__+': '+str(e)}
with open('tv_symbol_probe.json','w',encoding='utf-8') as f: json.dump(out,f,ensure_ascii=False,indent=2)
print(json.dumps(out,ensure_ascii=False,indent=2))
