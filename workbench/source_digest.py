"""Byte identity for bound source text, including older Windows bindings."""
from hashlib import sha256


def source_digest(content):
    return sha256(content.replace(b'\r\n', b'\n')).hexdigest()


def matches_digest(content, expected):
    lf = content.replace(b'\r\n', b'\n')
    return any(sha256(candidate).hexdigest() == expected
               for candidate in (content, lf, lf.replace(b'\n', b'\r\n')))
