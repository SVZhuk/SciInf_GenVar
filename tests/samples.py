"""Small, readable input files built in code, so every test shows the data it relies on."""

VCF_HEADER = "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO"
VCF_RECORDS = (
    "chr1\t100\trs1\tA\tG\t50\tPASS\tAF=0.25;DP=10",
    "chr2\t200\t.\tC\tT,A\t.\t.\tAF=0.1,0.2;DB",
)


def vcf_text(*records: str, header: str = VCF_HEADER) -> str:
    return "\n".join(["##fileformat=VCFv4.2", header, *records]) + "\n"


def sample_vcf() -> bytes:
    """Two lines, three variants: the second line is multi-allelic."""
    return vcf_text(*VCF_RECORDS).encode()


SIMPLIFIED_HEADER = (
    "#AlleleID\tType\tName\tGeneSymbol\tClinicalSignificance\tReviewStatus\tAssembly\t"
    "Chromosome\tStart\tStop\tReferenceAlleleVCF\tAlternateAlleleVCF"
)
SIMPLIFIED_ROW = (
    "15041\tIndel\tNM_014855.3(AP5Z1):c.80_83del\tAP5Z1\tPathogenic\t"
    "criteria provided, single submitter\tGRCh38\t7\t4781213\t4781216\tGGAT\tG"
)

FULL_COLUMNS = (
    "AlleleID",
    "Type",
    "Name",
    "GeneID",
    "GeneSymbol",
    "HGNC_ID",
    "ClinicalSignificance",
    "ClinSigSimple",
    "LastEvaluated",
    "RS# (dbSNP)",
    "nsv/esv (dbVar)",
    "RCVaccession",
    "PhenotypeIDs",
    "PhenotypeList",
    "Origin",
    "OriginSimple",
    "Assembly",
    "ChromosomeAccession",
    "Chromosome",
    "Start",
    "Stop",
    "ReferenceAllele",
    "AlternateAllele",
    "Cytogenetic",
    "ReviewStatus",
    "NumberSubmitters",
    "Guidelines",
    "TestedInGTR",
    "OtherIDs",
    "SubmitterCategories",
    "VariationID",
    "PositionVCF",
)


def full_row(allele_id: str = "15041", start: str = "4781213") -> str:
    values = dict.fromkeys(FULL_COLUMNS, "-")
    values.update(
        AlleleID=allele_id,
        GeneSymbol="AP5Z1",
        ClinicalSignificance="Pathogenic",
        Assembly="GRCh38",
        Chromosome="7",
        Start=start,
        Stop="4781216",
    )
    return "\t".join(values.values())


def clinvar_text(header: str, *rows: str) -> bytes:
    return ("\n".join([header, *rows]) + "\n").encode()


def sample_clinvar() -> bytes:
    return clinvar_text(SIMPLIFIED_HEADER, SIMPLIFIED_ROW)
