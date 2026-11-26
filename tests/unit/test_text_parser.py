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
