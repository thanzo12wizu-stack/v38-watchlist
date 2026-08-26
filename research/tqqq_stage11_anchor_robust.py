from pathlib import Path
p=Path('research/tqqq_stage11_integrated_nqsar.py')
s=p.read_text()
old="for baseexp,bmc,bmax,fdd,frec,bexit,vp in itertools.product([.52,.54,.545,.55,.56,.58,.60],[60,65,70],[2.0,2.5,3.0],[-.065,-.075,-.085],[3,4,5],['raw','score1','score3'],[False,True]):"
variants=[
(.545,65,2.5,-.075,4,'score1',True),
(.52,65,2.5,-.075,4,'score1',True),(.56,65,2.5,-.075,4,'score1',True),(.60,65,2.5,-.075,4,'score1',True),
(.545,60,2.5,-.075,4,'score1',True),(.545,70,2.5,-.075,4,'score1',True),
(.545,65,2.5,-.065,4,'score1',True),(.545,65,2.5,-.085,4,'score1',True),
(.545,65,2.5,-.075,3,'score1',True),(.545,65,2.5,-.075,5,'score1',True),
(.545,65,2.5,-.075,4,'raw',True),(.545,65,2.5,-.075,4,'score3',True),
(.545,65,2.5,-.075,4,'score1',False),
(.545,65,2.0,-.075,4,'score1',True),(.545,65,3.0,-.075,4,'score1',True),
]
s=s.replace(old,"for baseexp,bmc,bmax,fdd,frec,bexit,vp in "+repr(variants)+":")
s=s.replace("for rg,gb,by,ry,part,scope in itertools.product([.50,.60,.70],[.80,1.0],[.65,.75,.85],[.20,.25],['none','half','two_thirds'],['all','riskoff']):", "for rg,gb,by,ry,part,scope in itertools.product([.50,.60,.70],[1.0],[.75],[.25],['none','half'],['all','riskoff']):")
s=s.replace("if combo=='NONE' and (rg,gb,by,ry,part,scope)!=(.50,.80,.65,.20,'none','all'): continue", "if combo=='NONE' and (rg,gb,by,ry,part,scope)!=(.50,1.0,.75,.25,'none','all'): continue")
exec(compile(s,str(p),'exec'),{})
