"""Full snapshot contract; money is exact decimal, never floating point."""
import csv
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import io
import re
from pathlib import Path
from .config import SafeError

MAX_BYTES = 5_000_000
MAX_ROWS = 10_000
FIELDS = ("line_id", "date", "sku", "product", "category", "channel", "qty", "net_revenue", "net_cogs", "fees", "currency")
NUMBERS = ("qty", "net_revenue", "net_cogs", "fees")


def read_local(root: Path, filename: str) -> bytes:
    if not re.fullmatch(r"[A-Za-z0-9А-Яа-яЁё_. -]{1,160}\.csv", filename):
        raise SafeError("INPUT: provide a CSV basename from CLOUDRU_IMPORT_DIR, no directories")
    path = root / filename
    if path.is_symlink() or path.resolve().parent != root.resolve():
        raise SafeError("ACCESS: file is outside the import directory")
    try:
        with path.open("rb") as f:
            data = f.read(MAX_BYTES + 1)
    except OSError:
        raise SafeError("INPUT: CSV file unavailable in import directory") from None
    if len(data) > MAX_BYTES:
        raise SafeError("LIMIT: CSV exceeds 5 MB")
    return data


def parse(data: bytes):
    if len(data) > MAX_BYTES:
        raise SafeError("LIMIT: CSV exceeds 5 MB")
    try:
        reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")), strict=True)
        if reader.fieldnames != list(FIELDS):
            raise SafeError("SCHEMA: required CSV header: " + ",".join(FIELDS))
        rows, seen = [], set()
        for number, raw in enumerate(reader, 2):
            if number > MAX_ROWS + 1:
                raise SafeError("LIMIT: CSV exceeds 10000 rows")
            if None in raw or any(v is None for v in raw.values()):
                raise SafeError(f"CSV row {number}: column count mismatch")
            row = {k: v.strip() for k, v in raw.items()}
            if any(not v or len(v) > 256 or any(ord(c) < 32 for c in v) for v in row.values()):
                raise SafeError(f"CSV row {number}: missing, oversized or control-character value")
            if row['line_id'] in seen:
                raise SafeError(f"CSV row {number}: duplicate line_id within snapshot")
            seen.add(row['line_id'])
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row['date']):
                raise SafeError(f"CSV row {number}: date must be YYYY-MM-DD")
            try:
                dt = date.fromisoformat(row['date'])
                if not date(1970, 1, 1) <= dt <= date(2100, 12, 31):
                    raise ValueError
                for key in NUMBERS:
                    if not re.fullmatch(r"-?\d{1,12}(\.\d{1,2})?", row[key]):
                        raise ValueError
                    value = Decimal(row[key])
                    row[key] = format(value.quantize(Decimal(".01")), "f")
            except (ValueError, InvalidOperation):
                raise SafeError(f"CSV row {number}: invalid date or decimal (max two decimal places)") from None
            if row['currency'] != 'RUB':
                raise SafeError(f"CSV row {number}: only RUB is supported; convert currencies before import")
            rows.append(row)
    except (UnicodeError, csv.Error):
        raise SafeError("CSV: expected valid UTF-8 comma-separated CSV") from None
    if not rows:
        raise SafeError("EMPTY: snapshot must contain at least one row")
    return rows


def snapshot_id(data: bytes):
    return hashlib.sha256(data).hexdigest()


def summary(rows):
    totals = {k: sum((Decimal(r[k]) for r in rows), Decimal(0)) for k in NUMBERS}
    contribution = totals['net_revenue'] - totals['net_cogs'] - totals['fees']
    pct = contribution / totals['net_revenue'] * 100 if totals['net_revenue'] else None
    return {"rows": len(rows), "currency": "RUB", **{k: str(v) for k,v in totals.items()},
            "contribution": str(contribution), "margin_pct": str(pct.quantize(Decimal('.01'))) if pct is not None else None}


def validate_snapshot_id(value):
    if not re.fullmatch(r"[a-f0-9]{64}", value):
        raise SafeError("INPUT: snapshot_id must be the SHA-256 returned by preview/upload")
    return value
