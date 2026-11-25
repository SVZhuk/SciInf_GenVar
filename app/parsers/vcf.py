"""VCF parser: pure functions, no IO. A multi-allelic line becomes one variant per ALT allele."""

import math
import re
from dataclasses import dataclass

from app.core.exceptions import InvalidFileFormatError

FILEFORMAT_PREFIX = "##fileformat=VCFv4"
HEADER_COLUMNS = ("#CHROM", "POS", "ID", "REF", "ALT", "QUAL", "FILTER", "INFO")
FIXED_COLUMNS_WITH_FORMAT = len(HEADER_COLUMNS) + 1
MISSING = "."
REF_PATTERN = re.compile(r"[ACGTN]+", re.IGNORECASE)
ALT_PATTERN = re.compile(
    r"[ACGTN]+"  # bases
    r"|\*"  # allele missing because of an upstream deletion
    r"|<[^<>]+>"  # symbolic allele, e.g. <DEL>
    r"|[ACGTN]*[\[\]][^\[\]]+[\[\]][ACGTN]*"  # breakend, e.g. G]17:198982]
    r"|\.[ACGTN]+|[ACGTN]+\.",  # single breakend, e.g. .A
    re.IGNORECASE,
)

type InfoValue = str | bool


@dataclass(frozen=True, slots=True)
class ParsedVariant:
    chrom: str
    pos: int
    vcf_id: str | None
    ref: str
    alt: str
    qual: float | None
    filter: str | None
    af: float | None
    info: dict[str, InfoValue]


@dataclass(frozen=True, slots=True)
class ParsedVcf:
    sample_count: int
    variants: list[ParsedVariant]


def parse_vcf(lines: list[str]) -> ParsedVcf:
    if not lines or not lines[0].startswith(FILEFORMAT_PREFIX):
        raise InvalidFileFormatError("first line must be ##fileformat=VCFv4.x", 1)
    header_no = next((no for no, line in enumerate(lines, 1) if not line.startswith("##")), None)
    if header_no is None or tuple(lines[header_no - 1].split("\t")[:8]) != HEADER_COLUMNS:
        raise InvalidFileFormatError(
            "expected the header #CHROM POS ID REF ALT QUAL FILTER INFO", header_no
        )
    header = lines[header_no - 1].split("\t")
    sample_count = max(len(header) - FIXED_COLUMNS_WITH_FORMAT, 0)

    variants: list[ParsedVariant] = []
    seen: set[tuple[str, int, str, str]] = set()
    for no, line in enumerate(lines[header_no:], start=header_no + 1):
        if not line.strip():
            continue
        for variant in _parse_record(line, no):
            key = (variant.chrom, variant.pos, variant.ref, variant.alt)
            if key in seen:
                raise InvalidFileFormatError("duplicate variant (CHROM, POS, REF, ALT)", no)
            seen.add(key)
            variants.append(variant)
    return ParsedVcf(sample_count=sample_count, variants=variants)


def _parse_record(line: str, no: int) -> list[ParsedVariant]:
    fields = line.split("\t")
    if len(fields) < len(HEADER_COLUMNS):
        raise InvalidFileFormatError(
            f"expected at least {len(HEADER_COLUMNS)} tab-separated columns, got {len(fields)}", no
        )
    chrom, pos, vcf_id, ref, alt, qual, filter_, info = fields[: len(HEADER_COLUMNS)]
    if not chrom or chrom == MISSING:
        raise InvalidFileFormatError("CHROM is empty", no)
    if not (pos.isascii() and pos.isdigit() and int(pos) > 0):
        raise InvalidFileFormatError("POS must be a positive integer", no)
    if not REF_PATTERN.fullmatch(ref):
        raise InvalidFileFormatError("REF must contain only A, C, G, T, N", no)
    if alt == MISSING:
        return []  # a reference-only site has no variant to store
    alts = alt.split(",")
    if not all(ALT_PATTERN.fullmatch(allele) for allele in alts):
        raise InvalidFileFormatError("ALT has an invalid allele", no)
    info_fields = _parse_info(info, no)
    frequencies = _allele_frequencies(info_fields.get("AF"), len(alts), no)
    return [
        ParsedVariant(
            chrom=chrom,
            pos=int(pos),
            vcf_id=None if vcf_id == MISSING else vcf_id,
            ref=ref,
            alt=allele,
            qual=_parse_number(qual, "QUAL", no),
            filter=None if filter_ == MISSING else filter_,
            af=frequency,
            info=info_fields,
        )
        for allele, frequency in zip(alts, frequencies, strict=True)
    ]


def _parse_info(info: str, no: int) -> dict[str, InfoValue]:
    if info == MISSING:
        return {}
    fields: dict[str, InfoValue] = {}
    for item in info.split(";"):
        key, has_value, value = item.partition("=")
        if not key:
            raise InvalidFileFormatError("INFO has an empty key", no)
        fields[key] = value if has_value else True  # a key without a value is a flag
    return fields


def _allele_frequencies(af: InfoValue | None, alt_count: int, no: int) -> list[float | None]:
    if af is None or af == MISSING:  # one "." stands for every allele
        return [None] * alt_count
    if isinstance(af, bool):
        raise InvalidFileFormatError("AF must have a value", no)
    values = af.split(",")
    if len(values) != alt_count:
        raise InvalidFileFormatError(f"AF has {len(values)} values for {alt_count} ALT alleles", no)
    frequencies = [_parse_number(value, "AF", no) for value in values]
    if any(f is not None and not 0 <= f <= 1 for f in frequencies):
        raise InvalidFileFormatError("AF must be between 0 and 1", no)
    return frequencies


def _parse_number(value: str, name: str, no: int) -> float | None:
    if value == MISSING:
        return None
    error = InvalidFileFormatError(f"{name} must be a number or '.'", no)
    try:
        number = float(value)
    except ValueError:
        raise error from None
    if not math.isfinite(number):  # float() accepts "nan" and "inf"
        raise error
    return number
