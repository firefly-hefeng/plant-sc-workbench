"""Known mixed droplet fixture for integration of real R adapters, not accuracy calibration."""
from pathlib import Path
import sys,json,tempfile
import numpy as np
from scipy import sparse
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend import upstream
from backend.ambient import provisional_groups

def main():
    out=ROOT/"validation"/"raw-adapters"
    out.mkdir(exist_ok=True,parents=True)
    rng=np.random.default_rng(42);n=600;g=500;ambient_n=1300
    groups=np.arange(n)%6
    ambient=np.full(g,0.3);ambient[:24]=8;ambient/=ambient.sum()
    profiles=[]
    for group in groups:
        weight=np.ones(g)*0.12;weight[group*50:group*50+45]=12
        p=.94*weight/weight.sum()+.06*ambient
        profiles.append(rng.multinomial(int(rng.integers(500,1000)),p))
    ambient_profiles=[rng.multinomial(int(rng.integers(6,70)),ambient) for _ in range(ambient_n)]
    mat=sparse.csc_matrix(np.asarray(profiles+ambient_profiles).T)
    tags=[f"bc{x}" for x in range(n+ambient_n)];genes=[(f"G{i}",f"G{i}","Gene Expression") for i in range(g)]
    with tempfile.TemporaryDirectory(dir=out) as t:
        t=Path(t);upstream._write_mex(t/"raw",mat,genes,tags);upstream._write_mex(t/"filtered",mat[:,:n],genes,tags[:n])
        called=upstream.call_droplets(t/"raw",t/"called",fdr=.01,lower=80,niters=1000)
        coarse=provisional_groups(t/"filtered",t/"temp-clusters",42)
        corr=upstream.correct_ambient(t/"raw",t/"filtered",coarse,t/"ambient")
        assert 0<called["kept"]<=n+ambient_n and 0<corr["corrected_total"]<=corr["raw_total"]
        for name,p in (("droplet_calls.tsv",Path(called["barcodes_tsv"])),("droplet-versions.txt",t/"called/r_versions.txt"),("soup-versions.txt",t/"ambient/r_versions.txt"),("soup.log",t/"ambient/soupx.log")):(out/name).write_bytes(p.read_bytes())
        record=dict(fixture="synthetic",seed=42,input_droplets=n+ambient_n,simulated_cells=n,called=called["kept"],genes=g,
                    rho_mode=corr["rho_mode"],estimated_fraction=corr["rho"],raw_total=corr["raw_total"],corrected_total=corr["corrected_total"])
        (out/"result.json").write_text(json.dumps(record,indent=2))
        print(record)
if __name__=="__main__":main()

