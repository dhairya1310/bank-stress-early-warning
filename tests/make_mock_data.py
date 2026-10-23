import io, zipfile, numpy as np, pandas as pd, sys
from pathlib import Path
out = Path(sys.argv[1]); (out/"call_reports").mkdir(parents=True, exist_ok=True)
rng = np.random.default_rng(1)
N=150; qs = pd.date_range("2019-12-31","2024-03-31",freq="QE")
ids = np.arange(1000,1000+N); certs = np.arange(50000,50000+N)
risky = {0:"Mock Valley Bank",1:"Mock Signet Bank",2:"Mock First Republic",3:"Mock Republic First"}
sched = {"RC":["RCON2170","RCON2200","RCON0081","RCON0071"],
 "RCB":["RCON1754","RCON1771","RCON1772","RCON1773","RCON0416"]+[f"RCONA{n}" for n in range(549,563)],
 "RCO":["RCON5597"],"RCRI":["RCOA8274","RCOAP838"],"RCRII":["RCOA3792","RCOAA223"],
 "RCCI":["RCONF158","RCONF159","RCON1460","RCONF160","RCONF161"]}
def write(name, df):
    b=io.StringIO(); hdr="\t".join(df.columns); desc="\t".join(["desc"]*len(df.columns))
    b.write(hdr+"\n"+desc+"\n"); df.to_csv(b,sep="\t",header=False,index=False); return b.getvalue().encode()
for k,q in enumerate(qs):
    ta = rng.uniform(5e5, 5e7, N); ta[:4]=[2e8,1.1e8,2.1e8,6e6]
    ta *= (1+0.02*k)
    t = k/len(qs)
    sec = ta*rng.uniform(.1,.3,N); sec[:4]*=1.6
    loss = sec*(0.02 if q.year<2022 else 0.12)*rng.uniform(.5,1.5,N)
    dep = ta*.85; dep[:4] *= (1 - 0.08*(q>=pd.Timestamp("2022-09-30")))
    unins = dep*rng.uniform(.2,.5,N); unins[:4]=dep[:4]*.88
    t1 = ta*rng.uniform(.08,.12,N); t1[:4]=ta[:4]*.075
    d = {"IDRSSD":ids,"RCON2170":ta,"RCON2200":dep,"RCON0081":ta*.01,"RCON0071":ta*.04,
      "RCON1754":sec*.5,"RCON1771":sec*.5-loss*.5,"RCON1772":sec*.5,"RCON1773":sec*.5-loss*.5,"RCON0416":sec*.2,
      "RCON5597":unins,"RCOA8274":t1,"RCOAP838":1,"RCOA3792":t1*1.15,"RCOAA223":ta*.7,
      "RCONF158":ta*.02,"RCONF159":ta*.05,"RCON1460":ta*.05,"RCONF160":ta*.05,"RCONF161":ta*rng.uniform(.05,.3,N)}
    w=rng.dirichlet(np.ones(14),N)
    for j,n in enumerate(range(549,563)): d[f"RCONA{n}"]=sec*w[:,j]
    df=pd.DataFrame(d).round(0); df["RCOAA223"]=df["RCOAA223"].astype("Int64"); df.loc[5:8,"RCOAA223"]=pd.NA
    tag=q.strftime("%m%d%Y")
    with zipfile.ZipFile(out/"call_reports"/f"FFIEC CDR Call Bulk All Schedules {tag}.zip","w") as z:
        for s,cols in sched.items():
            z.writestr(f"FFIEC CDR Call Schedule {s} {tag}.txt", write(s, df[["IDRSSD"]+cols]))
        por=pd.DataFrame({"IDRSSD":ids,"FDIC Certificate Number":certs,
          "Financial Institution Name":[risky.get(i,f"Mock Bank {i}") for i in range(N)],"Financial Institution State":"NY"})
        z.writestr(f"FFIEC CDR Call Bulk POR {tag}.txt", write("POR",por))
fb=pd.DataFrame({"Bank Name\xa0":list(risky.values())+["Tiny Bank"],"City\xa0":"X","State\xa0":"CA",
  "Cert\xa0":list(certs[:4])+[99999],"Acquiring Institution\xa0":"Y",
  "Closing Date\xa0":["10-Mar-23","12-Mar-23","1-May-23","26-Apr-24","3-Nov-23"],"Fund\xa0":1})
fb.to_csv(out/"banklist.csv",index=False,encoding="cp1252")
