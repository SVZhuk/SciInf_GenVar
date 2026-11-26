#!/usr/bin/env bash
# Build files for trying the upload endpoints by hand: small synthetic samples, slices of real
# public ClinVar and 1000 Genomes releases, and files the API must reject with 422.
#
# Usage: scripts/generate_test_datasets.sh [output_dir]   (default: datasets/, git-ignored)
#        FORCE=1 scripts/generate_test_datasets.sh        (download again even if a file exists)
# Needs: curl, gzip, awk; bcftools for the 1000 Genomes slice (sudo apt install bcftools).
# All data is public and consented, safe to use in class. Never commit the output.

set -euo pipefail

CLINVAR_SUMMARY_URL=https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/variant_summary.txt.gz
CLINVAR_VCF_URL=https://ftp.ncbi.nlm.nih.gov/pub/clinvar/vcf_GRCh38/clinvar.vcf.gz
KG_CHR22_URL=https://ftp.1000genomes.ebi.ac.uk/vol1/ftp/release/20130502/ALL.chr22.phase3_shapeit2_mvncall_integrated_v5b.20130502.genotypes.vcf.gz
KG_REGION=22:16050000-16300000
CLINVAR_ROWS=20000
CLINVAR_VCF_LINES=5000

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
out=$(realpath -m "${1:-$repo_root/datasets}")
mkdir -p "$out"
cd "$out"

log() { printf '%s\n' "$*" >&2; }

# True when the file must be (re)built.
needed() {
    if [[ -s $1 && ${FORCE:-0} != 1 ]]; then
        log "skip    $1 (exists; FORCE=1 to rebuild)"
        return 1
    fi
    log "build   $1"
}

# First N lines of a remote gzip file. head closes the pipe early, which kills curl and gunzip
# with SIGPIPE, so the pipeline status is head's alone and the line count is checked instead.
head_of_remote_gz() {
    local url=$1 lines=$2 target=$3
    (set +o pipefail; curl -fsL "$url" | gunzip -c | head -n "$lines") >"$target.part"
    if [[ $(wc -l <"$target.part") -ne $lines ]]; then
        rm -f "$target.part"
        log "error   could not read $url; if it moved, browse its parent folder"
        return 1
    fi
    mv "$target.part" "$target"
}

# 1. Small synthetic VCF, same records as tests/samples.py: three variants, one multi-allelic line.
if needed calls.vcf; then
    printf '##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n%s\n%s\n' \
        $'chr1\t100\trs1\tA\tG\t50\tPASS\tAF=0.25;DP=10' \
        $'chr2\t200\t.\tC\tT,A\t.\t.\tAF=0.1,0.2;DB' >calls.vcf
fi
if needed calls.vcf.gz; then
    gzip -c calls.vcf >calls.vcf.gz
fi

# 2. Real ClinVar summary (full format): header plus the first rows, then the 12-column
# simplified format picked from it by column name. Rows without coordinates count as invalid.
if needed variant_summary_head.txt; then
    head_of_remote_gz "$CLINVAR_SUMMARY_URL" $((CLINVAR_ROWS + 1)) variant_summary_head.txt
fi
if needed clinvar_simplified.tsv; then
    awk -F'\t' -v OFS='\t' '
        NR == 1 {
            sub(/^#/, "")
            for (i = 1; i <= NF; i++) c[$i] = i
            n = split("AlleleID Type Name GeneSymbol ClinicalSignificance ReviewStatus Assembly Chromosome Start Stop ReferenceAlleleVCF AlternateAlleleVCF", k, " ")
        }
        {
            line = ""
            for (j = 1; j <= n; j++) line = line (j > 1 ? OFS : "") (NR == 1 ? k[j] : $c[k[j]])
            print line
        }' variant_summary_head.txt >clinvar_simplified.tsv
fi

# 3. Real VCF with AF (1000 Genomes phase 3, GRCh37): one chr22 region, sample columns dropped.
# bcftools reads the remote index, so only the region is downloaded. Exact duplicates are
# removed because the API rejects them.
if command -v bcftools >/dev/null; then
    if needed 1kg_chr22_small.vcf.gz; then
        bcftools view -G -r "$KG_REGION" -Ou "$KG_CHR22_URL" |
            bcftools norm -d exact -Oz -o 1kg_chr22_small.vcf.gz
        rm -f "$(basename "$KG_CHR22_URL").tbi"
    fi
else
    log "skip    1kg_chr22_small.vcf.gz (bcftools not installed: sudo apt install bcftools)"
fi

# 4. VCF without an AF key (ClinVar VCF has AF_ESP, AF_EXAC, AF_TGP only): every row gets af null.
if needed clinvar_head.vcf.gz; then
    head_of_remote_gz "$CLINVAR_VCF_URL" "$CLINVAR_VCF_LINES" clinvar_head.vcf
    gzip -f clinvar_head.vcf
fi

# Files the API must reject with 422.
mkdir -p rejected
if needed rejected/calls.txt; then
    cp calls.vcf rejected/calls.txt # wrong extension
fi
if needed rejected/fake.vcf.gz; then
    cp calls.vcf rejected/fake.vcf.gz # .gz name, plain text content
fi
if needed rejected/bad_af.vcf; then
    # two ALT alleles, one AF value
    printf '##fileformat=VCFv4.2\n#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\nchr1\t1\t.\tA\tG,T\t.\t.\tAF=0.5\n' \
        >rejected/bad_af.vcf
fi

log "done    $out"
ls -lh "$out" "$out/rejected" >&2
