from pathlib import Path
p=Path('research/tqqq_stage8_attribution.py')
s=p.read_text()
s=s.replace("ret=bt.strategy_returns(target,tqqq.Open).fillna(0); bh=tqqq.Open.pct_change().fillna(0)","ret=bt.strategy_returns(target,tqqq.Open).reindex(idx).fillna(0); bh=tqqq.Open.pct_change().reindex(idx).fillna(0)")
exec(compile(s,str(p),'exec'),{})
