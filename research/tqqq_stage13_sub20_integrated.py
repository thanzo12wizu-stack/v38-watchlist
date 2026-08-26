from pathlib import Path
p=Path('research/tqqq_stage11_integrated_nqsar.py')
s=p.read_text()
s=s.replace("for baseexp,bmc,bmax,fdd,frec,bexit,vp in itertools.product([.52,.54,.545,.55,.56,.58,.60],[60,65,70],[2.0,2.5,3.0],[-.065,-.075,-.085],[3,4,5],['raw','score1','score3'],[False,True]):", "for baseexp,bmc,bmax,fdd,frec,bexit,vp in itertools.product([.20,.25,.30,.35],[55,60,65,70],[2.5],[-.055,-.065,-.075],[2,3,4],['score1'],[False,True]):")
s=s.replace("combos=['NONE','RG','RG+GB','RG+GB+BY','RG+GB+BY+RY']", "combos=['NONE','RG','RG+GB']")
s=s.replace("for rg,gb,by,ry,part,scope in itertools.product([.50,.60,.70],[.80,1.0],[.65,.75,.85],[.20,.25],['none','half','two_thirds'],['all','riskoff']):", "for rg,gb,by,ry,part,scope in itertools.product([.60,.70,.80],[.90,1.0],[.75],[.25],['none','half'],['riskoff']):")
s=s.replace("if combo=='NONE' and (rg,gb,by,ry,part,scope)!=(.50,.80,.65,.20,'none','all'): continue", "if combo=='NONE' and (rg,gb,by,ry,part,scope)!=(.60,.90,.75,.25,'none','riskoff'): continue")
exec(compile(s,str(p),'exec'),{})
