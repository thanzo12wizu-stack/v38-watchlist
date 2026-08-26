from pathlib import Path
p=Path('research/tqqq_stage15_joint_state_mc.py')
s=p.read_text()
s=s.replace("for block in [60,120]:", "for block in [120]:")
s=s.replace("for horizon_name,horizon in [('10y',2520),('full',len(F))]:", "for horizon_name,horizon in [('10y',2520)]:")
s=s.replace("tqqq_stage15_joint_state_mc.csv", "tqqq_stage15b_joint_state_mc.csv")
s=s.replace("tqqq_stage15_summary.csv", "tqqq_stage15b_summary.csv")
s=s.replace("tqqq_stage15_summary.json", "tqqq_stage15b_summary.json")
exec(compile(s,str(p),'exec'),{})
