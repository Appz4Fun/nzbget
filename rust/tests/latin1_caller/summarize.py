from pathlib import Path
import os,statistics,random,json,sys
import argparse
parser=argparse.ArgumentParser()
parser.add_argument("directory",type=Path)
parser.add_argument("--trials",type=int,default=9)
args=parser.parse_args()
b=args.directory;M=statistics.median;data={}
prefix="latin-whole"
for i in range(args.trials):
 for stage in (["before","after"] if prefix=="latin-whole" else ["before","after","standin"]):
  rows={}
  for line in (b/f"logs/{prefix}-{i}-{stage}.log").read_text().splitlines():
   if line.startswith("RAW|"):
    _,name,round_,c,r=line.split("|");rows.setdefault(name,[]).append([float(c),float(r)])
  for name,a in rows.items():data.setdefault(name,{}).setdefault(stage,[]).append({"cpp":M(x[0] for x in a),"rust":M(x[1] for x in a),"paired":M(x[1]/x[0]-1 for x in a),"raw":a})
rng=random.Random(0x5c9e5af5)
def ci(a):
 samples=sorted(M(rng.choices(a,k=len(a))) for _ in range(20000))
 return [100*samples[499],100*samples[19499]]
summary={}
for name,d in data.items():
 after=d.get("after",d.get("standin"));cpp=[x["paired"] for x in after]
 s={"cpp_after_ns":M(x["cpp"] for x in after),"rust_after_ns":M(x["rust"] for x in after),"vs_cpp_pct":M(cpp)*100,"vs_cpp_95":ci(cpp)}
 if "before" in d:
  s.update({"cpp_before_ns":M(x["cpp"] for x in d["before"]),"rust_default_ns":M(x["rust"] for x in d["before"])})
  a=[n["rust"]/o["rust"]-1 for o,n in zip(d["before"],after)]
  norm=[(n["rust"]/n["cpp"])/(o["rust"]/o["cpp"])-1 for o,n in zip(d["before"],after)]
  s.update({"vs_default_pct":M(a)*100,"vs_default_95":ci(a),"vs_default_cpp_normalized_pct":M(norm)*100,"vs_default_cpp_normalized_95":ci(norm)})
 summary[name]=s
 print(name, json.dumps(s))
(b/(prefix+"-summary.json")).write_text(json.dumps({"method":"median of process medians; paired-ratio point estimates; process-block percentile bootstrap 20,000 draws seeded 5c9e5af5; descriptive CI excludes systematic layout bias","processes":args.trials,"rounds":21,"summary":summary,"raw":data},indent=2)+"\n")
