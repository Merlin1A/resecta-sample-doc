"""The PDF standard security handler, revision 2 (40-bit RC4), in plain Python (ISO 32000-1, 7.6.3).

Enough to write an encrypted test file deterministically: the owner entry (Algorithm 3), the file
key (Algorithm 2), the user entry (Algorithm 4) and each object's key (Algorithm 1). RC4 is used
here only because the format defines it; it protects nothing in a test fixture.
"""

from __future__ import annotations

import hashlib

PAD = bytes.fromhex("28BF4E5E4E758A4164004E56FFFA01082E2E00B6D0683E802F0CA9FE6453697A")
KEY_BYTES = 5


def rc4(key: bytes, data: bytes) -> bytes:
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) & 0xFF
        s[i], s[j] = s[j], s[i]
    out = bytearray()
    i = j = 0
    for b in data:
        i = (i + 1) & 0xFF
        j = (j + s[i]) & 0xFF
        s[i], s[j] = s[j], s[i]
        out.append(b ^ s[(s[i] + s[j]) & 0xFF])
    return bytes(out)


def _padded(pw: bytes) -> bytes:
    return (pw + PAD)[:32]


def _md5(b: bytes) -> bytes:
    return hashlib.md5(b, usedforsecurity=False).digest()


def owner_entry(owner: bytes, user: bytes) -> bytes:
    """Algorithm 3, revision 2."""
    key = _md5(_padded(owner))[:KEY_BYTES]
    return rc4(key, _padded(user))


def file_key(user: bytes, o_entry: bytes, permissions: int, file_id: bytes) -> bytes:
    """Algorithm 2, revision 2."""
    p = (permissions & 0xFFFFFFFF).to_bytes(4, "little")
    return _md5(_padded(user) + o_entry + p + file_id)[:KEY_BYTES]


def u_entry(key: bytes) -> bytes:
    """Algorithm 4: the padding string encrypted with the file key."""
    return rc4(key, PAD)


def standard_r2(user: bytes, owner: bytes, file_id: bytes, permissions: int) -> tuple[bytes, bytes]:
    """(the /O entry, the file key)."""
    o = owner_entry(owner, user)
    return o, file_key(user, o, permissions, file_id)


def object_key(key: bytes, num: int, gen: int) -> bytes:
    """Algorithm 1: the file key extended by the object and generation numbers."""
    k = _md5(key + num.to_bytes(3, "little") + gen.to_bytes(2, "little"))
    return k[: min(len(key) + 5, 16)]


def encrypt_object(key: bytes, num: int, gen: int, data: bytes) -> bytes:
    return rc4(object_key(key, num, gen), data)
