import pytest

from app.core.exceptions import InvalidFileFormatError
from app.parsers.clinvar import ClinVarFormat, ClinVarSummary, parse_clinvar
from tests.samples import (
    FULL_COLUMNS,
    SIMPLIFIED_HEADER,
    SIMPLIFIED_ROW,
    clinvar_text,
    full_row,
)

FULL_HEADER = "#" + "\t".join(FULL_COLUMNS)


def parse(header: str, *rows: str) -> ClinVarSummary:
    return parse_clinvar(clinvar_text(header, *rows).decode().splitlines())


def test_simplified_format() -> None:
    summary = parse(SIMPLIFIED_HEADER, SIMPLIFIED_ROW)

    assert summary == ClinVarSummary(ClinVarFormat.SIMPLIFIED, entry_count=1, invalid_count=0)


def test_full_format() -> None:
    summary = parse(FULL_HEADER, full_row(), full_row("15042"))

    assert summary == ClinVarSummary(ClinVarFormat.FULL, entry_count=2, invalid_count=0)


def test_full_format_accepts_columns_added_by_newer_releases() -> None:
    header = FULL_HEADER + "\tReferenceAlleleVCF\tAlternateAlleleVCF"

    summary = parse(header, full_row() + "\tGGAT\tG")

    assert summary.column_format is ClinVarFormat.FULL


def test_header_without_hash_is_accepted() -> None:
    assert parse(SIMPLIFIED_HEADER.removeprefix("#"), SIMPLIFIED_ROW).entry_count == 1


@pytest.mark.parametrize(
    "row",
    [
        full_row(allele_id="x"),
        full_row(start="-1"),
        full_row(start="9999999"),
        full_row().replace("\t7\t", "\tna\t"),
        "\t".join(["1"] * 5),
    ],
)
def test_invalid_entries_are_counted_not_fatal(row: str) -> None:
    summary = parse(FULL_HEADER, full_row(), row)

    assert (summary.entry_count, summary.invalid_count) == (1, 1)


def test_blank_lines_are_ignored() -> None:
    assert parse(SIMPLIFIED_HEADER, SIMPLIFIED_ROW, "").invalid_count == 0


@pytest.mark.parametrize(
    "header",
    [
        "#CHROM\tPOS\tID",
        SIMPLIFIED_HEADER.replace("GeneSymbol", "Gene"),
        "#" + "\t".join(FULL_COLUMNS[:31]),
        FULL_HEADER.replace("Chromosome\t", "Chr\t"),
    ],
)
def test_rejects_unknown_header(header: str) -> None:
    with pytest.raises(InvalidFileFormatError) as error:
        parse(header, SIMPLIFIED_ROW)

    assert error.value.line_no == 1


def test_rejects_empty_file() -> None:
    with pytest.raises(InvalidFileFormatError):
        parse_clinvar([])


def test_rejects_file_without_valid_entries() -> None:
    with pytest.raises(InvalidFileFormatError):
        parse(SIMPLIFIED_HEADER)
