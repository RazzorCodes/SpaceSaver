import os
import tempfile
from hash import compute_hash

def test_compute_hash():
    with tempfile.NamedTemporaryFile(delete=False) as f:
        f.write(b"0" * 1024)
        tmp_path = f.name
        
    try:
        hash_val = compute_hash(tmp_path)
        assert isinstance(hash_val, str)
        assert len(hash_val) == 64  # SHA-256 is 64 hex chars
    finally:
        os.remove(tmp_path)

test_compute_hash()
print('Hash tests passed!')
