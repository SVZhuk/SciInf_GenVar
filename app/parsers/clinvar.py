"""ClinVar tab-separated summary parser: detects the column format and counts valid entries."""

from dataclasses import dataclass
from enum import StrEnum

from app.core.exceptions import InvalidFileFormatError

# NCBI adds columns at the end over time (32 in older releases, 40 in 2026), so the full format
# is recognised by its first column, a minimum width and the columns this service relies on.
FULL_MIN_COLUMNS = 32
SIMPLIFIED_COLUMNS = (
    "AlleleID",
    "Type",
    "Name",
    "GeneSymbol",
    "ClinicalSignificance",
    "ReviewStatus",
    "Assembly",
    "Chromosome",
    "Start",
    "Stop",
    "ReferenceAlleleVCF",
    "AlternateAlleleVCF",
)
REQUIRED_COLUMNS = frozenset(
    {"AlleleID", "GeneSymbol", "ClinicalSignificance", "Assembly", "Chromosome", "Start", "Stop"}
)
UNKNOWN_VALUES = frozenset({"", "na", "-"})


class ClinVarFormat(StrEnum):
    FULL = "full"
    SIMPLIFIED = "simplified"


@dataclass(frozen=True, slots=True)
class ClinVarSummary:
    column_format: ClinVarFormat
    entry_count: int
    invalid_count: int


def parse_clinvar(lines: list[str]) -> ClinVarSummary:
    if not lines:
        raise InvalidFileFormatError("file is empty")
    header = lines[0].removeprefix("#").split("\t")
    column_format = _detect_format(header)
    column = {name: index for index, name in enumerate(header)}

    valid = invalid = 0
    for line in lines[1:]:
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) == len(header) and _is_valid_entry(fields, column):
            valid += 1
        else:
            invalid += 1
    if valid == 0:
        raise InvalidFileFormatError("no valid entries")
    return ClinVarSummary(column_format=column_format, entry_count=valid, invalid_count=invalid)


def _detect_format(header: list[str]) -> ClinVarFormat:
    if tuple(header) == SIMPLIFIED_COLUMNS:
        return ClinVarFormat.SIMPLIFIED
    is_full = header[0] == "AlleleID" and len(header) >= FULL_MIN_COLUMNS
    if is_full and set(header) >= REQUIRED_COLUMNS:
        return ClinVarFormat.FULL
    raise InvalidFileFormatError(
        "header is neither the full ClinVar variant_summary format nor the 12-column format", 1
    )


def _is_valid_entry(fields: list[str], column: dict[str, int]) -> bool:
    def value(name: str) -> str:
        return fields[column[name]].strip()

    return (
        _is_positive_integer(value("AlleleID"))
        and value("Chromosome").lower() not in UNKNOWN_VALUES
        and _is_positive_integer(value("Start"))
        and _is_positive_integer(value("Stop"))
        and int(value("Start")) <= int(value("Stop"))
    )


def _is_positive_integer(value: str) -> bool:
    return value.isascii() and value.isdigit() and int(value) > 0
