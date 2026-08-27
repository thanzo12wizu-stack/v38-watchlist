from __future__ import annotations
from pathlib import Path
import json, numpy as np, pandas as pd

# Reuse Stage36 exact hierarchy, target and tax-account machinery without running Stage36 grid.
src = Path("research/tqqq_stage36_goal_first_taxaware.py").read_text()
prefix = src.split("SPECS = [{\"name\":\"CURRENT\"}")[0]
exec(compile(prefix, "stage36-prefix", "exec"), globals())

print("\n=== STAGE37 AGGRESSIVE FRONTIER FINAL SEARCH ===", flush=True)

NSIM37 = 1000
TAXSIM37 = 300
H37 = 2520
BLOCK37 = 120
SEED37N = 370827
SEED37B = 370828

# The Stage36 scan showed A2_MC35 dominated the historical MDD-constrained frontier.
# A2_MC35 = QQQ above SMA200 AND VWAP252 AND MC57>=35.
SPECS37 = [{"name":"CURRENT"},{"name":"BUYHOLD"}]
for base in (.30,.40,.50,.60,.70,.80):
    for bull in (.60,.70,.80,.90,1.00):
        if bull + 1e-12 < base:
            continue
        SPECS37.append({"name":f"B{int(base*100)}_A2_MC35_F{int(bull*100)}","base":base,"bull":bull,"cond":"A2_MC35"})

# Add non-MC structural comparators at the key aggressive settings.
for base,bull in [(.40,.90),(.50,1.0),(.60,1.0),(.70,1.0),(.80,1.0)]:
    SPECS37.append({"name":f"B{int(base*100)}_A2_F{int(bull*100)}","base":base,"bull":bull,"cond":"A2"})

curA = current_trace(A)
hist=[]; th={}
for spec in SPECS37:
    t=make_target(A,spec,curA); th[spec["name"]]=t
    model,_,_=from_target(A,t,COST)
    pre=account_end(A["ret"],t,COST,0.0,DTS)
    aft=account_end(A["ret"],t,COST,TAX,DTS)
    hist.append({
        "candidate":spec["name"],"base":spec.get("base",np.nan),"bull":spec.get("bull",np.nan),"cond":spec.get("cond",""),
        "model_cagr":model["cagr"],"model_mdd":model["mdd"],"avg_exp":model["avg_exp"],"turnover":model["turnover"],
        "pre_cagr":pre["cagr"],"pre_mdd":pre["mdd"],"pre_end":pre["end"],
        "tax_cagr":aft["cagr"],"tax_end":aft["end"],"taxes_paid":aft["taxes_paid"]
    })
HIST=pd.DataFrame(hist); HIST.to_csv("tqqq_stage37_historical.csv",index=False)

# Select frontier controls and every candidate that either clears tax 30% with <=55% MDD,
# or is the best after-tax candidate in a drawdown band.
sel=["CURRENT","BUYHOLD"]
for cap in (.35,.40,.45,.50,.55,.60):
    g=HIST[(HIST.candidate!="BUYHOLD")&(HIST.pre_mdd>=-cap)]
    if len(g): sel.append(str(g.sort_values("tax_cagr",ascending=False).iloc[0].candidate))
goal=HIST[(HIST.tax_cagr>=.30)&(HIST.pre_mdd>=-.55)].sort_values(["tax_cagr","pre_mdd"],ascending=[False,False])
sel += goal.head(8).candidate.tolist()
sel=list(dict.fromkeys(sel))
SPECMAP={s["name"]:s for s in SPECS37 if s["name"] in sel}
print("SELECTED",sel,flush=True)

# Subperiods.
PER=[("2011-2015",2011,2015),("2016-2018",2016,2018),("2019-2021",2019,2021),("2022-2024",2022,2024),("2025-2026",2025,2026)]
wf=[]
for nm in sel:
    t=th[nm]
    for lab,a,b in PER:
        ids=np.flatnonzero((YY>=a)&(YY<=b))
        rr=A["ret"][ids]; tt=t[ids]; dd=DTS.iloc[ids].reset_index(drop=True)
        pre=account_end(rr,tt,COST,0.0,dd); aft=account_end(rr,tt,COST,TAX,dd)
        wf.append({"candidate":nm,"period":lab,"pre_cagr":pre["cagr"],"pre_mdd":pre["mdd"],"tax_cagr":aft["cagr"],"tax_end":aft["end"]})
WF=pd.DataFrame(wf); WF.to_csv("tqqq_stage37_subperiods.csv",index=False)

# Cost sensitivity.
cr=[]
for nm in sel:
    t=th[nm]
    for bps in (5,10,20):
        c=bps/10000.
        pre=account_end(A["ret"],t,c,0.0,DTS); aft=account_end(A["ret"],t,c,TAX,DTS)
        cr.append({"candidate":nm,"cost_bps":bps,"pre_cagr":pre["cagr"],"pre_mdd":pre["mdd"],"tax_cagr":aft["cagr"],"tax_end":aft["end"]})
COST37=pd.DataFrame(cr); COST37.to_csv("tqqq_stage37_costs.csv",index=False)

# Normal bootstrap, same-state moving blocks. Tax account on first TAXSIM37 paths.
L=len(A["ret"]); nb=int(np.ceil(H37/BLOCK37)); offs=np.arange(BLOCK37)
rng=np.random.default_rng(SEED37N)
starts=rng.integers(0,L-BLOCK37+1,size=(NSIM37,nb))
paths=(starts[:,:,None]+offs).reshape(NSIM37,-1)[:,:H37]
normal=[]; ntax=[]
for s in range(NSIM37):
    ix=paths[s]; B={k:A[k][ix].copy() for k in KEYS}; cur=current_trace(B)
    for nm,spec in SPECMAP.items():
        t=make_target(B,spec,cur); m,_,_=from_target(B,t,COST)
        normal.append({"sim":s,"candidate":nm,**m})
        if s<TAXSIM37:
            pre=account_end(B["ret"],t,COST,0.0,None); aft=account_end(B["ret"],t,COST,TAX,None)
            ntax.append({"sim":s,"candidate":nm,"pre_cagr":pre["cagr"],"pre_mdd":pre["mdd"],"tax_cagr":aft["cagr"],"tax_end":aft["end"]})
    if (s+1)%100==0: print("[normal37]",s+1,"/",NSIM37,flush=True)
NORMAL=pd.DataFrame(normal); NORMAL.to_csv("tqqq_stage37_normal_mc.csv",index=False)
NTAX=pd.DataFrame(ntax); NTAX.to_csv("tqqq_stage37_normal_tax_mc.csv",index=False)

# Adversarial Bear stress.
rng=np.random.default_rng(SEED37B)
starts=rng.integers(0,L-BLOCK37+1,size=(NSIM37,nb))
paths=(starts[:,:,None]+offs).reshape(NSIM37,-1)[:,:H37]
families=np.array((["dotcom_like"]*250)+(["gfc_like"]*250)+(["covid_like"]*250)+(["2022_like"]*250),dtype=object); rng.shuffle(families)
bear=[]
for s in range(NSIM37):
    ix=paths[s]; B={k:A[k][ix].copy() for k in KEYS}; fam=str(families[s]); ep=make_episode(fam,rng); le=len(ep["ret"])
    if le>=H37-504:
        cut=(le-(H37-504))//2; ep={k:v[cut:cut+(H37-504)] for k,v in ep.items()}; le=len(ep["ret"])
    pos=int(rng.integers(252,max(253,H37-le-252)))
    for k in KEYS: B[k][pos:pos+le]=ep[k]
    cur=current_trace(B)
    for nm,spec in SPECMAP.items():
        t=make_target(B,spec,cur); m,_,_=from_target(B,t,COST)
        bear.append({"sim":s,"family":fam,"candidate":nm,**m})
    if (s+1)%100==0: print("[bear37]",s+1,"/",NSIM37,flush=True)
BEAR=pd.DataFrame(bear); BEAR.to_csv("tqqq_stage37_bear_mc.csv",index=False)

def summary(g):
    q=lambda x,p:float(np.quantile(np.asarray(x,float),p))
    return {
        "n":len(g),"cagr_p05":q(g.cagr,.05),"cagr_median":q(g.cagr,.50),"cagr_p95":q(g.cagr,.95),
        "mdd_p05":q(g.mdd,.05),"mdd_median":q(g.mdd,.50),
        "prob_mdd35plus":float(np.mean(g.mdd<-.35)),
        "prob_mdd40plus":float(np.mean(g.mdd<-.40)),
        "prob_mdd50plus":float(np.mean(g.mdd<-.50)),
        "prob_cagr30plus":float(np.mean(g.cagr>=.30))
    }
SUM=[]
for typ,df in [("normal",NORMAL),("bear",BEAR)]:
    for nm,g in df.groupby("candidate"): SUM.append({"test":typ,"candidate":nm,"family":"ALL",**summary(g)})
    if typ=="bear":
        for (nm,fam),g in df.groupby(["candidate","family"]): SUM.append({"test":typ,"candidate":nm,"family":fam,**summary(g)})
SUM=pd.DataFrame(SUM); SUM.to_csv("tqqq_stage37_mc_summary.csv",index=False)

TS=[]
for nm,g in NTAX.groupby("candidate"):
    TS.append({
        "candidate":nm,"n":len(g),
        "tax_cagr_p05":float(np.quantile(g.tax_cagr,.05)),
        "tax_cagr_median":float(np.quantile(g.tax_cagr,.50)),
        "tax_cagr_p95":float(np.quantile(g.tax_cagr,.95)),
        "prob_tax30plus":float(np.mean(g.tax_cagr>=.30)),
        "pre_mdd_p05":float(np.quantile(g.pre_mdd,.05)),
        "pre_mdd_median":float(np.quantile(g.pre_mdd,.50)),
    })
TS=pd.DataFrame(TS); TS.to_csv("tqqq_stage37_tax_mc_summary.csv",index=False)

# Drawdown attribution on actual history using the exact model returns.
def dd_episode(sr):
    r=np.asarray(sr,float); eq=np.cumprod(1+np.nan_to_num(r,nan=0.0)); pk=np.maximum.accumulate(eq); dd=eq/pk-1
    tr=int(np.argmin(dd)); pki=int(np.argmax(eq[:tr+1]))
    rec=""
    for j in range(tr+1,len(eq)):
        if eq[j]>=eq[pki]: rec=str(pd.Timestamp(DTS.iloc[j]).date()); break
    return {"peak":str(pd.Timestamp(DTS.iloc[pki]).date()),"trough":str(pd.Timestamp(DTS.iloc[tr]).date()),"recovery":rec,"mdd":float(dd[tr])}
DD=[]
for nm in sel:
    m,sr,_=from_target(A,th[nm],COST)
    DD.append({"candidate":nm,**dd_episode(sr)})
DD=pd.DataFrame(DD); DD.to_csv("tqqq_stage37_drawdowns.csv",index=False)

# Goal-first final table.
mall=SUM[SUM.family.eq("ALL")].pivot(index="candidate",columns="test")
rank=[]
for nm in sel:
    h=HIST[HIST.candidate.eq(nm)].iloc[0]
    tx=TS[TS.candidate.eq(nm)].iloc[0]
    nmed=float(mall.loc[nm,("cagr_median","normal")]); nmdd=float(mall.loc[nm,("mdd_median","normal")])
    bmdd=float(mall.loc[nm,("mdd_median","bear")])
    goal_hist=bool(h.tax_cagr>=.307)
    score=(h.tax_cagr + .60*tx.tax_cagr_median + .15*tx.tax_cagr_p05
           -1.2*max(0.,-h.pre_mdd-.50)-.3*max(0.,-nmdd-.50))
    rank.append({
        "candidate":nm,"hist_tax_cagr":h.tax_cagr,"hist_pre_cagr":h.pre_cagr,"hist_mdd":h.pre_mdd,
        "normal_cagr_median":nmed,"normal_mdd_median":nmdd,
        "tax_mc_median":tx.tax_cagr_median,"tax_mc_p05":tx.tax_cagr_p05,"prob_tax30plus":tx.prob_tax30plus,
        "bear_mdd_median":bmdd,"clears_30_7_hist":goal_hist,"score":score
    })
R=pd.DataFrame(rank).sort_values("score",ascending=False); R.to_csv("tqqq_stage37_final_rank.csv",index=False)

print("\n=== HISTORICAL FRONTIER ===")
print(HIST.sort_values("tax_cagr",ascending=False)[["candidate","pre_cagr","pre_mdd","tax_cagr","tax_end","avg_exp","turnover"]].to_string(index=False))
print("\n=== SELECTED ===")
print(HIST[HIST.candidate.isin(sel)][["candidate","pre_cagr","pre_mdd","tax_cagr","tax_end","avg_exp","turnover"]].sort_values("tax_cagr",ascending=False).to_string(index=False))
print("\n=== TAX MC ===")
print(TS.sort_values("tax_cagr_median",ascending=False).to_string(index=False))
print("\n=== FINAL RANK ===")
print(R.to_string(index=False))
print("\n=== DD EPISODES ===")
print(DD.to_string(index=False))

Path("tqqq_stage37_summary.json").write_text(json.dumps({
    "historical":HIST.to_dict("records"),"selected":sel,"subperiods":WF.to_dict("records"),"costs":COST37.to_dict("records"),
    "mc_summary":SUM.to_dict("records"),"tax_mc_summary":TS.to_dict("records"),"final_rank":R.to_dict("records"),
    "drawdowns":DD.to_dict("records"),
    "rule_family":"Normal exposure = base. When all current risk locks are off and CURRENT would otherwise be 30%, if QQQ>SMA200 and QQQ>VWAP252 and MC57>=35, raise exposure to bull floor. Existing StrongBull/RG/GB/VIX Panic/risk locks stay unchanged.",
    "tax_model":"same Stage36 20.315% annual realized-gain model with average cost and 3-year loss carry; terminal liquidation taxed",
    "caveats":["USDJPY FX not modeled.","Dividend tax not separately modeled.","MC57 PIT/survivorship audit unresolved.","NQSAR history is reconstruction proxy.","Bear stress is not a forecast distribution."]
},ensure_ascii=False,indent=2,default=str))
