import pytest

from app.core.exceptions import InvalidFileFormatError
from app.parsers.vcf import ParsedVariant, parse_vcf
from tests.samples import VCF_HEADER, VCF_RECORDS, vcf_text


def parse(*records: str, header: str = VCF_HEADER) -> list[ParsedVariant]:
    return parse_vcf(vcf_text(*records, header=header).splitlines()).variants


def test_parses_fixed_columns() -> None:
    [variant] = parse(VCF_RECORDS[0])

    assert variant == ParsedVariant(
        chrom="chr1",
        pos=100,
        vcf_id="rs1",
        ref="A",
        alt="G",
        qual=50.0,
        filter="PASS",
        af=0.25,
        info={"AF": "0.25", "DP": "10"},
    )


def test_missing_values_become_none() -> None:
    [variant] = parse("chr1\t100\t.\tA\tG\t.\t.\t.")

    assert (variant.vcf_id, variant.qual, variant.filter, variant.af, variant.info) == (
        None,
        None,
        None,
        None,
        {},
    )


def test_multi_allelic_line_splits_with_matching_af() -> None:
    variants = parse(VCF_RECORDS[1])

    assert [(v.alt, v.af) for v in variants] == [("T", 0.1), ("A", 0.2)]


def test_info_flag_is_true() -> None:
    [first, _] = parse(VCF_RECORDS[1])

    assert first.info["DB"] is True


def test_reference_only_site_is_skipped() -> None:
    assert parse("chr1\t100\t.\tA\t.\t.\t.\t.") == []


def test_blank_lines_are_ignored() -> None:
    assert len(parse(VCF_RECORDS[0], "")) == 1


@pytest.mark.parametrize(
    ("samples", "expected"),
    [((), 0), (("FORMAT",), 0), (("FORMAT", "S1", "S2"), 2)],
)
def test_sample_count_from_header(samples: tuple[str, ...], expected: int) -> None:
    header = "\t".join([VCF_HEADER, *samples])

    assert parse_vcf(vcf_text(header=header).splitlines()).sample_count == expected


def test_rejects_missing_fileformat_line() -> None:
    with pytest.raises(InvalidFileFormatError) as error:
        parse_vcf([VCF_HEADER, VCF_RECORDS[0]])

    assert error.value.line_no == 1


def test_rejects_missing_header() -> None:
    with pytest.raises(InvalidFileFormatError):
        parse_vcf(["##fileformat=VCFv4.2", "##source=test"])


def test_rejects_wrong_header() -> None:
    with pytest.raises(InvalidFileFormatError) as error:
        parse(header="#CHROM\tPOS")

    assert error.value.line_no == 2


@pytest.mark.parametrize(
    "record",
    [
        "chr1\t100\t.\tA\tG\t.\t.",
        "\t100\t.\tA\tG\t.\t.\t.",
        "chr1\t0\t.\tA\tG\t.\t.\t.",
        "chr1\tten\t.\tA\tG\t.\t.\t.",
        "chr1\t100\t.\tX\tG\t.\t.\t.",
        "chr1\t100\t.\tA\tG,?\t.\t.\t.",
        "chr1\t100\t.\tA\tG\thigh\t.\t.",
        "chr1\t100\t.\tA\tG\tnan\t.\t.",
        "chr1\t100\t.\tA\tG\t.\t.\t=1",
        "chr1\t100\t.\tA\tG\t.\t.\tAF",
        "chr1\t100\t.\tA\tG,T\t.\t.\tAF=0.1",
        "chr1\t100\t.\tA\tG\t.\t.\tAF=1.5",
    ],
)
def test_rejects_invalid_record_with_line_number(record: str) -> None:
    with pytest.raises(InvalidFileFormatError) as error:
        parse(VCF_RECORDS[0], record)

    assert error.value.line_no == 4


@pytest.mark.parametrize(
    "alt", ["<DEL>", "*", "G]17:198982]", "]13:123456]T", "C[2:321682[", "[17:198983[A", ".A", "G."]
)
def test_accepts_symbolic_spanning_and_breakend_alleles(alt: str) -> None:
    [variant] = parse(f"chr1\t100\t.\tA\t{alt}\t.\t.\t.")

    assert variant.alt == alt


def test_single_missing_af_applies_to_every_allele() -> None:
    variants = parse("chr1\t100\t.\tA\tG,T\t.\t.\tAF=.")

    assert [v.af for v in variants] == [None, None]


def test_rejects_duplicate_variant() -> None:
    with pytest.raises(InvalidFileFormatError):
        parse(VCF_RECORDS[0], VCF_RECORDS[0])


def test_error_message_does_not_contain_file_content() -> None:
    with pytest.raises(InvalidFileFormatError) as error:
        parse("chrSECRET\t100\t.\tA\tG\tSECRET\t.\t.")

    assert "SECRET" not in str(error.value)
