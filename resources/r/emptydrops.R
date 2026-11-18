args <- commandArgs(trailingOnly=TRUE)
suppressPackageStartupMessages(library(DropletUtils))
m <- as(Matrix::readMM(args[[1]]), "CsparseMatrix")
set.seed(as.integer(args[[4]]))
stats <- emptyDrops(m, lower=as.numeric(args[[2]]), niters=as.integer(args[[5]]),
                    BPPARAM=BiocParallel::SerialParam())
out <- data.frame(total=stats$Total, pvalue=stats$PValue, fdr=stats$FDR,
                  limited=stats$Limited, kept=!is.na(stats$FDR) & stats$FDR <= as.numeric(args[[3]]))
write.table(out, args[[6]], sep="\t", quote=FALSE, row.names=FALSE)
writeLines(capture.output(sessionInfo()),args[[7]])
