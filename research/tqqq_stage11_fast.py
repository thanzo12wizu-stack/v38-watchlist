from pathlib import Path
p=Path('research/tqqq_stage11_integrated_nqsar.py')
s=p.read_text()
s=s.replace("for rg,gb,by,ry,part,scope in itertools.product([.50,.60,.70],[.80,1.0],[.65,.75,.85],[.20,.25],['none','half','two_thirds'],['all','riskoff']):", "for rg,gb,by,ry,part,scope in itertools.product([.50,.60,.70],[1.0],[.75],[.25],['none','half'],['all','riskoff']):")
s=s.replace("if combo=='NONE' and (rg,gb,by,ry,part,scope)!=(.50,.80,.65,.20,'none','all'): continue", "if combo=='NONE' and (rg,gb,by,ry,part,scope)!=(.50,1.0,.75,.25,'none','all'): continue")
exec(compile(s,str(p),'exec'),{})
