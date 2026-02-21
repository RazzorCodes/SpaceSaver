"""
hash.py — Fast, stable file identification.

Hashes the first 64 KB of file content + the file size (as a suffix).
This is intentionally not a full-file hash for performance on large media files,
but is stable as long as the file header and size don't change between scans.
"""

import hashlib
import os

SAMPLE_BYTES = 65_536  # 64 KB


def compute_hash(path: str) -> str:
    """Return a hex SHA-256 of the first 64 KB + file size."""
    h = hashlib.sha256()
    file_size = os.path.getsize(path)
    with open(path, "rb") as f:
        chunk = f.read(SAMPLE_BYTES)
        h.update(chunk)
    # Mix in the file size so that truncated copies get different hashes
    h.update(str(file_size).encode())
    return h.hexdigest()
