"""Run within Linux, including WSL. Use an ext4 temporary directory for STAR pipes."""
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile

def main(file):
    job=json.loads(Path(file).read_text(encoding="utf-8")); out=Path(job["output"])
    out.mkdir(parents=True,exist_ok=True)
    star=job["binary"]
    version=subprocess.check_output([star,"--version"],text=True).strip()
    if version!="2.7.11b":raise ValueError("本适配器的验证版本是 STAR 2.7.11b，检测到 "+version)
    with tempfile.TemporaryDirectory(prefix="plantsc-star-") as temp:
        work=Path(temp);cmd=[star,"--runThreadN",str(job["threads"])]
        if job["mode"]=="index":
            with open(job["fasta"],"rb") as f:
                bases=sum(len(line.strip()) for line in f if not line.startswith(b">"))
            args=["--runMode","genomeGenerate","--genomeDir",str(out),"--genomeFastaFiles",job["fasta"],
                  "--sjdbGTFfile",job["gtf"],"--sjdbOverhang","99","--genomeSAindexNbases",str(max(1,min(14,math.floor(math.log2(bases)/2)-1))),
                  "--limitGenomeGenerateRAM",str(job["memory_gb"]*1000000000)]
        else:
            reads=[[],[]]
            for i,pair in enumerate(job["pairs"]):
                for read_no,path in enumerate(pair):
                    dest=work/f"lane{i:03d}_R{read_no+1}.fastq.gz";dest.symlink_to(path);reads[read_no].append(str(dest))
            args=["--genomeDir",job["index"],"--readFilesIn",",".join(reads[1]),",".join(reads[0]),"--readFilesCommand","zcat",
                  "--soloType","CB_UMI_Simple","--soloCBwhitelist",job["whitelist"],"--soloCBlen","16","--soloUMIlen",str(job["umi_length"]),
                  "--soloBarcodeReadLength","0","--soloFeatures",job["feature"],"--soloCellFilter","EmptyDrops_CR",
                  "--soloCBmatchWLtype","1MM_multi_Nbase_pseudocounts","--soloUMIdedup","1MM_CR","--soloUMIfiltering","MultiGeneUMI_CR",
                  "--outSAMtype","None"]
        cmd+=args+["--outTmpDir",str(work/"star-tmp"),"--outFileNamePrefix",str(out)+"/"]
        with (out/"command.json").open("w") as dst:json.dump({"argv":cmd,"version":version,"read_pairs":job.get("pairs",[])},dst,indent=2)
        subprocess.run(cmd,check=True)
if __name__=="__main__":main(sys.argv[1])

