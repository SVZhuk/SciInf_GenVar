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
