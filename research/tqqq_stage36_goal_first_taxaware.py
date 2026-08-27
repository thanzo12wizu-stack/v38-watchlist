from __future__ import annotations
from pathlib import Path
import json, math, numpy as np, pandas as pd

# Reuse the exact Stage34 hierarchy/data construction, but do not run its validation body.
src = Path("research/tqqq_stage34_final_gb_runner_validation.py").read_text()
prefix = src.split("# ---------- historical exact validation ----------")[0]
exec(compile(prefix, "stage34-prefix", "exec"), globals())

print("\n=== STAGE36 GOAL-FIRST / TAX-AWARE BULL CAPTURE SEARCH ===", flush=True)

TAX = 0.20315
COST = 0.0005
NSIM = 400
TAXSIM = 120
HORIZON = 2520
BLOCK = 120
SEED_NORMAL = 360827
SEED_BEAR = 360828

DTS = pd.to_datetime(F.date).reset_index(drop=True)
YY = DTS.dt.year.to_numpy()
N = len(A["ret"])

def from_target(B, t, cost=COST):
    n = len(t)
    eff = np.zeros(n)
    eff[2:] = t[:-2]
    turn = np.zeros(n)
    turn[2:] = np.abs(np.diff(t))[:-1]
    sr = eff * B["ret"] - turn * cost
    m = metrics(sr[2:])
    m["avg_exp"] = float(np.mean(t))
    m["turnover"] = float(np.abs(np.diff(t)).sum())
    return m, sr, eff

def cond_mask(B, name):
    a200, a252, a50, a63 = B["a200"], B["a252"], B["a50"], B["a63"]
    nq, mc, lte21 = B["nq"], B["mc"], B["lte21"]
    if name == "A200":
        return a200.copy()
    if name == "A2":
        return a200 & a252
    if name == "A200_50":
        return a200 & a50
    if name == "A200_50_63":
        return a200 & a50 & a63
    if name == "A4":
        return a200 & a252 & a50 & a63
    if name == "A4_E21":
        return a200 & a252 & a50 & a63 & (~lte21)
    if name == "A2_NR":
        return a200 & a252 & (nq != 0)
    if name == "A4_NR":
        return a200 & a252 & a50 & a63 & (nq != 0)
    if name == "A2_MC35":
        return a200 & a252 & (mc >= 35)
    if name == "A4_MC35":
        return a200 & a252 & a50 & a63 & (mc >= 35)
    if name == "L_BOTH_LONG":
        enter = a200 & a252
        exit_ = (~a200) & (~a252)
    elif name == "L_STRONG_LONG":
        enter = a200 & a252 & a50 & a63
        exit_ = (~a200) & (~a252)
    elif name == "L_STRONG_MID":
        enter = a200 & a252 & a50 & a63
        exit_ = (~a50) & (~a63)
    elif name == "L_200_50":
        enter = a200 & a50
        exit_ = ~a200
    elif name == "L_200":
        enter = a200
        exit_ = ~a200
    else:
        raise ValueError(name)
    out = np.zeros(len(a200), dtype=bool)
    on = False
    for i in range(len(out)):
        if (not on) and enter[i]:
            on = True
        if on and exit_[i]:
            on = False
        out[i] = on
    return out

CONDS = [
    "A200","A2","A200_50","A200_50_63","A4","A4_E21",
    "A2_NR","A4_NR","A2_MC35","A4_MC35",
    "L_BOTH_LONG","L_STRONG_LONG","L_STRONG_MID","L_200_50","L_200",
]

def current_trace(B):
    return simulate(B, PCUR, COST, True)

def make_target(B, spec, cur=None):
    if spec["name"] == "CURRENT":
        return (cur if cur is not None else current_trace(B))["target"].copy()
    if spec["name"] == "BUYHOLD":
        return np.ones(len(B["ret"]), dtype=float)
    if cur is None:
        cur = current_trace(B)
    t = cur["target"].copy()
    risk = cur["risklock"]
    normal = (~risk) & np.isclose(t, .30, atol=1e-9)
    base_floor = spec["base"]
    bull_floor = spec["bull"]
    if base_floor > .30:
        t[normal] = np.maximum(t[normal], base_floor)
    cm = cond_mask(B, spec["cond"])
    hit = normal & cm
    t[hit] = np.maximum(t[hit], bull_floor)
    return np.clip(t, 0, 1)

def account_end(ret, target, cost=COST, tax_rate=0.0, dates=None, synthetic_year=252):
    """
    Realistic cash+shares account:
    close signal -> next-session open rebalance; only rebalance when the target signal changes.
    Average-cost tax basis; annual realized-gain taxation with 3-year loss carry.
    Terminal liquidation is included in end wealth. FX/dividend tax are outside this model.
    """
    r = np.asarray(ret, float)
    t = np.asarray(target, float)
    n = len(r)
    px = np.ones(n, float)
    for i in range(1, n):
        rr = r[i] if np.isfinite(r[i]) else 0.0
        px[i] = px[i-1] * max(1e-12, 1.0 + rr)

    cash = 1.0
    shares = 0.0
    basis = 0.0
    realized = 0.0
    losses = []  # [remaining future tax years, amount]
    prev_sig = None
    nav_hist = [1.0]
    taxes_paid = 0.0

    def year_id_for_open(j):
        if dates is None:
            return int((j-1) // synthetic_year)
        return int(pd.Timestamp(dates.iloc[j]).year)

    def apply_loss_and_tax(net):
        nonlocal losses
        losses = [[rem, amt] for rem, amt in losses if rem > 0 and amt > 1e-15]
        taxable = max(0.0, net)
        if taxable > 0:
            losses.sort(key=lambda x: x[0])
            for z in losses:
                if taxable <= 0:
                    break
                use = min(taxable, z[1])
                taxable -= use
                z[1] -= use
        losses = [[rem-1, amt] for rem, amt in losses if amt > 1e-15 and rem-1 > 0]
        if net < 0:
            losses.append([3, -net])
        return taxable * tax_rate

    def forced_sale_for_cash(need, p):
        nonlocal cash, shares, basis
        pos = shares * p
        if need <= 0 or pos <= 0:
            return 0.0
        gross = min(pos, need / max(1e-12, 1.0-cost))
        frac = gross / pos
        alloc_basis = basis * frac
        fee = gross * cost
        proceeds = gross - fee
        gain = proceeds - alloc_basis
        shares -= gross / p
        basis -= alloc_basis
        cash += proceeds
        return gain

    current_year = year_id_for_open(1) if n > 2 else 0
    for j in range(1, n-1):
        yid = year_id_for_open(j)
        if yid != current_year:
            tax = apply_loss_and_tax(realized)
            realized = 0.0
            if tax > 0:
                if cash < tax:
                    extra = forced_sale_for_cash(tax-cash, px[j])
                    realized += extra
                cash -= min(cash, tax)
                taxes_paid += tax
            current_year = yid

        sig = float(t[j-1])
        if prev_sig is None or abs(sig-prev_sig) > 1e-12:
            p = px[j]
            nav = cash + shares*p
            desired = sig * nav
            current = shares*p
            delta = desired-current
            if delta > 1e-14:
                buy = min(delta, max(0.0, cash)/(1.0+cost))
                fee = buy*cost
                shares += buy/p
                basis += buy + fee
                cash -= buy + fee
            elif delta < -1e-14:
                sell = min(-delta, current)
                if current > 0 and sell > 0:
                    frac = sell/current
                    alloc_basis = basis*frac
                    fee = sell*cost
                    proceeds = sell-fee
                    realized += proceeds-alloc_basis
                    shares -= sell/p
                    basis -= alloc_basis
                    cash += proceeds
            prev_sig = sig
        nav_hist.append(cash + shares*px[j])

    j = n-1
    if n > 2:
        yid = year_id_for_open(j)
        if yid != current_year:
            tax = apply_loss_and_tax(realized)
            realized = 0.0
            if tax > 0:
                if cash < tax:
                    extra = forced_sale_for_cash(tax-cash, px[j])
                    realized += extra
                cash -= min(cash, tax)
                taxes_paid += tax
            current_year = yid

        p = px[j]
        pos = shares*p
        if pos > 0:
            fee = pos*cost
            proceeds = pos-fee
            realized += proceeds-basis
            cash += proceeds
            shares = 0.0
            basis = 0.0
        tax = apply_loss_and_tax(realized)
        tax = min(tax, max(0.0, cash))
        cash -= tax
        taxes_paid += tax
        nav_hist.append(cash)

    arr = np.asarray(nav_hist, float)
    peak = np.maximum.accumulate(arr)
    mdd = float(np.min(arr/peak-1.0))
    years = max((n-2)/252.0, 1e-9)
    end = float(cash)
    cagr = float(end**(1/years)-1) if end > 0 else -1.0
    return {"end": end, "cagr": cagr, "mdd": mdd, "taxes_paid": float(taxes_paid)}

SPECS = [{"name":"CURRENT"},{"name":"BUYHOLD"}]
for base in (.30,.40,.50,.60):
    for bull in (.60,.70,.80,.90,1.00):
        if bull + 1e-12 < base:
            continue
        for cond in CONDS:
            nm = f"B{int(base*100)}_{cond}_F{int(bull*100)}"
            SPECS.append({"name":nm,"base":base,"bull":bull,"cond":cond})

curA = current_trace(A)
rows = []
targets_hist = {}
for k, spec in enumerate(SPECS):
    t = make_target(A, spec, curA)
    targets_hist[spec["name"]] = t
    model, sr, eff = from_target(A, t, COST)
    pre = account_end(A["ret"], t, COST, 0.0, DTS)
    aft = account_end(A["ret"], t, COST, TAX, DTS)
    rows.append({
        "candidate":spec["name"],
        "base":spec.get("base",np.nan),"bull":spec.get("bull",np.nan),"cond":spec.get("cond",""),
        "model_cagr":model["cagr"],"model_mdd":model["mdd"],"avg_exp":model["avg_exp"],"turnover":model["turnover"],
        "acct_pre_cagr":pre["cagr"],"acct_pre_mdd":pre["mdd"],"acct_pre_end":pre["end"],
        "tax_cagr":aft["cagr"],"tax_end":aft["end"],"taxes_paid":aft["taxes_paid"],
    })
    if (k+1)%50 == 0:
        print("[scan]", k+1, "/", len(SPECS), flush=True)
SCAN = pd.DataFrame(rows)
SCAN.to_csv("tqqq_stage36_scan.csv", index=False)

sel = ["CURRENT","BUYHOLD"]
for cap in (.25,.30,.35,.40,.45):
    g = SCAN[(SCAN.candidate!="BUYHOLD") & (SCAN.acct_pre_mdd >= -cap)]
    if len(g):
        sel.append(str(g.sort_values("tax_cagr",ascending=False).iloc[0].candidate))
G = SCAN[~SCAN.candidate.isin(["CURRENT","BUYHOLD"])].copy()
G["score"] = G.tax_cagr - 1.5*np.maximum(0.0, -G.acct_pre_mdd-.40)
sel += G.sort_values("score",ascending=False).head(8).candidate.tolist()
sel = list(dict.fromkeys(sel))
sel = sel[:12]
SELSPECS = {s["name"]:s for s in SPECS if s["name"] in sel}
print("\nSELECTED:", sel, flush=True)

PER = [("2011-2015",2011,2015),("2016-2018",2016,2018),("2019-2021",2019,2021),("2022-2024",2022,2024),("2025-2026",2025,2026)]
wf=[]
for nm in sel:
    t=targets_hist[nm]
    for lab,a,b in PER:
        mask=(YY>=a)&(YY<=b); ids=np.flatnonzero(mask)
        if len(ids)<20: continue
        rr=A["ret"][ids]; tt=t[ids]; dd=DTS.iloc[ids].reset_index(drop=True)
        pre=account_end(rr,tt,COST,0.0,dd); aft=account_end(rr,tt,COST,TAX,dd)
        wf.append({"candidate":nm,"period":lab,"pre_cagr":pre["cagr"],"pre_mdd":pre["mdd"],"tax_cagr":aft["cagr"],"tax_end":aft["end"]})
WF=pd.DataFrame(wf); WF.to_csv("tqqq_stage36_subperiods.csv",index=False)

costrows=[]
for nm in sel:
    t=targets_hist[nm]
    for bps in (5,10,20):
        c=bps/10000.0
        pre=account_end(A["ret"],t,c,0.0,DTS); aft=account_end(A["ret"],t,c,TAX,DTS)
        costrows.append({"candidate":nm,"cost_bps":bps,"pre_cagr":pre["cagr"],"pre_mdd":pre["mdd"],"tax_cagr":aft["cagr"],"tax_end":aft["end"]})
COSTS=pd.DataFrame(costrows); COSTS.to_csv("tqqq_stage36_costs.csv",index=False)

L=len(A["ret"]); nb=int(np.ceil(HORIZON/BLOCK)); offs=np.arange(BLOCK)
rng=np.random.default_rng(SEED_NORMAL)
starts=rng.integers(0,L-BLOCK+1,size=(NSIM,nb))
paths=(starts[:,:,None]+offs).reshape(NSIM,-1)[:,:HORIZON]
normal=[]; normal_tax=[]
for s in range(NSIM):
    ix=paths[s]; B={k:A[k][ix].copy() for k in KEYS}; cur=current_trace(B)
    for nm,spec in SELSPECS.items():
        t=make_target(B,spec,cur); m,_,_=from_target(B,t,COST)
        normal.append({"sim":s,"candidate":nm,**m})
        if s<TAXSIM:
            pre=account_end(B["ret"],t,COST,0.0,None); aft=account_end(B["ret"],t,COST,TAX,None)
            normal_tax.append({"sim":s,"candidate":nm,"pre_cagr":pre["cagr"],"pre_mdd":pre["mdd"],"tax_cagr":aft["cagr"],"tax_end":aft["end"]})
    if (s+1)%50==0: print("[normal]",s+1,"/",NSIM,flush=True)
NORMAL=pd.DataFrame(normal); NORMAL.to_csv("tqqq_stage36_normal_mc.csv",index=False)
NORMALT=pd.DataFrame(normal_tax); NORMALT.to_csv("tqqq_stage36_normal_tax_mc.csv",index=False)

rng=np.random.default_rng(SEED_BEAR)
starts=rng.integers(0,L-BLOCK+1,size=(NSIM,nb))
paths=(starts[:,:,None]+offs).reshape(NSIM,-1)[:,:HORIZON]
families=np.array((["dotcom_like"]*(NSIM//4))+(["gfc_like"]*(NSIM//4))+(["covid_like"]*(NSIM//4))+(["2022_like"]*(NSIM-3*(NSIM//4))),dtype=object)
rng.shuffle(families)
bear=[]
for s in range(NSIM):
    ix=paths[s]; B={k:A[k][ix].copy() for k in KEYS}; fam=str(families[s]); ep=make_episode(fam,rng); le=len(ep["ret"])
    if le>=HORIZON-504:
        cut=(le-(HORIZON-504))//2
        ep={k:v[cut:cut+(HORIZON-504)] for k,v in ep.items()}; le=len(ep["ret"])
    pos=int(rng.integers(252,max(253,HORIZON-le-252)))
    for k in KEYS: B[k][pos:pos+le]=ep[k]
    cur=current_trace(B)
    for nm,spec in SELSPECS.items():
        t=make_target(B,spec,cur); m,_,_=from_target(B,t,COST)
        bear.append({"sim":s,"family":fam,"candidate":nm,**m})
    if (s+1)%50==0: print("[bear]",s+1,"/",NSIM,flush=True)
BEAR=pd.DataFrame(bear); BEAR.to_csv("tqqq_stage36_bear_mc.csv",index=False)

def summ(g):
    q=lambda x,p: float(np.quantile(np.asarray(x,float),p))
    cg=g.cagr; md=g.mdd
    return {
        "n":len(g),"cagr_p05":q(cg,.05),"cagr_median":q(cg,.5),"cagr_p95":q(cg,.95),
        "mdd_p05":q(md,.05),"mdd_median":q(md,.5),
        "prob_mdd30plus":float(np.mean(md<-.30)),
        "prob_mdd35plus":float(np.mean(md<-.35)),
        "prob_mdd40plus":float(np.mean(md<-.40)),
        "prob_cagr30below":float(np.mean(cg<.30)),
    }
SUM=[]
for typ,df in [("normal",NORMAL),("bear",BEAR)]:
    for nm,g in df.groupby("candidate"):
        SUM.append({"test":typ,"candidate":nm,"family":"ALL",**summ(g)})
    if typ=="bear":
        for (nm,fam),g in df.groupby(["candidate","family"]):
            SUM.append({"test":typ,"candidate":nm,"family":fam,**summ(g)})
SUM=pd.DataFrame(SUM); SUM.to_csv("tqqq_stage36_mc_summary.csv",index=False)

TAXSUM=[]
if len(NORMALT):
    for nm,g in NORMALT.groupby("candidate"):
        TAXSUM.append({
            "candidate":nm,"n":len(g),
            "tax_cagr_p05":float(np.quantile(g.tax_cagr,.05)),
            "tax_cagr_median":float(np.quantile(g.tax_cagr,.50)),
            "tax_cagr_p95":float(np.quantile(g.tax_cagr,.95)),
            "prob_tax_cagr30plus":float(np.mean(g.tax_cagr>=.30)),
            "pre_mdd_median":float(np.quantile(g.pre_mdd,.50)),
            "pre_mdd_p05":float(np.quantile(g.pre_mdd,.05)),
        })
TAXSUM=pd.DataFrame(TAXSUM); TAXSUM.to_csv("tqqq_stage36_tax_mc_summary.csv",index=False)

HSEL=SCAN[SCAN.candidate.isin(sel)].copy()
MALL=SUM[SUM.family.eq("ALL")].pivot(index="candidate",columns="test")
rows=[]
for _,h in HSEL.iterrows():
    nm=h.candidate
    normal_med=float(MALL.loc[nm,("cagr_median","normal")]) if nm in MALL.index else np.nan
    normal_mdd=float(MALL.loc[nm,("mdd_median","normal")]) if nm in MALL.index else np.nan
    bear_mdd=float(MALL.loc[nm,("mdd_median","bear")]) if nm in MALL.index else np.nan
    tx=TAXSUM[TAXSUM.candidate.eq(nm)]
    txmed=float(tx.tax_cagr_median.iloc[0]) if len(tx) else np.nan
    txp05=float(tx.tax_cagr_p05.iloc[0]) if len(tx) else np.nan
    score=(h.tax_cagr + 0.50*txmed + 0.20*txp05
           -0.80*max(0.0,-h.acct_pre_mdd-.35)
           -0.30*max(0.0,-normal_mdd-.35)
           -0.10*max(0.0,-bear_mdd-.50))
    rows.append({
        "candidate":nm,"hist_tax_cagr":h.tax_cagr,"hist_pre_cagr":h.acct_pre_cagr,"hist_mdd":h.acct_pre_mdd,
        "normal_cagr_median":normal_med,"normal_mdd_median":normal_mdd,
        "tax_mc_median":txmed,"tax_mc_p05":txp05,"bear_mdd_median":bear_mdd,"score":score
    })
RANK=pd.DataFrame(rows).sort_values("score",ascending=False)
RANK.to_csv("tqqq_stage36_final_rank.csv",index=False)

print("\n=== TOP HISTORICAL TAX/MDD ===")
print(SCAN.sort_values("tax_cagr",ascending=False).head(20)[["candidate","acct_pre_cagr","acct_pre_mdd","tax_cagr","tax_end","avg_exp","turnover"]].to_string(index=False))
print("\n=== SELECTED HISTORICAL ===")
print(HSEL[["candidate","acct_pre_cagr","acct_pre_mdd","tax_cagr","tax_end","avg_exp","turnover"]].sort_values("tax_cagr",ascending=False).to_string(index=False))
print("\n=== NORMAL/BEAR SUMMARY ===")
print(SUM[SUM.family.eq("ALL")].to_string(index=False))
print("\n=== TAX MC SUMMARY ===")
print(TAXSUM.to_string(index=False))
print("\n=== FINAL RANK ===")
print(RANK.to_string(index=False))

out={
    "goal":"maximize after-tax compounding; target after-tax CAGR >=30% while avoiding TQQQ buy-and-hold style catastrophic drawdown",
    "tax_rate":TAX,"cost_oneway":COST,"historical_scan":SCAN.to_dict("records"),
    "selected":sel,"subperiods":WF.to_dict("records"),"costs":COSTS.to_dict("records"),
    "mc_summary":SUM.to_dict("records"),"tax_mc_summary":TAXSUM.to_dict("records"),
    "final_rank":RANK.to_dict("records"),
    "execution":"close signal -> next-session open; account simulation rebalances only when target signal changes; terminal liquidation included for after-tax wealth",
    "tax_model":"20.315% capital-gain tax on annual net realized gains, average-cost basis, 3-year loss carry; taxes paid from portfolio; terminal liquidation taxed",
    "caveats":[
        "USDJPY FX is not modeled; all capital gains are measured in the TQQQ price currency.",
        "Dividend/distribution taxation is not separately modeled.",
        "MC57 PIT/survivorship audit remains unresolved.",
        "NQSAR historical state is a reconstruction proxy, not authoritative full history.",
        "Adversarial Bear stress is a robustness test, not a real-world probability distribution."
    ]
}
Path("tqqq_stage36_summary.json").write_text(json.dumps(out,ensure_ascii=False,indent=2,default=str))
