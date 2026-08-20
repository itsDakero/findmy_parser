"""CSV output: one row per location fix."""

from __future__ import annotations

import csv
from pathlib import Path

from ..discovery import DiscoveryResult
from . import FIELDNAMES, iter_rows


def write_csv(result: DiscoveryResult, path: Path) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in iter_rows(result):
            writer.writerow(row)
