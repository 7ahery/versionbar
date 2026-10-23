"""Turning a tool's raw output bytes into text.

Encoding is detected from the bytes of each stream rather than declared per
tool, so a definition never needs to know it: WSL prints UTF-16LE without a
BOM (and UTF-8 when `WSL_UTF8=1` is set), and both decode the same way. Capture
and scan share this, so a capture's readable text is what the engine parses.
"""

import codecs


def detect_encoding(data: bytes) -> str:
    """Best guess for one stream: `utf-16` (BOM), `utf-16-le` (NULs), else `utf-8`."""
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return "utf-16"
    # Version output is overwhelmingly ASCII, which UTF-16 interleaves with
    # NULs and no 8-bit text encoding ever contains. Big-endian UTF-16 without
    # a BOM has not been seen from a Windows tool, so it is not guessed.
    if b"\x00" in data:
        return "utf-16-le"
    return "utf-8"


def decode_output(data: bytes) -> str:
    """Decode one stream. Never fails: undecodable bytes become U+FFFD."""
    text = data.decode(detect_encoding(data), errors="replace").removeprefix("﻿")
    # Windows tools end lines with CRLF; consumers of `raw` should not have to care.
    return text.replace("\r\n", "\n")
