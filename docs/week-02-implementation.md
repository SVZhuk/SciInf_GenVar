# Week 2: VCF and ClinVar annotation file endpoints

Goal: upload VCF files into a project, parse and validate them, store every variant (with its
allele frequency) in Postgres and the raw file in S3; upload ClinVar annotation files, validate
them and count their valid entries; list, read and delete both kinds of file.
Read [ARCHITECTURE.md](../ARCHITECTURE.md) first and finish
[week 1](week-01-implementation.md); this guide builds on that code.

Every code block below is complete and was verified end to end (191 tests, 99% coverage, mypy
strict, the Docker stack serving every endpoint). Type it (or copy it) exactly, run the check at
the end of each step, and commit once the step works. Files that week 1 created and this week
changes are shown as a diff (`+` lines added, `-` lines removed) when the change is small, and in
full otherwise.

## Task coverage

| Course task | Where |
|---|---|
| 5 `POST /projects/{project_id}/vcf/`: upload a VCF file | Steps 9 and 10 |
| 5 Validate file extension (.vcf or .vcf.gz) | Step 3 (`file_extension`) |
| 5 Parse and validate the VCF file | Step 4 |
| 5 Store metadata in the database | Steps 6 and 8 (`vcf_files`) |
| 5 Extract all variants into the variants table | Steps 4, 6, 8 (`variants`, batched insert) |
| 5 Extract AF from INFO and store it in the variants table | Step 4 (`_allele_frequencies`), step 6 (`variants.af`) |
| 5 `GET /projects/{project_id}/vcf/`: list VCF files | Steps 9 and 10 |
| 5 `GET /projects/{project_id}/vcf/{vcf_id}`: metadata and variants | Steps 9 and 10 (paged) |
| 5 `DELETE /projects/{project_id}/vcf/{vcf_id}`: file and all its data | Steps 9 and 10 (cascade + S3) |
| 6 `POST /projects/{project_id}/annotation/`: upload a ClinVar file | Steps 9 and 10 |
| 6 Full (32 or more columns) and simplified (12 columns) tab-separated format | Step 5 |
| 6 Validate the format and count valid entries | Step 5 |
| 6 Store the file and save metadata | Steps 7 to 9 |
| 6 `GET /projects/{project_id}/annotation/`: list annotation files | Steps 9 and 10 |
| 6 `DELETE /projects/{project_id}/annotation/{annotation_id}` | Steps 9 and 10 |
| Rubric: logging, 80% coverage, FIRST tests | Step 9 (logging), step 12 (tests) |

## Definition of done

- [ ] `docker compose up --build` starts db, local S3, runs migrations, serves the API on :8000
- [ ] All seven new endpoints return the documented status codes
- [ ] Uploading a `.vcf` or `.vcf.gz` file stores one `variants` row per ALT allele, with `af`
- [ ] Deleting a VCF file, an annotation file or a project removes its rows and its S3 objects
- [ ] `alembic upgrade head`, `alembic check`, `alembic downgrade base` all run cleanly
- [ ] `poetry run python scripts/check.py` passes (coverage at least 80%)
- [ ] GitHub Actions is green on push and on pull request

## Design decisions for this week

| Decision | Why |
|---|---|
| Parse synchronously inside the upload request, return 201 | KISS: files are capped at 50 MB; a job queue can come later if uploads grow |
| Parsing runs in a worker thread (`asyncio.to_thread`) | It is CPU work; on the event loop it would stall every other request, health checks included |
| No `status` column on `vcf_files` | A row exists only after a successful parse, so it could only ever say "parsed" |
| Raw file in S3, metadata and variants in Postgres | Rows stay small; the original file is kept for re-processing |
| S3 key built by the server: `projects/{project_id}/vcf/{vcf_file_id}.vcf.gz` | A client filename never becomes a path; deleting a project is one prefix delete |
| Upload: rows are written (flushed) before the S3 object | If S3 fails, the transaction rolls back and nothing is half-saved |
| Delete: S3 objects are removed only after the commit (`AfterCommit`) | If the commit fails, rows and files both survive; a database row never points at a missing file |
| No unique constraint on (`vcf_file_id`, `chrom`, `pos`, `ref`, `alt`) | A B-tree entry is limited to about 2.7 KB and long indel alleles exceed it; the parser rejects duplicates |
| Oversized bodies are refused from the `Content-Length` header | Starlette writes a multipart body to a temp file before the route runs; checking afterwards would let a 20 GB upload fill the disk |
| A multi-allelic line becomes one row per ALT allele, each with its own AF | (`chrom`, `pos`, `ref`, `alt`) then identifies a variant; filtering by AF is a plain `WHERE` |
| Hand-written parser, no pysam/cyvcf2 | No C extension to install; the format rules are explicit and tested |
| Annotation upload stores the file and metadata only | The task asks to validate and count; matching entries to variants is a later week |
| Local S3 is moto server in Docker Compose | MinIO no longer publishes Docker images; moto is already the test fake, so one tool covers both |

### The ClinVar formats

NCBI publishes `variant_summary.txt.gz` at
https://ftp.ncbi.nlm.nih.gov/pub/clinvar/tab_delimited/. Its header starts with `#AlleleID`. The
course calls it the "32-column" format, but NCBI adds columns at the end over time (the README
lists 40 in 2026), so the parser accepts any header that starts with `AlleleID`, has at least 32
columns and contains the columns the service needs.

The simplified format is defined by this project: exactly these 12 tab-separated columns.

```text
#AlleleID  Type  Name  GeneSymbol  ClinicalSignificance  ReviewStatus  Assembly
Chromosome  Start  Stop  ReferenceAlleleVCF  AlternateAlleleVCF
```

A row is a valid entry when it has as many fields as the header, a positive integer `AlleleID`, a
known `Chromosome` (not empty, `na` or `-`) and positive integer `Start <= Stop`. Invalid rows are
counted and logged, not fatal; a file with no valid entry is rejected.

## Prerequisites

Week 1 done and green. Same tools as week 1: Python 3.15, Poetry 2.x, Docker with Compose v2.

---

## Step 1. Dependencies

```bash
poetry add python-multipart boto3
poetry add --group dev "boto3-stubs[s3]" "moto[s3]"
```

Then widen the `python-multipart` pin Poetry wrote for a `0.0.x` version, so patch releases
(security fixes) can still install: `"python-multipart (>=0.0.34,<0.1.0)"`, then `poetry lock`.

| Package | Why |
|---|---|
| python-multipart | FastAPI needs it to read `multipart/form-data` file uploads (`UploadFile`) |
| boto3 | AWS SDK, S3 client |
| boto3-stubs[s3] | Type hints for the S3 client, so mypy strict checks every call |
| moto[s3] | In-process fake of AWS used by the S3 storage tests, and the local S3 server |

## Step 2. Settings and domain errors

`app/core/config.py`:

```diff
@@ -15,4 +15,8 @@ class Settings(BaseSettings):
     database_url: SecretStr
     log_level: LogLevel = "INFO"
+    s3_bucket: str = "gva-files"
+    s3_endpoint_url: str | None = None
+    aws_region: str = "us-east-1"
+    max_upload_bytes: int = 50 * 1024 * 1024  # also caps a .gz file after decompression
```

- `s3_endpoint_url` is `None` on AWS (boto3 finds the regional endpoint) and points at the local
  S3 container in development.
- Credentials are deliberately not settings: boto3 reads them from its default chain
  (environment variables locally, the ECS task role on AWS), so they never sit in a `Settings`
  object that could be logged.
- `max_upload_bytes` caps the upload and, for `.gz` files, the decompressed content too.

`.env.example`:

```diff
@@ -2,2 +2,7 @@ DATABASE_URL=postgresql+asyncpg://app:app@localhost:5434/gva
 TEST_DATABASE_URL=postgresql+asyncpg://app:app@localhost:5433/gva_test
 LOG_LEVEL=INFO
+S3_BUCKET=gva-files
+S3_ENDPOINT_URL=http://localhost:9000
+# Local moto S3 accepts any credentials; never put real AWS keys here.
+AWS_ACCESS_KEY_ID=local
+AWS_SECRET_ACCESS_KEY=local
```

`app/core/exceptions.py`:

```diff
@@ -14,2 +14,36 @@ class ProjectNameConflictError(Exception):
         super().__init__(f"Project name {name!r} already exists")
         self.name = name
+
+
+class VcfFileNotFoundError(Exception):
+    def __init__(self, vcf_file_id: UUID) -> None:
+        super().__init__(f"VCF file {vcf_file_id} not found")
+        self.vcf_file_id = vcf_file_id
+
+
+class AnnotationFileNotFoundError(Exception):
+    def __init__(self, annotation_file_id: UUID) -> None:
+        super().__init__(f"Annotation file {annotation_file_id} not found")
+        self.annotation_file_id = annotation_file_id
+
+
+class InvalidFilenameError(Exception):
+    def __init__(self, allowed: tuple[str, ...], max_length: int) -> None:
+        super().__init__(
+            f"Filename must end with one of {', '.join(allowed)} "
+            f"and be at most {max_length} characters"
+        )
+
+
+class FileStorageError(Exception):
+    """The file store refused an operation; raised by storage, never mapped to a 4xx."""
+
+
+class InvalidFileFormatError(Exception):
+    """File content is invalid; the message names the line and the rule, never the content."""
+
+    def __init__(self, reason: str, line_no: int | None = None) -> None:
+        where = f"line {line_no}: " if line_no is not None else ""
+        super().__init__(f"Invalid file: {where}{reason}")
+        self.reason = reason
+        self.line_no = line_no
```

`FileStorageError` wraps boto3 errors, so code above the storage layer never imports botocore.
`InvalidFileFormatError` keeps `reason` and `line_no` as attributes, so services can log them as
structured fields. Its message names the rule that failed, never the offending content: a VCF
line can hold patient data, and the message goes into the HTTP response and the log.

## Step 3. Shared parsing helpers

Both parsers need the same two things: check the filename and turn bytes (maybe gzip) into text
lines. They live once in `app/parsers/` (DRY). Parsers are pure functions: no database, no S3,
no FastAPI, so they are tested with plain strings in microseconds.

```bash
mkdir -p app/parsers app/storage
touch app/parsers/__init__.py app/storage/__init__.py
```

`app/parsers/text.py`:

```python
"""Helpers shared by the file parsers: filename check and decoding bytes into lines."""

import zlib

from app.core.exceptions import InvalidFileFormatError, InvalidFilenameError

MAX_FILENAME_LENGTH = 255
GZIP_MAGIC = b"\x1f\x8b"
GZIP_WBITS = zlib.MAX_WBITS | 16  # expect a gzip header and trailer


def file_extension(filename: str, allowed: tuple[str, ...]) -> str:
    """Return the allowed extension the filename ends with (case-insensitive)."""
    lower = filename.lower()
    extension = next((ext for ext in allowed if lower.endswith(ext)), None)
    if extension is None or len(filename) > MAX_FILENAME_LENGTH:
        raise InvalidFilenameError(allowed, MAX_FILENAME_LENGTH)
    return extension


def decode_lines(data: bytes, gzipped: bool, max_bytes: int) -> list[str]:
    if gzipped:
        data = _gunzip(data, max_bytes)
    if b"\x00" in data:
        raise InvalidFileFormatError("file contains NUL bytes")
    try:
        text = data.decode("utf-8-sig")  # drops a byte order mark written by Windows tools
    except UnicodeDecodeError as exc:
        raise InvalidFileFormatError("file is not UTF-8 text") from exc
    return text.splitlines()


def _gunzip(data: bytes, max_bytes: int) -> bytes:
    """Decompress at most max_bytes, so a small gzip bomb cannot exhaust memory.

    bgzip, the usual VCF compressor, writes many gzip members back to back; read them all.
    """
    if not data.startswith(GZIP_MAGIC):
        raise InvalidFileFormatError("file ends with .gz but is not gzip compressed")
    output = bytearray()
    while data:
        member = zlib.decompressobj(wbits=GZIP_WBITS)
        try:
            output += member.decompress(data, max_bytes + 1 - len(output))
        except zlib.error as exc:
            raise InvalidFileFormatError("gzip data is corrupt") from exc
        if len(output) > max_bytes:
            raise InvalidFileFormatError(f"decompressed file is larger than {max_bytes} bytes")
        if not member.eof:
            raise InvalidFileFormatError("gzip data is truncated")
        data = member.unused_data
    return bytes(output)
```

- The extension check is case-insensitive and also caps the filename length, which is the
  `vcf_files.filename` column width.
- Gzip bombs: a 50 KB `.gz` file can expand to gigabytes. `zlib.decompressobj().decompress(data,
  max_length)` stops after `max_length` bytes, so memory stays bounded.
- bgzip, the tool `bcftools` and `tabix` use, writes a `.vcf.gz` as many gzip members back to back.
  `unused_data` holds the bytes after the current member, so the loop reads all of them.
- Postgres cannot store the NUL character in `text` or `jsonb`; rejecting it here turns a would-be
  500 into a 422.
- `utf-8-sig` decodes UTF-8 and drops a byte order mark if there is one (Excel and other Windows
  tools write it); otherwise the first line would not start with `##fileformat` or `AlleleID`.

## Step 4. VCF parser

A VCF file has meta lines (`##...`), one header line, then one tab-separated record per line:

```text
##fileformat=VCFv4.2
#CHROM  POS  ID   REF  ALT  QUAL  FILTER  INFO
chr1    100  rs1  A    G    50    PASS    AF=0.25;DP=10
chr2    200  .    C    T,A  .     .       AF=0.1,0.2;DB
```

`.` means "missing". `ALT` may list several alleles; then `AF` lists one frequency per allele, in
the same order. `DB` (no `=`) is a flag. Columns after `INFO` (`FORMAT` and one per sample) are
optional; this week only counts the samples.

`app/parsers/vcf.py`:

```python
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
```

- Every rejection raises `InvalidFileFormatError` with the line number, so the user can fix the
  file; the second line above becomes two `ParsedVariant`s (`T` with AF 0.1, `A` with AF 0.2).
- `zip(..., strict=True)` documents that the two lists always have the same length (checked just
  before); a bug would fail loudly instead of dropping alleles.
- `float()` accepts `"nan"` and `"inf"`, which are not valid numbers in a VCF and not valid JSON;
  `math.isfinite` rejects them.
- A reference-only line (`ALT` is `.`) carries no variant and is skipped, not rejected.
- `AF=.` is one missing value for all alleles (the VCF specification allows a single `.` for a
  missing list), so it becomes `None` for each allele instead of failing the length check.
- `ALT_PATTERN` accepts bases, `*`, symbolic alleles (`<DEL>`) and the breakends written by
  structural variant callers (`G]17:198982]`, `.A`).
- Duplicates (same `CHROM`, `POS`, `REF`, `ALT`) are rejected here, the only place they are
  checked (step 6 explains why the database does not).
- `ParsedVariant` is a frozen dataclass with `slots=True`: immutable and small, which matters when
  a file has hundreds of thousands of variants. Its fields have the same names as the `variants`
  columns, so `asdict(variant)` is ready to insert.

## Step 5. ClinVar parser

`app/parsers/clinvar.py`:

```python
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
```

- `ClinVarFormat` is a `StrEnum`: stored as the plain string `"full"` or `"simplified"`, and the
  response schema still only allows those two values.
- `removeprefix("#")` accepts the header with or without NCBI's leading `#`.
- Bad rows are counted, not fatal: real ClinVar releases contain rows without coordinates (for
  example `Start` = `-1`). Only a file with zero valid entries is rejected.

## Step 6. Models and the migration

| Table | Columns | Constraints and indexes |
|---|---|---|
| `vcf_files` | `vcf_file_id` uuid PK, `project_id`, `filename`, `s3_key`, `sample_count`, `variant_count`, `uploaded_at` | FK to projects `ON DELETE CASCADE`, index on `project_id`, unique `s3_key` |
| `variants` | `variant_id` bigint identity PK, `vcf_file_id`, `chrom`, `pos`, `vcf_id`, `ref`, `alt`, `qual`, `filter`, `af`, `info` jsonb | FK to vcf_files `ON DELETE CASCADE`, index (`vcf_file_id`, `variant_id`), index (`chrom`, `pos`) |
| `annotation_files` | `annotation_file_id` uuid PK, `project_id`, `filename`, `s3_key`, `column_format`, `entry_count`, `uploaded_at` | FK to projects `ON DELETE CASCADE`, index on `project_id`, unique `s3_key` |

`app/models/vcf_file.py`:

```python
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class VcfFileModel(Base):
    __tablename__ = "vcf_files"

    vcf_file_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.project_id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    s3_key: Mapped[str] = mapped_column(String(1024), unique=True)
    sample_count: Mapped[int]
    variant_count: Mapped[int]
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class VariantModel(Base):
    __tablename__ = "variants"
    # No unique (vcf_file_id, chrom, pos, ref, alt): a B-tree entry is limited to about 2.7 KB
    # and long indel alleles exceed it. The parser rejects duplicates instead.
    __table_args__ = (
        Index("ix_variants_vcf_file_id_variant_id", "vcf_file_id", "variant_id"),
        Index("ix_variants_chrom_pos", "chrom", "pos"),
    )

    variant_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    vcf_file_id: Mapped[UUID] = mapped_column(
        ForeignKey("vcf_files.vcf_file_id", ondelete="CASCADE")
    )
    chrom: Mapped[str] = mapped_column(Text)
    pos: Mapped[int] = mapped_column(BigInteger)
    vcf_id: Mapped[str | None] = mapped_column(Text)
    ref: Mapped[str] = mapped_column(Text)
    alt: Mapped[str] = mapped_column(Text)
    qual: Mapped[float | None]
    filter: Mapped[str | None] = mapped_column(Text)
    af: Mapped[float | None]
    info: Mapped[dict[str, Any]] = mapped_column(JSONB)
```

`app/models/annotation_file.py`:

```python
from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AnnotationFileModel(Base):
    __tablename__ = "annotation_files"

    annotation_file_id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(
        ForeignKey("projects.project_id", ondelete="CASCADE"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255))
    s3_key: Mapped[str] = mapped_column(String(1024), unique=True)
    column_format: Mapped[str] = mapped_column(String(20))
    entry_count: Mapped[int]
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

`app/models/__init__.py`:

```python
"""Import every model here, so importing Base from this package registers all tables."""

from app.db.base import Base
from app.models.annotation_file import AnnotationFileModel
from app.models.project import ProjectModel
from app.models.vcf_file import VariantModel, VcfFileModel

__all__ = ["AnnotationFileModel", "Base", "ProjectModel", "VariantModel", "VcfFileModel"]
```

- `ON DELETE CASCADE`: deleting a project deletes its files, deleting a VCF file deletes its
  variants, in one statement inside Postgres. No relationship or loop in Python is needed.
- `variant_id` is `bigint` with `Identity()`: a file can hold millions of variants, and a
  sequential 8-byte key keeps the index small. Files keep UUIDs because clients address them.
- Free text from the file (`chrom`, `ref`, `alt`, ...) is `Text`: Postgres stores `text` and
  `varchar` the same way, and an indel allele has no natural length limit.
- `qual` and `af` are `Mapped[float | None]`: SQLAlchemy maps them to double precision.
- `info` is `jsonb`: INFO keys differ between variant callers, so they do not get columns. `af`
  does get its own column because the platform filters on it.
- No unique constraint on (`vcf_file_id`, `chrom`, `pos`, `ref`, `alt`), although that is the
  natural key. Postgres limits one B-tree index entry to about 2.7 KB, and a structural deletion
  can have a REF allele of several kilobases: the insert would fail with "index row size exceeds
  btree maximum" and the upload would be a 500. The parser enforces uniqueness instead.
- Index (`vcf_file_id`, `variant_id`) serves both "one page of this file's variants, in file
  order" (step 8) and the cascade delete, which looks variants up by `vcf_file_id`.

Generate, read, and test the migration:

```bash
docker compose up -d db
poetry run alembic revision --autogenerate -m "create vcf and annotation tables"
```

`alembic/versions/<date>-<rev>_create_vcf_and_annotation_tables.py` (your revision ids and date
differ; the "commands auto generated" comment lines are removed):

```python
"""create vcf and annotation tables

Revision ID: ca15e941ed40
Revises: 79befec44259
Create Date: 2026-11-24 10:42:54.522774

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ca15e941ed40"
down_revision: str | Sequence[str] | None = "79befec44259"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "annotation_files",
        sa.Column("annotation_file_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("s3_key", sa.String(length=1024), nullable=False),
        sa.Column("column_format", sa.String(length=20), nullable=False),
        sa.Column("entry_count", sa.Integer(), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.project_id"],
            name=op.f("fk_annotation_files_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("annotation_file_id", name=op.f("pk_annotation_files")),
        sa.UniqueConstraint("s3_key", name=op.f("uq_annotation_files_s3_key")),
    )
    op.create_index(
        op.f("ix_annotation_files_project_id"), "annotation_files", ["project_id"], unique=False
    )
    op.create_table(
        "vcf_files",
        sa.Column("vcf_file_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("s3_key", sa.String(length=1024), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column("variant_count", sa.Integer(), nullable=False),
        sa.Column(
            "uploaded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.project_id"],
            name=op.f("fk_vcf_files_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("vcf_file_id", name=op.f("pk_vcf_files")),
        sa.UniqueConstraint("s3_key", name=op.f("uq_vcf_files_s3_key")),
    )
    op.create_index(op.f("ix_vcf_files_project_id"), "vcf_files", ["project_id"], unique=False)
    op.create_table(
        "variants",
        sa.Column("variant_id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("vcf_file_id", sa.Uuid(), nullable=False),
        sa.Column("chrom", sa.Text(), nullable=False),
        sa.Column("pos", sa.BigInteger(), nullable=False),
        sa.Column("vcf_id", sa.Text(), nullable=True),
        sa.Column("ref", sa.Text(), nullable=False),
        sa.Column("alt", sa.Text(), nullable=False),
        sa.Column("qual", sa.Double(), nullable=True),
        sa.Column("filter", sa.Text(), nullable=True),
        sa.Column("af", sa.Double(), nullable=True),
        sa.Column("info", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["vcf_file_id"],
            ["vcf_files.vcf_file_id"],
            name=op.f("fk_variants_vcf_file_id_vcf_files"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("variant_id", name=op.f("pk_variants")),
    )
    op.create_index("ix_variants_chrom_pos", "variants", ["chrom", "pos"], unique=False)
    op.create_index(
        "ix_variants_vcf_file_id_variant_id",
        "variants",
        ["vcf_file_id", "variant_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_variants_vcf_file_id_variant_id", table_name="variants")
    op.drop_index("ix_variants_chrom_pos", table_name="variants")
    op.drop_table("variants")
    op.drop_index(op.f("ix_vcf_files_project_id"), table_name="vcf_files")
    op.drop_table("vcf_files")
    op.drop_index(op.f("ix_annotation_files_project_id"), table_name="annotation_files")
    op.drop_table("annotation_files")
```

```bash
poetry run alembic upgrade head
poetry run alembic check        # No new upgrade operations detected.
poetry run alembic downgrade base
poetry run alembic upgrade head
```

## Step 7. Schemas and file storage

`app/schemas/vcf_file.py`:

```python
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class VcfFileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    vcf_file_id: UUID
    project_id: UUID
    filename: str
    sample_count: int
    variant_count: int
    uploaded_at: datetime


class VariantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    variant_id: int
    chrom: str
    pos: int
    vcf_id: str | None
    ref: str
    alt: str
    qual: float | None
    filter: str | None
    af: float | None
    info: dict[str, str | bool]


class VcfFileDetail(VcfFileRead):
    variants: list[VariantRead]
```

`app/schemas/annotation_file.py`:

```python
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.parsers.clinvar import ClinVarFormat


class AnnotationFileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    annotation_file_id: UUID
    project_id: UUID
    filename: str
    column_format: ClinVarFormat
    entry_count: int
    uploaded_at: datetime
```

`s3_key` is not part of any response: it is an internal detail, and clients reach files only
through the API. `VcfFileDetail` extends `VcfFileRead` (DRY) with one page of variants.

`app/storage/files.py`:

```python
"""File storage behind one Protocol: S3 in the running app, a dict in tests."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from functools import partial
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import Settings
from app.core.exceptions import FileStorageError
from app.db.unit_of_work import AfterCommit

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client  # type stubs are a dev dependency
    from mypy_boto3_s3.type_defs import ObjectIdentifierTypeDef

logger = logging.getLogger(__name__)


def project_prefix(project_id: UUID) -> str:
    return f"projects/{project_id}/"


def object_key(project_id: UUID, kind: str, file_id: UUID, extension: str) -> str:
    """Server-built key; the client filename never becomes part of it."""
    return f"{project_prefix(project_id)}{kind}/{file_id}{extension}"


class FileStorage(Protocol):
    async def put(self, key: str, data: bytes) -> None: ...
    async def delete(self, key: str) -> None: ...
    async def delete_prefix(self, prefix: str) -> None: ...


class S3FileStorage:
    """boto3 is blocking, so every call runs in a worker thread (boto3 clients are thread-safe)."""

    def __init__(self, client: S3Client, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    async def put(self, key: str, data: bytes) -> None:
        await asyncio.to_thread(self._client.put_object, Bucket=self._bucket, Key=key, Body=data)
        logger.debug("Stored object key=%s bytes=%d", key, len(data))

    async def delete(self, key: str) -> None:
        try:
            await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)
        except (BotoCoreError, ClientError) as exc:
            raise FileStorageError(f"S3 could not delete key={key}") from exc
        logger.debug("Deleted object key=%s", key)

    async def delete_prefix(self, prefix: str) -> None:
        try:
            count = await asyncio.to_thread(self._delete_prefix, prefix)
        except (BotoCoreError, ClientError) as exc:
            raise FileStorageError(f"S3 could not delete prefix={prefix}") from exc
        logger.debug("Deleted %d objects under prefix=%s", count, prefix)

    def _delete_prefix(self, prefix: str) -> int:
        # list_objects_v2 returns at most 1000 keys per page, the delete_objects limit.
        count = 0
        for page in self._client.get_paginator("list_objects_v2").paginate(
            Bucket=self._bucket, Prefix=prefix
        ):
            keys: list[ObjectIdentifierTypeDef] = [
                {"Key": obj["Key"]} for obj in page.get("Contents", []) if "Key" in obj
            ]
            if not keys:
                continue
            response = self._client.delete_objects(Bucket=self._bucket, Delete={"Objects": keys})
            if errors := response.get("Errors"):  # partial failure is HTTP 200, not an exception
                raise FileStorageError(f"S3 could not delete {len(errors)} objects")
            count += len(keys)
        return count


class InMemoryFileStorage:
    """Dict keyed by object key: O(1) put and delete."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes) -> None:
        self.objects[key] = data

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    async def delete_prefix(self, prefix: str) -> None:
        for key in [key for key in self.objects if key.startswith(prefix)]:
            del self.objects[key]


class DeleteAfterCommitStorage:
    """Decorator: writes happen at once, deletes wait until the database commit has succeeded.

    If the commit fails, the rows come back and their files are still there. If a delete fails
    after the commit, the object is orphaned (no row points to it): logged, not raised, because
    the client's delete has already succeeded.
    """

    def __init__(self, storage: FileStorage, after_commit: AfterCommit) -> None:
        self._storage = storage
        self._after_commit = after_commit

    async def put(self, key: str, data: bytes) -> None:
        await self._storage.put(key, data)

    async def delete(self, key: str) -> None:
        self._after_commit.add(partial(self._run, self._storage.delete, key))

    async def delete_prefix(self, prefix: str) -> None:
        self._after_commit.add(partial(self._run, self._storage.delete_prefix, prefix))

    @staticmethod
    async def _run(delete: Callable[[str], Awaitable[None]], target: str) -> None:
        try:
            await delete(target)
        except FileStorageError as exc:
            logger.error("Orphaned file after commit: %s", exc)


def build_file_storage(settings: Settings) -> S3FileStorage:
    """Credentials come from the default AWS chain (env vars locally, the ECS task role on AWS)."""
    client = boto3.client(
        "s3", region_name=settings.aws_region, endpoint_url=settings.s3_endpoint_url
    )
    return S3FileStorage(client, settings.s3_bucket)
```

- Same pattern as the repositories: a `FileStorage` Protocol, a real implementation and an
  in-memory one. Services depend on the Protocol only (Dependency Inversion), so service and API
  tests run without S3.
- boto3 is synchronous. Calling it directly inside `async def` would block the event loop and
  stall every other request; `asyncio.to_thread` runs it in a worker thread.
- `mypy_boto3_s3` is imported under `TYPE_CHECKING` only, because the stubs are a dev dependency
  and are not installed in the Docker image. Python 3.14+ evaluates annotations lazily, so the
  annotation `S3Client` needs no quotes.
- `object_key` builds keys from ids only. A filename like `../../etc/passwd` stays plain text in
  the `filename` column and never touches a path.
- `S3FileStorage` turns boto3 errors into `FileStorageError`. `delete_objects` needs an extra
  check: when some keys cannot be deleted it still answers HTTP 200 and lists them under
  `Errors`, so ignoring the response would report success for objects that are still there.
- `DeleteAfterCommitStorage` is a Decorator: it has the `FileStorage` methods, passes `put`
  through and turns `delete` and `delete_prefix` into actions that run after the commit (below).
  Services do not know about it; `api/deps.py` wraps the real storage per request. A delete that
  fails after the commit is logged at ERROR and not raised: the client's delete has succeeded and
  only an orphaned object (no row points to it) is left.
- `build_file_storage` creates one client per process (step 10, lifespan). Creating a client does
  no network call; the first request does.

`app/db/unit_of_work.py`:

```python
"""Actions that must wait until the request transaction has committed."""

from collections.abc import Awaitable, Callable

type Action = Callable[[], Awaitable[None]]


class AfterCommit:
    """Collected during a request, run by get_session once the commit has succeeded."""

    def __init__(self) -> None:
        self._actions: list[Action] = []

    def add(self, action: Action) -> None:
        self._actions.append(action)

    async def run(self) -> None:
        for action in self._actions:
            await action()
        self._actions.clear()


def get_after_commit() -> AfterCommit:
    """FastAPI caches a dependency per request, so the session and the storage share one."""
    return AfterCommit()
```

`app/db/session.py`, run the actions once the transaction has committed:

```diff
@@ -2,11 +2,13 @@

 import logging
-from collections.abc import AsyncIterator
+from collections.abc import AsyncGenerator
 from contextlib import asynccontextmanager
+from typing import Annotated

-from fastapi import FastAPI, Request
+from fastapi import Depends, FastAPI, Request
 from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

 from app.core.config import Settings
+from app.db.unit_of_work import AfterCommit, get_after_commit

 logger = logging.getLogger(__name__)
@@ -14,5 +16,5 @@ logger = logging.getLogger(__name__)

 @asynccontextmanager
-async def database_lifespan(app: FastAPI, settings: Settings) -> AsyncIterator[None]:
+async def database_lifespan(app: FastAPI, settings: Settings) -> AsyncGenerator[None]:
     engine = create_async_engine(settings.database_url.get_secret_value(), pool_pre_ping=True)
     app.state.sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
@@ -25,7 +27,14 @@ async def database_lifespan(app: FastAPI, settings: Settings) -> AsyncIterator[N


-async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
-    """Unit of Work: commit if the request succeeds, roll back if anything raises."""
+async def get_session(
+    request: Request, after_commit: Annotated[AfterCommit, Depends(get_after_commit)]
+) -> AsyncGenerator[AsyncSession]:
+    """Unit of Work: commit if the request succeeds, roll back if anything raises.
+
+    Actions in after_commit (S3 deletes) run only after a successful commit.
+    """
     sessionmaker: async_sessionmaker[AsyncSession] = request.app.state.sessionmaker
-    async with sessionmaker() as session, session.begin():
-        yield session
+    async with sessionmaker() as session:
+        async with session.begin():
+            yield session
+        await after_commit.run()
```

- `session.begin()` commits when its block ends without an exception. Only then does
  `after_commit.run()` execute; if the request raised, the exception leaves `get_session` before
  that line and the actions are dropped with the rollback.
- `get_after_commit` returns a new `AfterCommit`, and FastAPI calls a dependency once per request
  and reuses the result, so `get_session` and `get_file_storage` receive the same instance.
- The session dependency uses `scope="function"` (week 1), so the commit and the S3 deletes both
  finish before the response is sent.

## Step 8. Repositories

`app/repositories/vcf_file.py`:

```python
"""Data access for VCF files and their variants (Repository pattern)."""

import logging
from collections.abc import Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from itertools import batched, count
from typing import Protocol
from uuid import UUID

from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import VariantModel, VcfFileModel
from app.parsers.vcf import ParsedVariant

logger = logging.getLogger(__name__)

INSERT_BATCH_SIZE = 5000


class VcfFileRepository(Protocol):
    async def add(
        self, vcf_file: VcfFileModel, variants: Sequence[ParsedVariant]
    ) -> VcfFileModel: ...
    async def list_for_project(self, project_id: UUID) -> list[VcfFileModel]: ...
    async def get(self, project_id: UUID, vcf_file_id: UUID) -> VcfFileModel | None: ...
    async def list_variants(
        self, vcf_file_id: UUID, limit: int, offset: int
    ) -> list[VariantModel]: ...
    async def delete(self, vcf_file: VcfFileModel) -> None: ...


class SqlAlchemyVcfFileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, vcf_file: VcfFileModel, variants: Sequence[ParsedVariant]) -> VcfFileModel:
        self._session.add(vcf_file)
        await self._session.flush()
        for batch in batched(variants, INSERT_BATCH_SIZE, strict=False):
            rows = [{"vcf_file_id": vcf_file.vcf_file_id, **asdict(v)} for v in batch]
            await self._session.execute(insert(VariantModel), rows)
            logger.debug("Inserted %d variant rows vcf_file_id=%s", len(rows), vcf_file.vcf_file_id)
        return vcf_file

    async def list_for_project(self, project_id: UUID) -> list[VcfFileModel]:
        result = await self._session.scalars(
            select(VcfFileModel)
            .where(VcfFileModel.project_id == project_id)
            .order_by(VcfFileModel.uploaded_at, VcfFileModel.vcf_file_id)
        )
        return list(result)

    async def get(self, project_id: UUID, vcf_file_id: UUID) -> VcfFileModel | None:
        return await self._session.scalar(
            select(VcfFileModel).where(
                VcfFileModel.vcf_file_id == vcf_file_id, VcfFileModel.project_id == project_id
            )
        )

    async def list_variants(self, vcf_file_id: UUID, limit: int, offset: int) -> list[VariantModel]:
        result = await self._session.scalars(
            select(VariantModel)
            .where(VariantModel.vcf_file_id == vcf_file_id)
            .order_by(VariantModel.variant_id)
            .limit(limit)
            .offset(offset)
        )
        return list(result)

    async def delete(self, vcf_file: VcfFileModel) -> None:
        await self._session.delete(vcf_file)  # variants go with it: ON DELETE CASCADE
        await self._session.flush()
        logger.debug("Deleted vcf_file row vcf_file_id=%s", vcf_file.vcf_file_id)


class InMemoryVcfFileRepository:
    """Files indexed by project then id, variants by file id: lookups and deletes are O(1)."""

    def __init__(self) -> None:
        self._files: dict[UUID, dict[UUID, VcfFileModel]] = {}
        self._variants: dict[UUID, list[VariantModel]] = {}
        self._variant_ids = count(1)

    async def add(self, vcf_file: VcfFileModel, variants: Sequence[ParsedVariant]) -> VcfFileModel:
        vcf_file.uploaded_at = datetime.now(UTC)
        self._files.setdefault(vcf_file.project_id, {})[vcf_file.vcf_file_id] = vcf_file
        self._variants[vcf_file.vcf_file_id] = [
            VariantModel(
                variant_id=next(self._variant_ids), vcf_file_id=vcf_file.vcf_file_id, **asdict(v)
            )
            for v in variants
        ]
        return vcf_file

    async def list_for_project(self, project_id: UUID) -> list[VcfFileModel]:
        return list(self._files.get(project_id, {}).values())

    async def get(self, project_id: UUID, vcf_file_id: UUID) -> VcfFileModel | None:
        return self._files.get(project_id, {}).get(vcf_file_id)

    async def list_variants(self, vcf_file_id: UUID, limit: int, offset: int) -> list[VariantModel]:
        return self._variants.get(vcf_file_id, [])[offset : offset + limit]

    async def delete(self, vcf_file: VcfFileModel) -> None:
        del self._files[vcf_file.project_id][vcf_file.vcf_file_id]
        del self._variants[vcf_file.vcf_file_id]
```

`app/repositories/annotation_file.py`:

```python
"""Data access for annotation files (Repository pattern)."""

import logging
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AnnotationFileModel

logger = logging.getLogger(__name__)


class AnnotationFileRepository(Protocol):
    async def add(self, annotation_file: AnnotationFileModel) -> AnnotationFileModel: ...
    async def list_for_project(self, project_id: UUID) -> list[AnnotationFileModel]: ...
    async def get(
        self, project_id: UUID, annotation_file_id: UUID
    ) -> AnnotationFileModel | None: ...
    async def delete(self, annotation_file: AnnotationFileModel) -> None: ...


class SqlAlchemyAnnotationFileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, annotation_file: AnnotationFileModel) -> AnnotationFileModel:
        self._session.add(annotation_file)
        await self._session.flush()
        logger.debug(
            "Inserted annotation_file row annotation_file_id=%s",
            annotation_file.annotation_file_id,
        )
        return annotation_file

    async def list_for_project(self, project_id: UUID) -> list[AnnotationFileModel]:
        result = await self._session.scalars(
            select(AnnotationFileModel)
            .where(AnnotationFileModel.project_id == project_id)
            .order_by(AnnotationFileModel.uploaded_at, AnnotationFileModel.annotation_file_id)
        )
        return list(result)

    async def get(self, project_id: UUID, annotation_file_id: UUID) -> AnnotationFileModel | None:
        return await self._session.scalar(
            select(AnnotationFileModel).where(
                AnnotationFileModel.annotation_file_id == annotation_file_id,
                AnnotationFileModel.project_id == project_id,
            )
        )

    async def delete(self, annotation_file: AnnotationFileModel) -> None:
        await self._session.delete(annotation_file)
        await self._session.flush()
        logger.debug(
            "Deleted annotation_file row annotation_file_id=%s",
            annotation_file.annotation_file_id,
        )


class InMemoryAnnotationFileRepository:
    """Files indexed by project then id: lookups and deletes are O(1)."""

    def __init__(self) -> None:
        self._files: dict[UUID, dict[UUID, AnnotationFileModel]] = {}

    async def add(self, annotation_file: AnnotationFileModel) -> AnnotationFileModel:
        annotation_file.uploaded_at = datetime.now(UTC)
        files = self._files.setdefault(annotation_file.project_id, {})
        files[annotation_file.annotation_file_id] = annotation_file
        return annotation_file

    async def list_for_project(self, project_id: UUID) -> list[AnnotationFileModel]:
        return list(self._files.get(project_id, {}).values())

    async def get(self, project_id: UUID, annotation_file_id: UUID) -> AnnotationFileModel | None:
        return self._files.get(project_id, {}).get(annotation_file_id)

    async def delete(self, annotation_file: AnnotationFileModel) -> None:
        del self._files[annotation_file.project_id][annotation_file.annotation_file_id]
```

- `get(project_id, file_id)` filters on both ids: a file id that belongs to another project is
  "not found" (404), so one project cannot read another project's files by guessing ids.
- Variants are inserted with `insert(VariantModel)` and a list of dicts, which SQLAlchemy sends as
  a few multi-row `INSERT` statements instead of one statement per row. Batches of 5000 bound
  the memory used for the parameter dicts. Variants are not added as ORM objects because
  tracking hundreds of thousands of objects in the session is slow and useless here.
- The in-memory repositories index files by project and then by id (dict of dicts), so `get`,
  `list_for_project` and `delete` never scan other projects. They assign `uploaded_at` and
  `variant_id` the way Postgres would.
- `list_variants` orders by `variant_id`, which is file order, so `limit` and `offset` pages are
  stable.

## Step 9. Services

`app/services/project.py`:

```python
"""Business rules for projects (Service Layer); storage is reached only through the repository"""

import logging
from uuid import UUID

from app.core.exceptions import ProjectNameConflictError, ProjectNotFoundError
from app.models import ProjectModel
from app.repositories.project import ProjectRepository
from app.schemas.project import ProjectCreate
from app.storage.files import FileStorage, project_prefix

logger = logging.getLogger(__name__)


async def require_project(projects: ProjectRepository, project_id: UUID) -> ProjectModel:
    """Shared by every service that works inside a project."""
    project = await projects.get(project_id)
    if project is None:
        logger.warning("Project not found project_id=%s", project_id)
        raise ProjectNotFoundError(project_id)
    return project


class ProjectService:
    def __init__(self, repository: ProjectRepository, storage: FileStorage) -> None:
        self._repository = repository
        self._storage = storage

    async def create_project(self, data: ProjectCreate) -> ProjectModel:
        try:
            project = await self._repository.add(data)
        except ProjectNameConflictError:
            logger.warning("Project not created: name already exists")
            raise
        logger.info("Project created project_id=%s", project.project_id)
        return project

    async def list_projects(self) -> list[ProjectModel]:
        return await self._repository.list_all()

    async def delete_project(self, project_id: UUID) -> None:
        """Rows cascade in the database; the files under the project prefix are removed here."""
        project = await require_project(self._repository, project_id)
        await self._repository.delete(project)
        await self._storage.delete_prefix(project_prefix(project_id))
        logger.info("Project deleted project_id=%s", project_id)
```

- `require_project` is shared by all three services (DRY): one place checks "project exists",
  logs the WARNING and raises `ProjectNotFoundError`.
- `delete_project` now also deletes the project's S3 objects. The cascade only covers database
  rows; without this, every deleted project would leave its files in S3 forever.

`app/services/vcf_file.py`:

```python
"""VCF use cases: validate, parse, store the file and its variants, list, read, delete."""

import asyncio
import logging
from uuid import UUID, uuid4

from app.core.exceptions import InvalidFileFormatError, InvalidFilenameError, VcfFileNotFoundError
from app.models import VariantModel, VcfFileModel
from app.parsers.text import decode_lines, file_extension
from app.parsers.vcf import ParsedVcf, parse_vcf
from app.repositories.project import ProjectRepository
from app.repositories.vcf_file import VcfFileRepository
from app.services.project import require_project
from app.storage.files import FileStorage, object_key

logger = logging.getLogger(__name__)

VCF_EXTENSIONS = (".vcf.gz", ".vcf")


def _parse(data: bytes, extension: str, max_bytes: int) -> ParsedVcf:
    """CPU-bound, so it runs in a worker thread and the event loop keeps serving requests."""
    return parse_vcf(decode_lines(data, extension.endswith(".gz"), max_bytes))


class VcfFileService:
    def __init__(
        self,
        projects: ProjectRepository,
        vcf_files: VcfFileRepository,
        storage: FileStorage,
        max_bytes: int,
    ) -> None:
        self._projects = projects
        self._vcf_files = vcf_files
        self._storage = storage
        self._max_bytes = max_bytes

    async def upload(self, project_id: UUID, filename: str, data: bytes) -> VcfFileModel:
        """Rows are flushed before the file is written, so an S3 failure rolls the rows back.

        A failed commit after a successful write leaves an orphaned object; it is harmless (no row
        points to it) and cheaper to accept than a two-phase commit.
        """
        await require_project(self._projects, project_id)
        try:
            extension = file_extension(filename, VCF_EXTENSIONS)
            parsed = await asyncio.to_thread(_parse, data, extension, self._max_bytes)
        except InvalidFilenameError:
            logger.warning("VCF upload rejected: bad filename project_id=%s", project_id)
            raise
        except InvalidFileFormatError as exc:
            logger.warning(
                "VCF upload rejected: project_id=%s line=%s reason=%s",
                project_id,
                exc.line_no,
                exc.reason,
            )
            raise
        vcf_file_id = uuid4()
        vcf_file = VcfFileModel(
            vcf_file_id=vcf_file_id,
            project_id=project_id,
            filename=filename,
            s3_key=object_key(project_id, "vcf", vcf_file_id, extension),
            sample_count=parsed.sample_count,
            variant_count=len(parsed.variants),
        )
        await self._vcf_files.add(vcf_file, parsed.variants)
        await self._storage.put(vcf_file.s3_key, data)
        logger.info(
            "VCF file uploaded vcf_file_id=%s project_id=%s variants=%d samples=%d bytes=%d",
            vcf_file_id,
            project_id,
            vcf_file.variant_count,
            vcf_file.sample_count,
            len(data),
        )
        return vcf_file

    async def list_vcf_files(self, project_id: UUID) -> list[VcfFileModel]:
        await require_project(self._projects, project_id)
        return await self._vcf_files.list_for_project(project_id)

    async def get_vcf_file(
        self, project_id: UUID, vcf_file_id: UUID, limit: int, offset: int
    ) -> tuple[VcfFileModel, list[VariantModel]]:
        vcf_file = await self._require_vcf_file(project_id, vcf_file_id)
        variants = await self._vcf_files.list_variants(vcf_file_id, limit, offset)
        return vcf_file, variants

    async def delete_vcf_file(self, project_id: UUID, vcf_file_id: UUID) -> None:
        vcf_file = await self._require_vcf_file(project_id, vcf_file_id)
        await self._vcf_files.delete(vcf_file)
        await self._storage.delete(vcf_file.s3_key)
        logger.info("VCF file deleted vcf_file_id=%s project_id=%s", vcf_file_id, project_id)

    async def _require_vcf_file(self, project_id: UUID, vcf_file_id: UUID) -> VcfFileModel:
        await require_project(self._projects, project_id)
        vcf_file = await self._vcf_files.get(project_id, vcf_file_id)
        if vcf_file is None:
            logger.warning(
                "VCF file not found vcf_file_id=%s project_id=%s", vcf_file_id, project_id
            )
            raise VcfFileNotFoundError(vcf_file_id)
        return vcf_file
```

`app/services/annotation_file.py`:

```python
"""ClinVar annotation file use cases: validate, count entries, store, list, delete."""

import asyncio
import logging
from uuid import UUID, uuid4

from app.core.exceptions import (
    AnnotationFileNotFoundError,
    InvalidFileFormatError,
    InvalidFilenameError,
)
from app.models import AnnotationFileModel
from app.parsers.clinvar import ClinVarSummary, parse_clinvar
from app.parsers.text import decode_lines, file_extension
from app.repositories.annotation_file import AnnotationFileRepository
from app.repositories.project import ProjectRepository
from app.services.project import require_project
from app.storage.files import FileStorage, object_key

logger = logging.getLogger(__name__)

ANNOTATION_EXTENSIONS = (".txt.gz", ".tsv.gz", ".txt", ".tsv")


def _parse(data: bytes, extension: str, max_bytes: int) -> ClinVarSummary:
    """CPU-bound, so it runs in a worker thread and the event loop keeps serving requests."""
    return parse_clinvar(decode_lines(data, extension.endswith(".gz"), max_bytes))


class AnnotationFileService:
    def __init__(
        self,
        projects: ProjectRepository,
        annotation_files: AnnotationFileRepository,
        storage: FileStorage,
        max_bytes: int,
    ) -> None:
        self._projects = projects
        self._annotation_files = annotation_files
        self._storage = storage
        self._max_bytes = max_bytes

    async def upload(self, project_id: UUID, filename: str, data: bytes) -> AnnotationFileModel:
        """Same order and consistency rules as VcfFileService.upload."""
        await require_project(self._projects, project_id)
        try:
            extension = file_extension(filename, ANNOTATION_EXTENSIONS)
            summary = await asyncio.to_thread(_parse, data, extension, self._max_bytes)
        except InvalidFilenameError:
            logger.warning("Annotation upload rejected: bad filename project_id=%s", project_id)
            raise
        except InvalidFileFormatError as exc:
            logger.warning(
                "Annotation upload rejected: project_id=%s line=%s reason=%s",
                project_id,
                exc.line_no,
                exc.reason,
            )
            raise
        if summary.invalid_count:
            logger.warning(
                "Annotation file has %d invalid entries project_id=%s",
                summary.invalid_count,
                project_id,
            )
        annotation_file_id = uuid4()
        annotation_file = AnnotationFileModel(
            annotation_file_id=annotation_file_id,
            project_id=project_id,
            filename=filename,
            s3_key=object_key(project_id, "annotation", annotation_file_id, extension),
            column_format=summary.column_format,
            entry_count=summary.entry_count,
        )
        await self._annotation_files.add(annotation_file)
        await self._storage.put(annotation_file.s3_key, data)
        logger.info(
            "Annotation file uploaded annotation_file_id=%s project_id=%s format=%s entries=%d",
            annotation_file_id,
            project_id,
            summary.column_format,
            summary.entry_count,
        )
        return annotation_file

    async def list_annotation_files(self, project_id: UUID) -> list[AnnotationFileModel]:
        await require_project(self._projects, project_id)
        return await self._annotation_files.list_for_project(project_id)

    async def delete_annotation_file(self, project_id: UUID, annotation_file_id: UUID) -> None:
        await require_project(self._projects, project_id)
        annotation_file = await self._annotation_files.get(project_id, annotation_file_id)
        if annotation_file is None:
            logger.warning(
                "Annotation file not found annotation_file_id=%s project_id=%s",
                annotation_file_id,
                project_id,
            )
            raise AnnotationFileNotFoundError(annotation_file_id)
        await self._annotation_files.delete(annotation_file)
        await self._storage.delete(annotation_file.s3_key)
        logger.info(
            "Annotation file deleted annotation_file_id=%s project_id=%s",
            annotation_file_id,
            project_id,
        )
```

The upload use case, in order:

| # | Step | On failure |
|---|---|---|
| 1 | Project exists | `ProjectNotFoundError`, 404 |
| 2 | Filename has an allowed extension | `InvalidFilenameError`, 422 |
| 3 | Decode (gunzip, UTF-8) and parse | `InvalidFileFormatError` with line number, 422 |
| 4 | Insert metadata and variants (flush, not yet committed) | database error, 500, rolled back |
| 5 | Write the raw file to S3 | S3 error, 500, step 4 rolled back |
| 6 | Commit when the request ends (`get_session`) | 500; the S3 object is orphaned but harmless |

Step 3 runs in a worker thread (`asyncio.to_thread(_parse, ...)`): unzipping and parsing a 50 MB
file is CPU work that would otherwise block the event loop for seconds. With the GIL the thread
does not make parsing faster, but Python switches threads every few milliseconds, so the loop
keeps answering other requests and `/health`.

Deletes are the other way round: the rows are deleted (flushed) at once, the S3 objects only
after the commit, through `DeleteAfterCommitStorage` (step 7). If the commit fails, rows and files
both survive, so the database never points at a missing file.

Logging, as set up in week 1:

| Level | Example | Never |
|---|---|---|
| INFO | `VCF file uploaded vcf_file_id=... project_id=... variants=3 samples=0 bytes=137` | file content, filenames |
| WARNING | `VCF upload rejected: project_id=... line=4 reason=POS must be a positive integer` | the line itself |
| DEBUG | `Inserted 5000 variant rows vcf_file_id=...`, `Stored object key=... bytes=...` | |
| ERROR | the request log line of a 500 (for example S3 unreachable) | credentials |

`reason` is one of the parser's fixed messages, never text from the file. Filenames are not logged
either: users name files after patients or samples.

## Step 10. Routes, uploads and dependency injection

`app/api/uploads.py`:

```python
"""Upload size limits: an early check on the request header and an exact one on the file."""

from collections.abc import Awaitable, Callable

from fastapi import HTTPException, Request, Response, UploadFile, status
from fastapi.responses import JSONResponse

from app.core.config import Settings

MULTIPART_OVERHEAD_BYTES = 64 * 1024  # boundaries and part headers around the file


def too_large_detail(max_bytes: int) -> str:
    return f"File is larger than {max_bytes} bytes"


async def reject_oversized_requests(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    """Refuse a body announced as too large before Starlette spools it to disk."""
    settings: Settings = request.app.state.settings
    content_length = request.headers.get("content-length", "")
    limit = settings.max_upload_bytes + MULTIPART_OVERHEAD_BYTES
    if content_length.isdigit() and int(content_length) > limit:
        return JSONResponse(
            {"detail": too_large_detail(settings.max_upload_bytes)},
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        )
    return await call_next(request)


async def read_upload(file: UploadFile, max_bytes: int) -> bytes:
    """Exact check on the file itself; also covers bodies sent without Content-Length."""
    data = await file.read(max_bytes + 1)  # one byte more than allowed is enough to know
    if len(data) > max_bytes:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, detail=too_large_detail(max_bytes))
    return data
```

Two checks, both in the API layer because a status code is an HTTP concern:
- `reject_oversized_requests` is a middleware. Starlette parses a multipart body, and writes the
  file to a temporary file, before the route function runs, so a check inside the route comes too
  late to protect the disk. The middleware answers 413 from the `Content-Length` header alone,
  before the body is read. It allows 64 KB on top of the limit for the multipart framing.
- `read_upload` is the exact check on the file itself. It also covers clients that send the body
  in chunks without `Content-Length`. Reading `max_bytes + 1` bytes is enough to know a file is
  too large without reading all of it.

`app/api/deps.py`:

```python
"""Dependency Injection wiring: the only place that picks concrete implementations."""

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.session import get_session
from app.db.unit_of_work import AfterCommit, get_after_commit
from app.repositories.annotation_file import SqlAlchemyAnnotationFileRepository
from app.repositories.project import SqlAlchemyProjectRepository
from app.repositories.vcf_file import SqlAlchemyVcfFileRepository
from app.services.annotation_file import AnnotationFileService
from app.services.project import ProjectService
from app.services.vcf_file import VcfFileService
from app.storage.files import DeleteAfterCommitStorage, FileStorage

SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]


def get_file_storage(
    request: Request, after_commit: Annotated[AfterCommit, Depends(get_after_commit)]
) -> FileStorage:
    storage: FileStorage = request.app.state.file_storage
    return DeleteAfterCommitStorage(storage, after_commit)


FileStorageDep = Annotated[FileStorage, Depends(get_file_storage)]


def get_max_upload_bytes(request: Request) -> int:
    settings: Settings = request.app.state.settings
    return settings.max_upload_bytes


MaxUploadBytesDep = Annotated[int, Depends(get_max_upload_bytes)]


def get_project_service(session: SessionDep, storage: FileStorageDep) -> ProjectService:
    return ProjectService(SqlAlchemyProjectRepository(session), storage)


def get_vcf_file_service(
    session: SessionDep, storage: FileStorageDep, max_bytes: MaxUploadBytesDep
) -> VcfFileService:
    return VcfFileService(
        SqlAlchemyProjectRepository(session),
        SqlAlchemyVcfFileRepository(session),
        storage,
        max_bytes,
    )


def get_annotation_file_service(
    session: SessionDep, storage: FileStorageDep, max_bytes: MaxUploadBytesDep
) -> AnnotationFileService:
    return AnnotationFileService(
        SqlAlchemyProjectRepository(session),
        SqlAlchemyAnnotationFileRepository(session),
        storage,
        max_bytes,
    )


ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]
VcfFileServiceDep = Annotated[VcfFileService, Depends(get_vcf_file_service)]
AnnotationFileServiceDep = Annotated[AnnotationFileService, Depends(get_annotation_file_service)]
```

`app/api/v1/routes/vcf_files.py`:

```python
"""/projects/{project_id}/vcf resource: thin async handlers, HTTP concerns only."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response, UploadFile, status

from app.api.deps import MaxUploadBytesDep, VcfFileServiceDep
from app.api.uploads import read_upload
from app.core.exceptions import (
    InvalidFileFormatError,
    InvalidFilenameError,
    ProjectNotFoundError,
    VcfFileNotFoundError,
)
from app.schemas.vcf_file import VariantRead, VcfFileDetail, VcfFileRead

router = APIRouter(prefix="/projects/{project_id}/vcf", tags=["vcf files"])


@router.post("/", response_model=VcfFileRead, status_code=status.HTTP_201_CREATED)
async def upload_vcf_file(
    project_id: UUID,
    file: UploadFile,
    service: VcfFileServiceDep,
    max_bytes: MaxUploadBytesDep,
    request: Request,
    response: Response,
) -> VcfFileRead:
    data = await read_upload(file, max_bytes)
    try:
        vcf_file = await service.upload(project_id, file.filename or "", data)
    except ProjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
    except (InvalidFilenameError, InvalidFileFormatError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from None
    response.headers["Location"] = str(
        request.url_for("get_vcf_file", project_id=project_id, vcf_id=vcf_file.vcf_file_id)
    )
    return VcfFileRead.model_validate(vcf_file)


@router.get("/", response_model=list[VcfFileRead])
async def list_vcf_files(project_id: UUID, service: VcfFileServiceDep) -> list[VcfFileRead]:
    try:
        vcf_files = await service.list_vcf_files(project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
    return [VcfFileRead.model_validate(vcf_file) for vcf_file in vcf_files]


@router.get("/{vcf_id}", response_model=VcfFileDetail)
async def get_vcf_file(
    project_id: UUID,
    vcf_id: UUID,
    service: VcfFileServiceDep,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> VcfFileDetail:
    try:
        vcf_file, variants = await service.get_vcf_file(project_id, vcf_id, limit, offset)
    except (ProjectNotFoundError, VcfFileNotFoundError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
    return VcfFileDetail(
        **VcfFileRead.model_validate(vcf_file).model_dump(),
        variants=[VariantRead.model_validate(variant) for variant in variants],
    )


@router.delete("/{vcf_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vcf_file(project_id: UUID, vcf_id: UUID, service: VcfFileServiceDep) -> None:
    try:
        await service.delete_vcf_file(project_id, vcf_id)
    except (ProjectNotFoundError, VcfFileNotFoundError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
```

`app/api/v1/routes/annotation_files.py`:

```python
"""/projects/{project_id}/annotation resource: thin async handlers, HTTP concerns only."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, UploadFile, status

from app.api.deps import AnnotationFileServiceDep, MaxUploadBytesDep
from app.api.uploads import read_upload
from app.core.exceptions import (
    AnnotationFileNotFoundError,
    InvalidFileFormatError,
    InvalidFilenameError,
    ProjectNotFoundError,
)
from app.schemas.annotation_file import AnnotationFileRead

router = APIRouter(prefix="/projects/{project_id}/annotation", tags=["annotation files"])


@router.post("/", response_model=AnnotationFileRead, status_code=status.HTTP_201_CREATED)
async def upload_annotation_file(
    project_id: UUID,
    file: UploadFile,
    service: AnnotationFileServiceDep,
    max_bytes: MaxUploadBytesDep,
) -> AnnotationFileRead:
    data = await read_upload(file, max_bytes)
    try:
        annotation_file = await service.upload(project_id, file.filename or "", data)
    except ProjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
    except (InvalidFilenameError, InvalidFileFormatError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from None
    return AnnotationFileRead.model_validate(annotation_file)


@router.get("/", response_model=list[AnnotationFileRead])
async def list_annotation_files(
    project_id: UUID, service: AnnotationFileServiceDep
) -> list[AnnotationFileRead]:
    try:
        annotation_files = await service.list_annotation_files(project_id)
    except ProjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
    return [AnnotationFileRead.model_validate(item) for item in annotation_files]


@router.delete("/{annotation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_annotation_file(
    project_id: UUID, annotation_id: UUID, service: AnnotationFileServiceDep
) -> None:
    try:
        await service.delete_annotation_file(project_id, annotation_id)
    except (ProjectNotFoundError, AnnotationFileNotFoundError) as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from None
```

`app/api/v1/router.py`:

```python
"""Version prefix: every v1 resource router is mounted here."""

from fastapi import APIRouter

from app.api.v1.routes import annotation_files, projects, vcf_files

router = APIRouter(prefix="/api/v1")
router.include_router(projects.router)
router.include_router(vcf_files.router)
router.include_router(annotation_files.router)
```

`app/main.py`, build the S3 storage once at startup and register the size check:

```diff
@@ -1,17 +1,20 @@
-from collections.abc import AsyncIterator
+from collections.abc import AsyncGenerator
 from contextlib import asynccontextmanager

 from fastapi import FastAPI

+from app.api.uploads import reject_oversized_requests
 from app.api.v1.router import router as v1_router
 from app.core.config import Settings, get_settings
 from app.core.logging import configure_logging, log_requests
 from app.db.session import database_lifespan
+from app.storage.files import build_file_storage


 @asynccontextmanager
-async def lifespan(app: FastAPI) -> AsyncIterator[None]:
+async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
     settings: Settings = app.state.settings
     configure_logging(settings.log_level)
+    app.state.file_storage = build_file_storage(settings)
     async with database_lifespan(app, settings):
         yield
@@ -21,5 +24,6 @@ def create_app(settings: Settings | None = None) -> FastAPI:
     app = FastAPI(title="Genomic Variant Analysis API", version="0.1.0", lifespan=lifespan)
     app.state.settings = settings or get_settings()
-    app.middleware("http")(log_requests)
+    app.middleware("http")(reject_oversized_requests)
+    app.middleware("http")(log_requests)  # added last, runs first: logs every response
     app.include_router(v1_router)
```

| Method | Path | Success | Errors |
|---|---|---|---|
| POST | `/api/v1/projects/{project_id}/vcf/` (multipart field `file`) | 201 `VcfFileRead` + `Location` | 404 project, 413 too large, 422 bad name or content |
| GET | `/api/v1/projects/{project_id}/vcf/` | 200 `list[VcfFileRead]` | 404 project |
| GET | `/api/v1/projects/{project_id}/vcf/{vcf_id}?limit=100&offset=0` | 200 `VcfFileDetail` | 404, 422 bad UUID or paging |
| DELETE | `/api/v1/projects/{project_id}/vcf/{vcf_id}` | 204 | 404 |
| POST | `/api/v1/projects/{project_id}/annotation/` (multipart field `file`) | 201 `AnnotationFileRead` | 404, 413, 422 |
| GET | `/api/v1/projects/{project_id}/annotation/` | 200 `list[AnnotationFileRead]` | 404 |
| DELETE | `/api/v1/projects/{project_id}/annotation/{annotation_id}` | 204 | 404 |

- Paths are exactly as the task specifies: collection paths end with a slash, item paths do not.
- `UploadFile` makes FastAPI read the `file` field of a `multipart/form-data` body; a request
  without it is a 422 before our code runs.
- The upload sets `Location` to the URL of the new resource (REST convention for 201), built with
  `request.url_for` from the name of the GET route, so the two cannot drift apart.
- `limit` is between 1 and 1000: a VCF can hold millions of variants, and one response must not.
- `ProjectNotFoundError` and the file-not-found errors both map to 404: from the client's view
  the resource at that path does not exist either way. The `detail` says which one.

## Step 11. Docker Compose: local S3

`docker-compose.yml`:

```diff
@@ -3,4 +3,5 @@
 # Dev database only: docker compose up -d db       (run API locally with Poetry)
 # Test database:     docker compose up -d test_db  (needed by integration tests)
+# Local S3:          s3 (moto server, objects in memory) on :9000; s3-init creates the bucket
 # Local development creds only; real env inject DATABASE_URL from a secret store.
 x-api: &api
@@ -10,4 +11,11 @@ x-api: &api
     DATABASE_URL: postgresql+asyncpg://app:app@db:5432/gva
     LOG_LEVEL: ${LOG_LEVEL:-INFO}
+    S3_BUCKET: ${S3_BUCKET:-gva-files}
+    S3_ENDPOINT_URL: http://s3:5000
+
+# Fake keys for the local moto S3 only; on AWS the ECS task role provides credentials.
+x-local-s3-credentials: &local-s3-credentials
+  AWS_ACCESS_KEY_ID: local
+  AWS_SECRET_ACCESS_KEY: local

 services:
@@ -45,4 +53,24 @@ services:
       retries: 5

+  s3:
+    image: motoserver/moto:5.2.6
+    ports:
+      - '127.0.0.1:9000:5000'
+    healthcheck:
+      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/moto-api/')"]
+      interval: 5s
+      timeout: 5s
+      retries: 5
+
+  s3-init:
+    image: motoserver/moto:5.2.6
+    environment:
+      <<: *local-s3-credentials
+      S3_BUCKET: ${S3_BUCKET:-gva-files}
+    entrypoint: ["python", "-c", "import boto3, os; boto3.client('s3', endpoint_url='http://s3:5000', region_name='us-east-1').create_bucket(Bucket=os.environ['S3_BUCKET'])"]
+    depends_on:
+      s3:
+        condition: service_healthy
+
   migrate:
     <<: *api
@@ -54,4 +82,10 @@ services:
   api:
     <<: *api
+    environment:
+      DATABASE_URL: postgresql+asyncpg://app:app@db:5432/gva
+      LOG_LEVEL: ${LOG_LEVEL:-INFO}
+      S3_BUCKET: ${S3_BUCKET:-gva-files}
+      S3_ENDPOINT_URL: http://s3:5000
+      <<: *local-s3-credentials
     ports:
       - '127.0.0.1:8000:8000'
@@ -59,4 +93,6 @@ services:
       migrate:
         condition: service_completed_successfully
+      s3-init:
+        condition: service_completed_successfully
     develop:
       watch:
```

- `s3` runs moto in server mode on port 5000 (published on 127.0.0.1:9000). It keeps objects in
  memory: they are gone after `docker compose down`, while Postgres keeps its rows in a volume.
  Deleting such a file later still works, because an S3 delete of a missing key succeeds.
- `s3-init` is a one-off container that creates the bucket, like `migrate` for the schema; `api`
  waits until both have exited successfully.
- `x-local-s3-credentials` holds fake keys (moto accepts any) and is merged only into `api` and
  `s3-init`; `migrate` never talks to S3 and does not get them. On AWS no keys exist at all: the
  ECS task role provides temporary credentials.

Start the full stack and try it (sample files are in step 12, `tests/samples.py`, or use your own):

```bash
docker compose up --build -d --wait api
P=$(curl -s -X POST http://127.0.0.1:8000/api/v1/projects/ -H 'content-type: application/json' \
  -d '{"name": "BRCA cohort", "lead_scientist": "Rosalind Franklin"}' | python3 -c 'import json,sys; print(json.load(sys.stdin)["project_id"])')
curl -s -i -F file=@calls.vcf.gz http://127.0.0.1:8000/api/v1/projects/$P/vcf/   # 201 + Location
curl -s "http://127.0.0.1:8000/api/v1/projects/$P/vcf/"
curl -s -F file=@variant_summary.txt http://127.0.0.1:8000/api/v1/projects/$P/annotation/
curl -s "http://127.0.0.1:9000/gva-files?list-type=2"     # the objects in local S3
curl -s -o /dev/null -w "%{http_code}\n" -X DELETE http://127.0.0.1:8000/api/v1/projects/$P/  # 204
docker compose logs api
docker compose down
```

To run the API with Poetry instead, start only the services it needs. `--env-file .env` loads the
whole `.env` into the process environment, which is where boto3 looks for credentials:

```bash
docker compose up -d db s3-init
poetry run alembic upgrade head
poetry run uvicorn app.main:create_app --factory --reload --env-file .env
```

## Step 12. Tests

| Folder | New this week | Storage |
|---|---|---|
| `tests/unit/` | parsers, services, in-memory repositories, S3 storage against moto | in memory, moto in process |
| `tests/api/` | every endpoint and status code over HTTP | in-memory services |
| `tests/integration/` | SQL repositories (batched insert, jsonb, cascades), full upload lifecycle | Postgres `test_db`, S3 in memory |

Test inputs are built in code (`tests/samples.py`), never binary fixture files: each test shows
the data it relies on, and gzip input is made with `gzip.compress` (Repeatable, Self-validating).

`tests/samples.py`:

```python
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
```

`tests/conftest.py` now provides in-memory storage, repositories and the three services:

```python
"""Shared fixtures: settings that never read .env, in-memory storage and services per test."""

import os

import pytest

from app.core.config import Settings
from app.repositories.annotation_file import InMemoryAnnotationFileRepository
from app.repositories.project import InMemoryProjectRepository
from app.repositories.vcf_file import InMemoryVcfFileRepository
from app.services.annotation_file import AnnotationFileService
from app.services.project import ProjectService
from app.services.vcf_file import VcfFileService
from app.storage.files import InMemoryFileStorage

MAX_BYTES = 1024 * 1024
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://app:app@localhost:5433/gva_test"
)


@pytest.fixture(scope="session")
def settings() -> Settings:
    return Settings(_env_file=None, database_url=TEST_DATABASE_URL)  # pyright: ignore[reportCallIssue]


@pytest.fixture
def repository() -> InMemoryProjectRepository:
    return InMemoryProjectRepository()


@pytest.fixture
def storage() -> InMemoryFileStorage:
    return InMemoryFileStorage()


@pytest.fixture
def vcf_repository() -> InMemoryVcfFileRepository:
    return InMemoryVcfFileRepository()


@pytest.fixture
def annotation_repository() -> InMemoryAnnotationFileRepository:
    return InMemoryAnnotationFileRepository()


@pytest.fixture
def service(repository: InMemoryProjectRepository, storage: InMemoryFileStorage) -> ProjectService:
    return ProjectService(repository, storage)


@pytest.fixture
def vcf_service(
    repository: InMemoryProjectRepository,
    vcf_repository: InMemoryVcfFileRepository,
    storage: InMemoryFileStorage,
) -> VcfFileService:
    return VcfFileService(repository, vcf_repository, storage, MAX_BYTES)


@pytest.fixture
def annotation_service(
    repository: InMemoryProjectRepository,
    annotation_repository: InMemoryAnnotationFileRepository,
    storage: InMemoryFileStorage,
) -> AnnotationFileService:
    return AnnotationFileService(repository, annotation_repository, storage, MAX_BYTES)
```

### Unit tests

`tests/unit/test_text_parser.py`:

```python
import gzip

import pytest

from app.core.exceptions import InvalidFileFormatError, InvalidFilenameError
from app.parsers.text import decode_lines, file_extension

VCF_EXTENSIONS = (".vcf.gz", ".vcf")


@pytest.mark.parametrize(
    ("filename", "expected"),
    [("calls.vcf", ".vcf"), ("calls.vcf.gz", ".vcf.gz"), ("CALLS.VCF.GZ", ".vcf.gz")],
)
def test_file_extension_accepts_allowed(filename: str, expected: str) -> None:
    assert file_extension(filename, VCF_EXTENSIONS) == expected


@pytest.mark.parametrize("filename", ["calls.txt", "calls.vcf.zip", "", "x" * 252 + ".vcf"])
def test_file_extension_rejects_others(filename: str) -> None:
    with pytest.raises(InvalidFilenameError):
        file_extension(filename, VCF_EXTENSIONS)


LIMIT = 1024


def test_decode_lines_plain_text() -> None:
    assert decode_lines(b"a\nb\r\n", False, LIMIT) == ["a", "b"]


def test_decode_lines_gzip() -> None:
    assert decode_lines(gzip.compress(b"a\nb\n"), True, LIMIT) == ["a", "b"]


def test_decode_lines_reads_every_gzip_member() -> None:
    data = gzip.compress(b"a\n") + gzip.compress(b"b\n")  # how bgzip writes files

    assert decode_lines(data, True, LIMIT) == ["a", "b"]


def test_decode_lines_stops_at_decompressed_limit() -> None:
    bomb = gzip.compress(b"A" * (LIMIT + 1))

    with pytest.raises(InvalidFileFormatError, match="larger than"):
        decode_lines(bomb, True, LIMIT)


@pytest.mark.parametrize(
    ("data", "gzipped"),
    [
        (b"plain text", True),
        (b"\x1f\x8bnot really gzip", True),
        (gzip.compress(b"a\nb\n")[:-4], True),
        (b"\xff\xfe", False),
        (b"a\x00b", False),
    ],
)
def test_decode_lines_rejects_bad_bytes(data: bytes, gzipped: bool) -> None:
    with pytest.raises(InvalidFileFormatError):
        decode_lines(data, gzipped, LIMIT)


def test_decode_lines_drops_byte_order_mark() -> None:
    assert decode_lines(b"\xef\xbb\xbfa\n", False, LIMIT) == ["a"]
```

`tests/unit/test_vcf_parser.py`:

```python
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
```

`tests/unit/test_clinvar_parser.py`:

```python
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
```

`tests/unit/test_vcf_file_service.py`:

```python
import gzip
import logging
import threading
from uuid import UUID, uuid4

import pytest

from app.core.exceptions import (
    InvalidFileFormatError,
    InvalidFilenameError,
    ProjectNotFoundError,
    VcfFileNotFoundError,
)
from app.parsers.vcf import ParsedVcf, parse_vcf
from app.repositories.project import InMemoryProjectRepository
from app.schemas.project import ProjectCreate
from app.services.vcf_file import VcfFileService
from app.storage.files import InMemoryFileStorage
from tests.samples import sample_vcf


@pytest.fixture
async def project_id(repository: InMemoryProjectRepository) -> UUID:
    project = await repository.add(ProjectCreate(name="BRCA", lead_scientist="R. Franklin"))
    return project.project_id


async def test_upload_stores_metadata_variants_and_file(
    vcf_service: VcfFileService, storage: InMemoryFileStorage, project_id: UUID
) -> None:
    vcf_file = await vcf_service.upload(project_id, "calls.vcf", sample_vcf())

    _, variants = await vcf_service.get_vcf_file(project_id, vcf_file.vcf_file_id, 100, 0)
    assert (vcf_file.filename, vcf_file.variant_count, vcf_file.sample_count) == ("calls.vcf", 3, 0)
    assert [v.af for v in variants] == [0.25, 0.1, 0.2]
    assert storage.objects == {vcf_file.s3_key: sample_vcf()}


async def test_upload_key_is_built_by_server(vcf_service: VcfFileService, project_id: UUID) -> None:
    vcf_file = await vcf_service.upload(project_id, "../../etc/calls.vcf", sample_vcf())

    assert vcf_file.s3_key == f"projects/{project_id}/vcf/{vcf_file.vcf_file_id}.vcf"


async def test_upload_gzip(vcf_service: VcfFileService, project_id: UUID) -> None:
    vcf_file = await vcf_service.upload(project_id, "calls.vcf.gz", gzip.compress(sample_vcf()))

    assert vcf_file.variant_count == 3
    assert vcf_file.s3_key.endswith(".vcf.gz")


async def test_upload_logs_ids_and_counts(
    vcf_service: VcfFileService, project_id: UUID, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.INFO):
        vcf_file = await vcf_service.upload(project_id, "calls.vcf", sample_vcf())

    assert f"vcf_file_id={vcf_file.vcf_file_id}" in caplog.text
    assert "variants=3" in caplog.text
    assert "calls.vcf" not in caplog.text


async def test_upload_unknown_project_raises(vcf_service: VcfFileService) -> None:
    with pytest.raises(ProjectNotFoundError):
        await vcf_service.upload(uuid4(), "calls.vcf", sample_vcf())


async def test_upload_bad_extension_raises_and_warns(
    vcf_service: VcfFileService, project_id: UUID, caplog: pytest.LogCaptureFixture
) -> None:
    with pytest.raises(InvalidFilenameError):
        await vcf_service.upload(project_id, "calls.csv", sample_vcf())

    assert any(record.levelno == logging.WARNING for record in caplog.records)


async def test_upload_invalid_content_stores_nothing(
    vcf_service: VcfFileService,
    storage: InMemoryFileStorage,
    project_id: UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with pytest.raises(InvalidFileFormatError):
        await vcf_service.upload(project_id, "calls.vcf", b"not a vcf")

    assert storage.objects == {}
    assert await vcf_service.list_vcf_files(project_id) == []
    assert "line=1" in caplog.text


async def test_list_vcf_files(vcf_service: VcfFileService, project_id: UUID) -> None:
    first = await vcf_service.upload(project_id, "a.vcf", sample_vcf())
    second = await vcf_service.upload(project_id, "b.vcf", sample_vcf())

    assert await vcf_service.list_vcf_files(project_id) == [first, second]


async def test_list_unknown_project_raises(vcf_service: VcfFileService) -> None:
    with pytest.raises(ProjectNotFoundError):
        await vcf_service.list_vcf_files(uuid4())


async def test_get_pages_variants(vcf_service: VcfFileService, project_id: UUID) -> None:
    vcf_file = await vcf_service.upload(project_id, "calls.vcf", sample_vcf())

    _, variants = await vcf_service.get_vcf_file(project_id, vcf_file.vcf_file_id, 1, 1)

    assert [v.alt for v in variants] == ["T"]


async def test_get_unknown_file_raises_and_warns(
    vcf_service: VcfFileService, project_id: UUID, caplog: pytest.LogCaptureFixture
) -> None:
    with pytest.raises(VcfFileNotFoundError):
        await vcf_service.get_vcf_file(project_id, uuid4(), 100, 0)

    assert any(record.levelno == logging.WARNING for record in caplog.records)


async def test_get_file_of_other_project_raises(
    vcf_service: VcfFileService, repository: InMemoryProjectRepository, project_id: UUID
) -> None:
    other = await repository.add(ProjectCreate(name="other", lead_scientist="R. Franklin"))
    vcf_file = await vcf_service.upload(project_id, "calls.vcf", sample_vcf())

    with pytest.raises(VcfFileNotFoundError):
        await vcf_service.get_vcf_file(other.project_id, vcf_file.vcf_file_id, 100, 0)


async def test_delete_removes_rows_and_file(
    vcf_service: VcfFileService, storage: InMemoryFileStorage, project_id: UUID
) -> None:
    vcf_file = await vcf_service.upload(project_id, "calls.vcf", sample_vcf())

    await vcf_service.delete_vcf_file(project_id, vcf_file.vcf_file_id)

    assert await vcf_service.list_vcf_files(project_id) == []
    assert storage.objects == {}


async def test_delete_unknown_file_raises(vcf_service: VcfFileService, project_id: UUID) -> None:
    with pytest.raises(VcfFileNotFoundError):
        await vcf_service.delete_vcf_file(project_id, uuid4())


async def test_upload_parses_in_a_worker_thread(
    vcf_service: VcfFileService, project_id: UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    threads: list[int] = []

    def spy(lines: list[str]) -> ParsedVcf:
        threads.append(threading.get_ident())
        return parse_vcf(lines)

    monkeypatch.setattr("app.services.vcf_file.parse_vcf", spy)

    await vcf_service.upload(project_id, "calls.vcf", sample_vcf())

    assert threads != [threading.get_ident()]
```

`tests/unit/test_annotation_file_service.py`:

```python
import gzip
import logging
from uuid import UUID, uuid4

import pytest

from app.core.exceptions import (
    AnnotationFileNotFoundError,
    InvalidFileFormatError,
    InvalidFilenameError,
    ProjectNotFoundError,
)
from app.parsers.clinvar import ClinVarFormat
from app.repositories.project import InMemoryProjectRepository
from app.schemas.project import ProjectCreate
from app.services.annotation_file import AnnotationFileService
from app.storage.files import InMemoryFileStorage
from tests.samples import SIMPLIFIED_HEADER, SIMPLIFIED_ROW, clinvar_text, sample_clinvar


@pytest.fixture
async def project_id(repository: InMemoryProjectRepository) -> UUID:
    project = await repository.add(ProjectCreate(name="BRCA", lead_scientist="R. Franklin"))
    return project.project_id


async def test_upload_stores_metadata_and_file(
    annotation_service: AnnotationFileService, storage: InMemoryFileStorage, project_id: UUID
) -> None:
    annotation_file = await annotation_service.upload(project_id, "clinvar.txt", sample_clinvar())

    assert annotation_file.column_format == ClinVarFormat.SIMPLIFIED
    assert annotation_file.entry_count == 1
    assert storage.objects == {annotation_file.s3_key: sample_clinvar()}


async def test_upload_gzip(annotation_service: AnnotationFileService, project_id: UUID) -> None:
    data = gzip.compress(sample_clinvar())

    annotation_file = await annotation_service.upload(project_id, "variant_summary.txt.gz", data)

    assert annotation_file.s3_key.endswith(
        f"/annotation/{annotation_file.annotation_file_id}.txt.gz"
    )


async def test_upload_warns_about_invalid_entries(
    annotation_service: AnnotationFileService,
    project_id: UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    data = clinvar_text(SIMPLIFIED_HEADER, SIMPLIFIED_ROW, "broken row")

    annotation_file = await annotation_service.upload(project_id, "clinvar.tsv", data)

    assert annotation_file.entry_count == 1
    assert "1 invalid entries" in caplog.text


async def test_upload_unknown_project_raises(annotation_service: AnnotationFileService) -> None:
    with pytest.raises(ProjectNotFoundError):
        await annotation_service.upload(uuid4(), "clinvar.txt", sample_clinvar())


async def test_upload_bad_extension_raises(
    annotation_service: AnnotationFileService, project_id: UUID
) -> None:
    with pytest.raises(InvalidFilenameError):
        await annotation_service.upload(project_id, "clinvar.vcf", sample_clinvar())


async def test_upload_invalid_content_stores_nothing(
    annotation_service: AnnotationFileService,
    storage: InMemoryFileStorage,
    project_id: UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with pytest.raises(InvalidFileFormatError):
        await annotation_service.upload(project_id, "clinvar.txt", b"a\tb\n")

    assert storage.objects == {}
    assert any(record.levelno == logging.WARNING for record in caplog.records)


async def test_list_annotation_files(
    annotation_service: AnnotationFileService, project_id: UUID
) -> None:
    annotation_file = await annotation_service.upload(project_id, "clinvar.txt", sample_clinvar())

    assert await annotation_service.list_annotation_files(project_id) == [annotation_file]


async def test_list_unknown_project_raises(annotation_service: AnnotationFileService) -> None:
    with pytest.raises(ProjectNotFoundError):
        await annotation_service.list_annotation_files(uuid4())


async def test_delete_removes_row_and_file(
    annotation_service: AnnotationFileService, storage: InMemoryFileStorage, project_id: UUID
) -> None:
    annotation_file = await annotation_service.upload(project_id, "clinvar.txt", sample_clinvar())

    await annotation_service.delete_annotation_file(project_id, annotation_file.annotation_file_id)

    assert await annotation_service.list_annotation_files(project_id) == []
    assert storage.objects == {}


async def test_delete_unknown_file_raises_and_warns(
    annotation_service: AnnotationFileService,
    project_id: UUID,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with pytest.raises(AnnotationFileNotFoundError):
        await annotation_service.delete_annotation_file(project_id, uuid4())

    assert any(record.levelno == logging.WARNING for record in caplog.records)
```

`tests/unit/test_project_service.py`:

```diff
@@ -7,4 +7,5 @@ from app.core.exceptions import ProjectNameConflictError, ProjectNotFoundError
 from app.schemas.project import ProjectCreate
 from app.services.project import ProjectService
+from app.storage.files import InMemoryFileStorage


@@ -55,2 +56,15 @@ async def test_delete_unknown_project_raises_and_warns(

     assert any(record.levelno == logging.WARNING for record in caplog.records)
+
+
+async def test_delete_project_removes_its_files(
+    service: ProjectService, storage: InMemoryFileStorage
+) -> None:
+    project = await service.create_project(new_project())
+    other = await service.create_project(new_project("other"))
+    await storage.put(f"projects/{project.project_id}/vcf/a.vcf", b"x")
+    await storage.put(f"projects/{other.project_id}/vcf/b.vcf", b"y")
+
+    await service.delete_project(project.project_id)
+
+    assert list(storage.objects) == [f"projects/{other.project_id}/vcf/b.vcf"]
```

`tests/unit/test_in_memory_file_repositories.py`:

```python
from uuid import uuid4

from app.models import AnnotationFileModel, VcfFileModel
from app.parsers.clinvar import ClinVarFormat
from app.parsers.vcf import ParsedVariant
from app.repositories.annotation_file import InMemoryAnnotationFileRepository
from app.repositories.vcf_file import InMemoryVcfFileRepository


def new_vcf_file() -> VcfFileModel:
    return VcfFileModel(
        vcf_file_id=uuid4(),
        project_id=uuid4(),
        filename="calls.vcf",
        s3_key=f"{uuid4()}.vcf",
        sample_count=0,
        variant_count=1,
    )


def new_annotation_file() -> AnnotationFileModel:
    return AnnotationFileModel(
        annotation_file_id=uuid4(),
        project_id=uuid4(),
        filename="clinvar.txt",
        s3_key=f"{uuid4()}.txt",
        column_format=ClinVarFormat.FULL,
        entry_count=1,
    )


VARIANT = ParsedVariant("chr1", 100, None, "A", "G", None, None, 0.5, {"AF": "0.5"})


async def test_vcf_add_assigns_ids_and_timestamp(
    vcf_repository: InMemoryVcfFileRepository,
) -> None:
    vcf_file = await vcf_repository.add(new_vcf_file(), [VARIANT, VARIANT])

    variants = await vcf_repository.list_variants(vcf_file.vcf_file_id, 10, 0)
    assert vcf_file.uploaded_at.tzinfo is not None
    assert [v.variant_id for v in variants] == [1, 2]


async def test_vcf_get_is_scoped_to_project(vcf_repository: InMemoryVcfFileRepository) -> None:
    vcf_file = await vcf_repository.add(new_vcf_file(), [])

    assert await vcf_repository.get(uuid4(), vcf_file.vcf_file_id) is None


async def test_vcf_delete_removes_file_and_variants(
    vcf_repository: InMemoryVcfFileRepository,
) -> None:
    vcf_file = await vcf_repository.add(new_vcf_file(), [VARIANT])

    await vcf_repository.delete(vcf_file)

    assert await vcf_repository.list_for_project(vcf_file.project_id) == []
    assert await vcf_repository.list_variants(vcf_file.vcf_file_id, 10, 0) == []


async def test_annotation_get_is_scoped_to_project(
    annotation_repository: InMemoryAnnotationFileRepository,
) -> None:
    annotation_file = await annotation_repository.add(new_annotation_file())

    assert await annotation_repository.get(uuid4(), annotation_file.annotation_file_id) is None
    assert (
        await annotation_repository.get(
            annotation_file.project_id, annotation_file.annotation_file_id
        )
        is annotation_file
    )


async def test_annotation_delete(annotation_repository: InMemoryAnnotationFileRepository) -> None:
    annotation_file = await annotation_repository.add(new_annotation_file())

    await annotation_repository.delete(annotation_file)

    assert await annotation_repository.list_for_project(annotation_file.project_id) == []
```

`tests/unit/test_file_storage.py`:

```python
import logging
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import boto3
import pytest
from moto import mock_aws
from mypy_boto3_s3 import S3Client

from app.core.config import Settings
from app.core.exceptions import FileStorageError
from app.db.unit_of_work import AfterCommit
from app.storage.files import (
    DeleteAfterCommitStorage,
    InMemoryFileStorage,
    S3FileStorage,
    build_file_storage,
    object_key,
    project_prefix,
)

BUCKET = "test-bucket"


@pytest.fixture
def s3_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[S3Client]:
    """moto fakes S3 inside the process: no network, no real AWS account."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


def keys(client: S3Client) -> list[str]:
    return [obj["Key"] for obj in client.list_objects_v2(Bucket=BUCKET).get("Contents", [])]


def test_object_key_is_under_project_prefix() -> None:
    project_id, file_id = uuid4(), uuid4()

    key = object_key(project_id, "vcf", file_id, ".vcf.gz")

    assert key == f"{project_prefix(project_id)}vcf/{file_id}.vcf.gz"


async def test_s3_put_writes_object(s3_client: S3Client) -> None:
    await S3FileStorage(s3_client, BUCKET).put("a/b.vcf", b"data")

    assert s3_client.get_object(Bucket=BUCKET, Key="a/b.vcf")["Body"].read() == b"data"


async def test_s3_delete_removes_object(s3_client: S3Client) -> None:
    storage = S3FileStorage(s3_client, BUCKET)
    await storage.put("a/b.vcf", b"data")

    await storage.delete("a/b.vcf")

    assert keys(s3_client) == []


async def test_s3_delete_prefix_keeps_other_prefixes(s3_client: S3Client) -> None:
    storage = S3FileStorage(s3_client, BUCKET)
    for key in ["p1/a", "p1/b", "p2/c"]:
        await storage.put(key, b"x")

    await storage.delete_prefix("p1/")

    assert keys(s3_client) == ["p2/c"]


async def test_s3_delete_prefix_without_objects_is_a_no_op(s3_client: S3Client) -> None:
    await S3FileStorage(s3_client, BUCKET).delete_prefix("missing/")

    assert keys(s3_client) == []


def test_build_file_storage_returns_s3_storage(settings: Settings) -> None:
    assert isinstance(build_file_storage(settings), S3FileStorage)


async def test_in_memory_delete_missing_key_is_a_no_op() -> None:
    storage = InMemoryFileStorage()

    await storage.delete("missing")

    assert storage.objects == {}


async def test_in_memory_delete_prefix() -> None:
    storage = InMemoryFileStorage()
    await storage.put("p1/a", b"x")
    await storage.put("p2/b", b"y")

    await storage.delete_prefix("p1/")

    assert storage.objects == {"p2/b": b"y"}


async def test_s3_delete_prefix_raises_on_partial_failure(
    s3_client: S3Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage = S3FileStorage(s3_client, BUCKET)
    await storage.put("p1/a", b"x")

    def refuse(**_: object) -> dict[str, Any]:  # S3 reports per-key failures with HTTP 200
        return {"Errors": [{"Key": "p1/a", "Code": "AccessDenied"}]}

    monkeypatch.setattr(s3_client, "delete_objects", refuse)

    with pytest.raises(FileStorageError):
        await storage.delete_prefix("p1/")


async def test_s3_delete_prefix_client_error_becomes_storage_error(s3_client: S3Client) -> None:
    with pytest.raises(FileStorageError):
        await S3FileStorage(s3_client, "missing-bucket").delete_prefix("p1/")


async def test_s3_delete_client_error_becomes_storage_error(s3_client: S3Client) -> None:
    with pytest.raises(FileStorageError):
        await S3FileStorage(s3_client, "missing-bucket").delete("a")


class BrokenStorage(InMemoryFileStorage):
    async def delete(self, key: str) -> None:
        raise FileStorageError(f"refused key={key}")


async def test_deferred_storage_writes_at_once_and_deletes_after_commit() -> None:
    storage, after_commit = InMemoryFileStorage(), AfterCommit()
    deferred = DeleteAfterCommitStorage(storage, after_commit)
    await deferred.put("p1/a", b"x")
    await deferred.put("p2/b", b"y")

    await deferred.delete("p1/a")
    await deferred.delete_prefix("p2/")
    before_commit = dict(storage.objects)
    await after_commit.run()

    assert before_commit == {"p1/a": b"x", "p2/b": b"y"}
    assert storage.objects == {}


async def test_deferred_storage_logs_failed_delete_instead_of_raising(
    caplog: pytest.LogCaptureFixture,
) -> None:
    after_commit = AfterCommit()
    await DeleteAfterCommitStorage(BrokenStorage(), after_commit).delete("p1/a")

    await after_commit.run()

    assert any(
        record.levelno == logging.ERROR and "p1/a" in record.getMessage()
        for record in caplog.records
    )
```

`mock_aws()` replaces the AWS endpoints inside the process, so `S3FileStorage` runs its real boto3
calls (put, delete, paginated list) against a fake bucket: no network, no account, milliseconds.
The fake credentials are set per test with `monkeypatch`, so a developer's real AWS credentials
can never be picked up.

### API tests

`tests/api/conftest.py`:

```python
from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_annotation_file_service, get_project_service, get_vcf_file_service
from app.core.config import Settings
from app.main import create_app
from app.services.annotation_file import AnnotationFileService
from app.services.project import ProjectService
from app.services.vcf_file import VcfFileService


@pytest_asyncio.fixture
async def client(
    settings: Settings,
    service: ProjectService,
    vcf_service: VcfFileService,
    annotation_service: AnnotationFileService,
) -> AsyncIterator[AsyncClient]:
    """HTTP client over the real app, with storage swapped for the in-memory implementations."""
    app = create_app(settings)
    app.dependency_overrides[get_project_service] = lambda: service
    app.dependency_overrides[get_vcf_file_service] = lambda: vcf_service
    app.dependency_overrides[get_annotation_file_service] = lambda: annotation_service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
```

`tests/api/helpers.py`:

```python
from typing import Any

from httpx import AsyncClient

PROJECTS = "/api/v1/projects/"


async def create_project(client: AsyncClient) -> str:
    response = await client.post(PROJECTS, json={"name": "BRCA", "lead_scientist": "R. Franklin"})
    project_id: str = response.json()["project_id"]
    return project_id


async def upload(client: AsyncClient, url: str, filename: str, data: bytes) -> dict[str, Any]:
    response = await client.post(url, files={"file": (filename, data)})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body
```

`tests/api/test_vcf_files.py`:

```python
import gzip
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from app.api.deps import get_vcf_file_service
from app.api.uploads import MULTIPART_OVERHEAD_BYTES
from app.core.config import Settings
from app.main import create_app
from app.services.vcf_file import VcfFileService
from tests.api.helpers import PROJECTS, create_project, upload
from tests.samples import sample_vcf


def vcf_url(project_id: str) -> str:
    return f"{PROJECTS}{project_id}/vcf/"


async def test_upload_returns_201_with_metadata(client: AsyncClient) -> None:
    project_id = await create_project(client)

    body = await upload(client, vcf_url(project_id), "calls.vcf", sample_vcf())

    assert body["project_id"] == project_id
    assert (body["filename"], body["variant_count"], body["sample_count"]) == ("calls.vcf", 3, 0)
    assert set(body) == {
        "vcf_file_id",
        "project_id",
        "filename",
        "sample_count",
        "variant_count",
        "uploaded_at",
    }


async def test_upload_sets_location_of_new_file(client: AsyncClient) -> None:
    project_id = await create_project(client)

    response = await client.post(vcf_url(project_id), files={"file": ("a.vcf", sample_vcf())})

    location = response.headers["location"]
    assert location.endswith(f"{vcf_url(project_id)}{response.json()['vcf_file_id']}")
    assert (await client.get(location)).status_code == 200


async def test_upload_gzip_returns_201(client: AsyncClient) -> None:
    project_id = await create_project(client)

    body = await upload(client, vcf_url(project_id), "calls.vcf.gz", gzip.compress(sample_vcf()))

    assert body["variant_count"] == 3


async def test_upload_unknown_project_returns_404(client: AsyncClient) -> None:
    response = await client.post(vcf_url(str(uuid4())), files={"file": ("a.vcf", sample_vcf())})

    assert response.status_code == 404


async def test_upload_bad_extension_returns_422(client: AsyncClient) -> None:
    project_id = await create_project(client)

    response = await client.post(vcf_url(project_id), files={"file": ("a.txt", sample_vcf())})

    assert response.status_code == 422


async def test_upload_invalid_vcf_returns_422_with_line(client: AsyncClient) -> None:
    project_id = await create_project(client)

    response = await client.post(vcf_url(project_id), files={"file": ("a.vcf", b"garbage")})

    assert response.status_code == 422
    assert "line 1" in response.json()["detail"]


async def test_upload_without_file_returns_422(client: AsyncClient) -> None:
    project_id = await create_project(client)

    response = await client.post(vcf_url(project_id))

    assert response.status_code == 422


async def test_upload_too_large_returns_413(
    settings: Settings, vcf_service: VcfFileService
) -> None:
    app = create_app(settings.model_copy(update={"max_upload_bytes": 10}))
    app.dependency_overrides[get_vcf_file_service] = lambda: vcf_service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(vcf_url(str(uuid4())), files={"file": ("a.vcf", b"x" * 11)})

    assert response.status_code == 413


async def test_list_returns_uploaded_files(client: AsyncClient) -> None:
    project_id = await create_project(client)
    first = await upload(client, vcf_url(project_id), "a.vcf", sample_vcf())
    second = await upload(client, vcf_url(project_id), "b.vcf", sample_vcf())

    response = await client.get(vcf_url(project_id))

    assert response.status_code == 200
    assert response.json() == [first, second]


async def test_list_unknown_project_returns_404(client: AsyncClient) -> None:
    response = await client.get(vcf_url(str(uuid4())))

    assert response.status_code == 404


async def test_get_returns_metadata_and_variants(client: AsyncClient) -> None:
    project_id = await create_project(client)
    vcf_file = await upload(client, vcf_url(project_id), "calls.vcf", sample_vcf())

    response = await client.get(f"{vcf_url(project_id)}{vcf_file['vcf_file_id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["vcf_file_id"] == vcf_file["vcf_file_id"]
    assert [(v["chrom"], v["pos"], v["alt"], v["af"]) for v in body["variants"]] == [
        ("chr1", 100, "G", 0.25),
        ("chr2", 200, "T", 0.1),
        ("chr2", 200, "A", 0.2),
    ]


async def test_get_pages_variants(client: AsyncClient) -> None:
    project_id = await create_project(client)
    vcf_file = await upload(client, vcf_url(project_id), "calls.vcf", sample_vcf())
    url = f"{vcf_url(project_id)}{vcf_file['vcf_file_id']}"

    response = await client.get(url, params={"limit": 1, "offset": 2})

    assert [v["alt"] for v in response.json()["variants"]] == ["A"]


async def test_get_invalid_limit_returns_422(client: AsyncClient) -> None:
    project_id = await create_project(client)

    response = await client.get(f"{vcf_url(project_id)}{uuid4()}", params={"limit": 0})

    assert response.status_code == 422


async def test_get_unknown_file_returns_404(client: AsyncClient) -> None:
    project_id = await create_project(client)

    response = await client.get(f"{vcf_url(project_id)}{uuid4()}")

    assert response.status_code == 404


async def test_delete_returns_204(client: AsyncClient) -> None:
    project_id = await create_project(client)
    vcf_file = await upload(client, vcf_url(project_id), "calls.vcf", sample_vcf())

    response = await client.delete(f"{vcf_url(project_id)}{vcf_file['vcf_file_id']}")

    assert response.status_code == 204
    assert (await client.get(vcf_url(project_id))).json() == []


async def test_delete_unknown_file_returns_404(client: AsyncClient) -> None:
    project_id = await create_project(client)

    response = await client.delete(f"{vcf_url(project_id)}{uuid4()}")

    assert response.status_code == 404


async def test_delete_in_unknown_project_returns_404(client: AsyncClient) -> None:
    response = await client.delete(f"{vcf_url(str(uuid4()))}{uuid4()}")

    assert response.status_code == 404


async def test_announced_oversized_body_is_rejected_before_parsing(settings: Settings) -> None:
    app = create_app(settings.model_copy(update={"max_upload_bytes": 10}))
    body = b"x" * (MULTIPART_OVERHEAD_BYTES + 11)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(vcf_url(str(uuid4())), files={"file": ("a.vcf", body)})

    assert response.status_code == 413
```

`tests/api/test_annotation_files.py`:

```python
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from app.api.deps import get_annotation_file_service
from app.core.config import Settings
from app.main import create_app
from app.services.annotation_file import AnnotationFileService
from tests.api.helpers import PROJECTS, create_project, upload
from tests.samples import sample_clinvar


def annotation_url(project_id: str) -> str:
    return f"{PROJECTS}{project_id}/annotation/"


async def test_upload_returns_201_with_metadata(client: AsyncClient) -> None:
    project_id = await create_project(client)

    body = await upload(client, annotation_url(project_id), "clinvar.txt", sample_clinvar())

    assert (body["column_format"], body["entry_count"]) == ("simplified", 1)
    assert set(body) == {
        "annotation_file_id",
        "project_id",
        "filename",
        "column_format",
        "entry_count",
        "uploaded_at",
    }


async def test_upload_unknown_project_returns_404(client: AsyncClient) -> None:
    files = {"file": ("clinvar.txt", sample_clinvar())}

    response = await client.post(annotation_url(str(uuid4())), files=files)

    assert response.status_code == 404


async def test_upload_bad_extension_returns_422(client: AsyncClient) -> None:
    project_id = await create_project(client)

    response = await client.post(
        annotation_url(project_id), files={"file": ("clinvar.csv", sample_clinvar())}
    )

    assert response.status_code == 422


async def test_upload_invalid_format_returns_422(client: AsyncClient) -> None:
    project_id = await create_project(client)

    response = await client.post(
        annotation_url(project_id), files={"file": ("clinvar.txt", b"a\tb\n1\t2\n")}
    )

    assert response.status_code == 422


async def test_list_returns_uploaded_files(client: AsyncClient) -> None:
    project_id = await create_project(client)
    uploaded = await upload(client, annotation_url(project_id), "clinvar.txt", sample_clinvar())

    response = await client.get(annotation_url(project_id))

    assert response.status_code == 200
    assert response.json() == [uploaded]


async def test_list_unknown_project_returns_404(client: AsyncClient) -> None:
    response = await client.get(annotation_url(str(uuid4())))

    assert response.status_code == 404


async def test_delete_returns_204(client: AsyncClient) -> None:
    project_id = await create_project(client)
    uploaded = await upload(client, annotation_url(project_id), "clinvar.txt", sample_clinvar())

    response = await client.delete(f"{annotation_url(project_id)}{uploaded['annotation_file_id']}")

    assert response.status_code == 204
    assert (await client.get(annotation_url(project_id))).json() == []


async def test_delete_unknown_file_returns_404(client: AsyncClient) -> None:
    project_id = await create_project(client)

    response = await client.delete(f"{annotation_url(project_id)}{uuid4()}")

    assert response.status_code == 404


async def test_upload_without_file_returns_422(client: AsyncClient) -> None:
    project_id = await create_project(client)

    response = await client.post(annotation_url(project_id))

    assert response.status_code == 422


async def test_upload_too_large_returns_413(
    settings: Settings, annotation_service: AnnotationFileService
) -> None:
    app = create_app(settings.model_copy(update={"max_upload_bytes": 10}))
    app.dependency_overrides[get_annotation_file_service] = lambda: annotation_service
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            annotation_url(str(uuid4())), files={"file": ("clinvar.txt", b"x" * 11)}
        )

    assert response.status_code == 413


async def test_delete_in_unknown_project_returns_404(client: AsyncClient) -> None:
    response = await client.delete(f"{annotation_url(str(uuid4()))}{uuid4()}")

    assert response.status_code == 404
```

The 413 tests build their own app with `max_upload_bytes=10` (`model_copy` leaves the shared
session-scoped settings untouched), so they need an 11-byte body, not a 50 MB one.

### Integration tests

`tests/integration/conftest.py`, add an `e2e_client` fixture (and its imports). Since step 9,
deleting a project deletes S3 objects, so the week 1 end-to-end test needs storage too:

```diff
@@ -4,8 +4,11 @@ from collections.abc import AsyncIterator

 import pytest_asyncio
+from httpx import ASGITransport, AsyncClient
 from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

 from app.core.config import Settings
+from app.main import create_app
 from app.models import Base
+from app.storage.files import InMemoryFileStorage


@@ -32,2 +35,16 @@ async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
             await session.close()
             await conn.rollback()
+
+
+@pytest_asyncio.fixture
+async def e2e_client(
+    engine: AsyncEngine, settings: Settings, storage: InMemoryFileStorage
+) -> AsyncIterator[AsyncClient]:
+    """Real app, lifespan and Postgres (requests commit); S3 replaced by in-memory storage."""
+    app = create_app(settings)
+    async with (
+        app.router.lifespan_context(app),
+        AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client,
+    ):
+        app.state.file_storage = storage  # replaces S3 behind the real dependency chain
+        yield client
```

`tests/integration/test_projects_e2e.py` now uses it:

```python
"""Full stack against Postgres: lifespan, per-request session, commit, real SQL."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration

URL = "/api/v1/projects/"


async def test_project_lifecycle(e2e_client: AsyncClient) -> None:
    payload = {"name": f"e2e-{uuid4()}", "lead_scientist": "Rosalind Franklin"}

    created = await e2e_client.post(URL, json=payload)
    assert created.status_code == 201
    assert (await e2e_client.post(URL, json=payload)).status_code == 409
    project = created.json()
    assert project in (await e2e_client.get(URL)).json()

    deleted = await e2e_client.delete(f"{URL}{project['project_id']}/")

    assert deleted.status_code == 204
    assert project not in (await e2e_client.get(URL)).json()
```

`tests/integration/test_file_repositories.py`:

```python
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AnnotationFileModel, VariantModel, VcfFileModel
from app.parsers.clinvar import ClinVarFormat
from app.parsers.vcf import ParsedVariant
from app.repositories.annotation_file import SqlAlchemyAnnotationFileRepository
from app.repositories.project import SqlAlchemyProjectRepository
from app.repositories.vcf_file import INSERT_BATCH_SIZE, SqlAlchemyVcfFileRepository
from app.schemas.project import ProjectCreate

pytestmark = pytest.mark.integration


def variant(pos: int) -> ParsedVariant:
    return ParsedVariant("chr1", pos, None, "A", "G", 30.0, "PASS", 0.5, {"AF": "0.5", "DB": True})


def new_vcf_file(project_id: UUID) -> VcfFileModel:
    return VcfFileModel(
        vcf_file_id=uuid4(),
        project_id=project_id,
        filename="calls.vcf",
        s3_key=f"projects/{project_id}/vcf/{uuid4()}.vcf",
        sample_count=0,
        variant_count=0,
    )


def new_annotation_file(project_id: UUID) -> AnnotationFileModel:
    return AnnotationFileModel(
        annotation_file_id=uuid4(),
        project_id=project_id,
        filename="clinvar.txt",
        s3_key=f"projects/{project_id}/annotation/{uuid4()}.txt",
        column_format=ClinVarFormat.FULL,
        entry_count=1,
    )


@pytest.fixture
async def project_id(session: AsyncSession) -> UUID:
    projects = SqlAlchemyProjectRepository(session)
    project = await projects.add(ProjectCreate(name="BRCA", lead_scientist="R. Franklin"))
    return project.project_id


@pytest.fixture
def vcf_files(session: AsyncSession) -> SqlAlchemyVcfFileRepository:
    return SqlAlchemyVcfFileRepository(session)


@pytest.fixture
def annotation_files(session: AsyncSession) -> SqlAlchemyAnnotationFileRepository:
    return SqlAlchemyAnnotationFileRepository(session)


async def count_variants(session: AsyncSession) -> int:
    return await session.scalar(select(func.count()).select_from(VariantModel)) or 0


async def test_add_inserts_variants_in_batches(
    vcf_files: SqlAlchemyVcfFileRepository, session: AsyncSession, project_id: UUID
) -> None:
    variants = [variant(pos) for pos in range(1, INSERT_BATCH_SIZE + 2)]

    vcf_file = await vcf_files.add(new_vcf_file(project_id), variants)

    assert vcf_file.uploaded_at is not None
    assert await count_variants(session) == INSERT_BATCH_SIZE + 1


async def test_list_variants_round_trips_jsonb_and_pages(
    vcf_files: SqlAlchemyVcfFileRepository, project_id: UUID
) -> None:
    vcf_file = await vcf_files.add(new_vcf_file(project_id), [variant(1), variant(2)])

    [second] = await vcf_files.list_variants(vcf_file.vcf_file_id, limit=1, offset=1)

    assert (second.pos, second.af, second.info) == (2, 0.5, {"AF": "0.5", "DB": True})


async def test_get_is_scoped_to_project(
    vcf_files: SqlAlchemyVcfFileRepository, project_id: UUID
) -> None:
    vcf_file = await vcf_files.add(new_vcf_file(project_id), [])

    assert await vcf_files.get(project_id, vcf_file.vcf_file_id) is vcf_file
    assert await vcf_files.get(uuid4(), vcf_file.vcf_file_id) is None


async def test_list_for_project(vcf_files: SqlAlchemyVcfFileRepository, project_id: UUID) -> None:
    vcf_file = await vcf_files.add(new_vcf_file(project_id), [])

    assert await vcf_files.list_for_project(project_id) == [vcf_file]


async def test_delete_cascades_to_variants(
    vcf_files: SqlAlchemyVcfFileRepository, session: AsyncSession, project_id: UUID
) -> None:
    vcf_file = await vcf_files.add(new_vcf_file(project_id), [variant(1)])

    await vcf_files.delete(vcf_file)

    assert await count_variants(session) == 0


async def test_long_alleles_are_stored(
    vcf_files: SqlAlchemyVcfFileRepository, project_id: UUID
) -> None:
    deletion = ParsedVariant("chr1", 1, None, "A" * 10_000, "A", None, None, None, {})

    vcf_file = await vcf_files.add(new_vcf_file(project_id), [deletion])

    [stored] = await vcf_files.list_variants(vcf_file.vcf_file_id, limit=1, offset=0)
    assert len(stored.ref) == 10_000


async def test_deleting_project_cascades_to_files(
    vcf_files: SqlAlchemyVcfFileRepository,
    annotation_files: SqlAlchemyAnnotationFileRepository,
    session: AsyncSession,
    project_id: UUID,
) -> None:
    await vcf_files.add(new_vcf_file(project_id), [variant(1)])
    await annotation_files.add(new_annotation_file(project_id))
    projects = SqlAlchemyProjectRepository(session)
    project = await projects.get(project_id)
    assert project is not None

    await projects.delete(project)

    session.expunge_all()
    assert await vcf_files.list_for_project(project_id) == []
    assert await annotation_files.list_for_project(project_id) == []
    assert await count_variants(session) == 0


async def test_annotation_add_get_list_delete(
    annotation_files: SqlAlchemyAnnotationFileRepository, project_id: UUID
) -> None:
    annotation_file = await annotation_files.add(new_annotation_file(project_id))
    assert await annotation_files.get(project_id, annotation_file.annotation_file_id) is (
        annotation_file
    )
    assert await annotation_files.list_for_project(project_id) == [annotation_file]

    await annotation_files.delete(annotation_file)

    assert await annotation_files.get(project_id, annotation_file.annotation_file_id) is None
```

`tests/integration/test_files_e2e.py`:

```python
"""Full stack against Postgres: upload, read and delete files, then delete the project."""

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.storage.files import InMemoryFileStorage
from tests.samples import sample_clinvar, sample_vcf

pytestmark = pytest.mark.integration

PROJECTS = "/api/v1/projects/"


async def test_file_lifecycle(e2e_client: AsyncClient, storage: InMemoryFileStorage) -> None:
    payload = {"name": f"e2e-{uuid4()}", "lead_scientist": "Rosalind Franklin"}
    project_id = (await e2e_client.post(PROJECTS, json=payload)).json()["project_id"]
    base = f"{PROJECTS}{project_id}"

    vcf = await e2e_client.post(f"{base}/vcf/", files={"file": ("calls.vcf", sample_vcf())})
    annotation = await e2e_client.post(
        f"{base}/annotation/", files={"file": ("clinvar.txt", sample_clinvar())}
    )
    assert (vcf.status_code, annotation.status_code) == (201, 201)
    detail = await e2e_client.get(f"{base}/vcf/{vcf.json()['vcf_file_id']}")
    assert len(detail.json()["variants"]) == 3
    assert len(storage.objects) == 2

    deleted = await e2e_client.delete(f"{base}/")

    assert deleted.status_code == 204
    assert storage.objects == {}
    assert (await e2e_client.get(f"{base}/vcf/")).status_code == 404
```

`tests/integration/test_unit_of_work.py`:

```python
"""get_session runs after-commit actions only when the transaction commits."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from app.db.session import get_session
from app.db.unit_of_work import AfterCommit

pytestmark = pytest.mark.integration


def fake_request(engine: AsyncEngine) -> Request:
    state = SimpleNamespace(sessionmaker=async_sessionmaker(engine, expire_on_commit=False))
    return cast(Request, SimpleNamespace(app=SimpleNamespace(state=state)))


async def record(calls: list[str]) -> None:
    calls.append("ran")


async def test_actions_run_after_commit(engine: AsyncEngine) -> None:
    calls: list[str] = []
    after_commit = AfterCommit()
    after_commit.add(lambda: record(calls))

    async with asynccontextmanager(get_session)(fake_request(engine), after_commit):
        assert calls == []

    assert calls == ["ran"]


async def test_actions_skipped_on_rollback(engine: AsyncEngine) -> None:
    calls: list[str] = []
    after_commit = AfterCommit()
    after_commit.add(lambda: record(calls))

    with pytest.raises(RuntimeError):
        async with asynccontextmanager(get_session)(fake_request(engine), after_commit):
            raise RuntimeError("request failed")

    assert calls == []
```

- `test_add_inserts_variants_in_batches` inserts `INSERT_BATCH_SIZE + 1` rows, so the last,
  partial batch is exercised too.
- `test_deleting_project_cascades_to_files` proves the `ON DELETE CASCADE` chain in real
  Postgres: project, then files, then variants. `expunge_all()` drops the objects cached in the
  session, so the following queries really read the database.
- `test_long_alleles_are_stored` stores a 10 kb REF allele, the case a unique index on the
  allele columns would turn into a 500.
- `test_unit_of_work.py` checks the after-commit contract directly: actions run after a commit
  and are dropped when the request raises.

Run:

```bash
poetry run pytest -m "not integration"     # unit + API, no Docker needed
docker compose up -d test_db
poetry run python scripts/check.py         # everything, fails below 80% line coverage
```

Expected: 191 passed, total coverage around 99% (around 92% without the integration tests).

CI needs no change: the new dependencies come from `poetry.lock`, the S3 tests use moto in
process, and the integration tests replace S3 with the in-memory storage.

## Step 13. README.md

Update the scope line, the branch table, the run instructions and the API table:

````diff
@@ -2,8 +2,10 @@

 REST API to upload VCF files, filter and annotate genomic variants and retrieve summaries.
-Week 1 scope: projects. Architecture: [ARCHITECTURE.md](ARCHITECTURE.md).
+Scope so far: projects (week 1), VCF and ClinVar annotation file uploads (week 2).
+Architecture: [ARCHITECTURE.md](ARCHITECTURE.md).

-You are on `week_1_implementation`: the full working week 1 solution. The step-by-step
-walkthrough that builds it is [docs/week-01-implementation.md](docs/week-01-implementation.md).
+You are on `week_2_implementation`: the full working solution up to week 2. The step-by-step
+walkthroughs are [docs/week-01-implementation.md](docs/week-01-implementation.md) and
+[docs/week-02-implementation.md](docs/week-02-implementation.md).

 ## Branches
@@ -16,4 +18,5 @@ Each branch builds on the previous.
 | `week_1_setup` | `main` plus detailed guidance: concrete layer layout, filled-in architecture, extra Claude Code skill | Build week 1 with a clear target structure |
 | `week_1_implementation` | `week_1_setup` plus the full working week 1 solution and a step-by-step walkthrough | Compare your work or study a reference implementation |
+| `week_2_implementation` | `week_1_implementation` plus VCF and annotation file endpoints and the week 2 walkthrough | Compare your week 2 work |

 ## Requirements
@@ -27,6 +30,7 @@ docker compose up --build
 ```

-Starts Postgres, applies migrations, then serves the API on http://127.0.0.1:8000
-(interactive docs: http://127.0.0.1:8000/docs).
+Starts Postgres and a local S3 (moto server, bucket created by `s3-init`), applies migrations,
+then serves the API on http://127.0.0.1:8000 (interactive docs: http://127.0.0.1:8000/docs).
+Local S3 keeps objects in memory: they are gone after `docker compose down`.

 ## Local development
@@ -35,7 +39,7 @@ Starts Postgres, applies migrations, then serves the API on http://127.0.0.1:800
 poetry install
 cp .env.example .env
-docker compose up -d db
+docker compose up -d db s3-init        # s3-init starts s3 and creates the bucket
 poetry run alembic upgrade head
-poetry run uvicorn app.main:create_app --factory --reload
+poetry run uvicorn app.main:create_app --factory --reload --env-file .env
 poetry run pre-commit install
 ```
@@ -66,6 +70,19 @@ Rebuild the image (`docker compose up --build`) after adding a migration.
 | GET | /api/v1/projects/ | 200 | |
 | DELETE | /api/v1/projects/{project_id}/ | 204 | 404, 422 |
+| POST | /api/v1/projects/{project_id}/vcf/ (multipart `file`: .vcf, .vcf.gz) | 201 + Location | 404, 413, 422 |
+| GET | /api/v1/projects/{project_id}/vcf/ | 200 | 404 |
+| GET | /api/v1/projects/{project_id}/vcf/{vcf_id}?limit=&offset= | 200 | 404, 422 |
+| DELETE | /api/v1/projects/{project_id}/vcf/{vcf_id} | 204 | 404 |
+| POST | /api/v1/projects/{project_id}/annotation/ (multipart `file`: .txt, .tsv, optionally .gz) | 201 | 404, 413, 422 |
+| GET | /api/v1/projects/{project_id}/annotation/ | 200 | 404 |
+| DELETE | /api/v1/projects/{project_id}/annotation/{annotation_id} | 204 | 404 |
 | GET | /health | 200 | |

+Example upload:
+
+```bash
+curl -F file=@calls.vcf.gz http://127.0.0.1:8000/api/v1/projects/<project_id>/vcf/
+```
+
 ## Quality checks
````

## Final verification

```bash
poetry install
docker compose up -d db test_db
poetry run alembic upgrade head && poetry run alembic check
poetry run python scripts/check.py
docker compose up --build -d --wait api
# upload, list, get, delete as in step 11
docker compose down
git push                                                          # watch CI go green
```

## Common pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| `RuntimeError: Form data requires "python-multipart" to be installed` | Dependency missing | `poetry add python-multipart` |
| 422 `field required` on upload | Field name is not `file`, or JSON was sent | `curl -F file=@calls.vcf ...` (multipart) |
| 500 with `NoCredentialsError` | API run with Poetry without AWS variables | `--env-file .env` (step 11) |
| 500 with `NoSuchBucket` | Local S3 restarted (in-memory) or `s3-init` did not run | `docker compose up -d s3-init` |
| 500 with `EndpointConnectionError` | `S3_ENDPOINT_URL` wrong or `s3` not running | `docker compose up -d s3-init`; locally use `http://localhost:9000`, in Compose `http://s3:5000` |
| Integration tests call real S3 | App built without the storage override | Use the `e2e_client` fixture |
| 422 `decompressed file is larger than ...` for a small `.gz` | The content after decompression is over `MAX_UPLOAD_BYTES` (the gzip bomb guard) | Raise `MAX_UPLOAD_BYTES` or split the file |
| 422 `AF has 1 values for 2 ALT alleles` | AF must have one value per ALT allele | Fix the file (`bcftools +fill-tags` recomputes AF) |
| ClinVar file rejected with a header error | Header renamed or fewer than 32 columns | Use the NCBI file or the exact 12-column header |
| Event loop stalls under load during uploads | Blocking boto3 call or parsing in `async def` | Wrap it in `asyncio.to_thread` (steps 7 and 9) |
| Editor warning `asynccontextmanager` is deprecated | Function annotated `-> AsyncIterator[...]`; the decorator needs `athrow` and `aclose`, which only an async generator has | Annotate `-> AsyncGenerator[...]` (`main.py`, `session.py`) |
| 500 `index row size exceeds btree maximum` | A unique index over `ref`/`alt` | Do not index unbounded allele text (step 6) |
| S3 objects still there after a delete, ERROR `Orphaned file after commit` | S3 refused the delete after the commit | Fix bucket permissions; delete the logged keys |
