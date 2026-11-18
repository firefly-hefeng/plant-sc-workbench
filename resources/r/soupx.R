args <- commandArgs(trailingOnly=TRUE)
suppressPackageStartupMessages(library(SoupX))
raw <- as(Matrix::readMM(file.path(args[[1]],"raw.mtx")), "CsparseMatrix")
cells <- as(Matrix::readMM(file.path(args[[1]],"filtered.mtx")), "CsparseMatrix")
rownames(cells) <- rownames(raw) <- paste0("g",seq_len(nrow(raw)))
colnames(raw) <- paste0("d",seq_len(ncol(raw)))
index <- scan(file.path(args[[1]],"indexes.txt"),quiet=TRUE,what=integer())
colnames(cells) <- colnames(raw)[index]
clusters <- readLines(file.path(args[[1]],"clusters.txt"),encoding="UTF-8",warn=FALSE)
names(clusters) <- colnames(cells)
set.seed(42L)
s <- SoupChannel(raw,cells)
s <- setClusters(s,clusters)
if (args[[2]]=="auto") {
    s <- autoEstCont(s,doPlot=FALSE)
} else {
    s <- setContaminationFraction(s,as.numeric(args[[2]]))
}
out <- adjustCounts(s,roundToInt=FALSE)
stopifnot(identical(rownames(out),rownames(cells)),identical(colnames(out),colnames(cells)))
Matrix::writeMM(out,file.path(args[[1]],"corrected.mtx"))
writeLines(as.character(median(s$metaData$rho)),args[[3]])
writeLines(capture.output(sessionInfo()),args[[4]])
