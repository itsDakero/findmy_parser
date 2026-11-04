"""Regenerate the synthetic fixture tree before the test session runs.

tests/fixtures/synthetic/ is generated (see generate_synthetic.py) and
git-ignored rather than committed as binary blobs, so it's rebuilt here
on demand instead of relying on a checked-in copy.
"""

import sys
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SYNTHETIC_DIR = FIXTURES_DIR / "synthetic"


def pytest_configure(config):
    sys.path.insert(0, str(FIXTURES_DIR))
    import generate_synthetic

    generate_synthetic.main()
    generate_synthetic.main_pa()
