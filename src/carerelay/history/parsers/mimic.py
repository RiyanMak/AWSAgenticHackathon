"""Parse MIMIC-IV (demo) hosp tables for one subject into a HistoryProfile.

Reads ``patients``, ``diagnoses_icd`` + ``d_icd_diagnoses``, ``prescriptions`` and
``procedures_icd`` + ``d_icd_procedures`` from a directory holding either ``.csv`` or ``.csv.gz``
files. The demo has no allergy table, so allergies come from the intake form.

MIMIC-IV demo is ODbL-licensed; see data/samples/history/README.md for attribution.
"""

from __future__ import annotations

import csv
import gzip
import io
from collections import OrderedDict
from pathlib import Path
from typing import Iterator

from ..risk_flags import derive_risk_flags
from ..schema import CodedItem, HistoryProfile, PatientSummary


def _open_table(data_dir: Path, name: str) -> io.TextIOBase | None:
    for candidate in (data_dir / f"{name}.csv", data_dir / f"{name}.csv.gz", data_dir / "hosp" / f"{name}.csv", data_dir / "hosp" / f"{name}.csv.gz"):
        if candidate.exists():
            if candidate.suffix == ".gz":
                return gzip.open(candidate, "rt", newline="")
            return open(candidate, "rt", newline="")
    return None


def _rows(data_dir: Path, name: str) -> Iterator[dict[str, str]]:
    fh = _open_table(data_dir, name)
    if fh is None:
        return iter(())
    return _iter_close(fh)


def _iter_close(fh: io.TextIOBase) -> Iterator[dict[str, str]]:
    try:
        yield from csv.DictReader(fh)
    finally:
        fh.close()


def _icd_system(version: str, kind: str) -> str:
    if kind == "dx":
        return "icd10cm" if version.strip() == "10" else "icd9cm"
    return "icd10pcs" if version.strip() == "10" else "icd9pcs"


def _lookup_titles(data_dir: Path, table: str, wanted: set[tuple[str, str]]) -> dict[tuple[str, str], str]:
    titles: dict[tuple[str, str], str] = {}
    if not wanted:
        return titles
    for row in _rows(data_dir, table):
        key = (row["icd_code"].strip(), row["icd_version"].strip())
        if key in wanted:
            titles[key] = row["long_title"]
            if len(titles) == len(wanted):
                break
    return titles


def parse_mimic_subject(data_dir: str | Path, subject_id: int | str) -> HistoryProfile:
    """Build a HistoryProfile for ``subject_id`` from MIMIC-IV hosp tables in ``data_dir``."""
    data_dir = Path(data_dir)
    sid = str(subject_id).strip()
    profile = HistoryProfile(source="csv")

    if _open_table(data_dir, "diagnoses_icd") is None:
        profile.source = "degraded"
        profile.warnings.append(f"No diagnoses_icd table found under {data_dir}")
        return profile

    # Patient
    for row in _rows(data_dir, "patients"):
        if row["subject_id"] == sid:
            profile.patient = PatientSummary(
                patient_id=sid,
                gender=row.get("gender") or None,
                age_years=int(row["anchor_age"]) if row.get("anchor_age") else None,
            )
            break

    # Diagnoses: one entry per distinct code, most recent admission wins the source_ref
    dx: "OrderedDict[tuple[str, str], dict[str, str]]" = OrderedDict()
    for row in _rows(data_dir, "diagnoses_icd"):
        if row["subject_id"] != sid:
            continue
        key = (row["icd_code"].strip(), row["icd_version"].strip())
        dx.setdefault(key, row)
    titles = _lookup_titles(data_dir, "d_icd_diagnoses", set(dx))
    for key, row in dx.items():
        code, version = key
        profile.conditions.append(
            CodedItem(
                display=titles.get(key, f"ICD-{version} {code}"),
                code=code,
                system=_icd_system(version, "dx"),
                status="active",  # MIMIC diagnoses are billing codes per admission; treat as active history
                source_ref=f"diagnoses_icd hadm_id={row['hadm_id']} seq={row['seq_num']}",
            )
        )

    # Prescriptions are inpatient orders and every one has a stoptime, so "active" is defined as
    # "ordered during the most recent admission" (the closest thing to a current regimen in MIMIC).
    rx_rows = [r for r in _rows(data_dir, "prescriptions") if r["subject_id"] == sid and (r.get("drug") or "").strip()]
    latest_hadm = None
    if rx_rows:
        latest_hadm = max(rx_rows, key=lambda r: r.get("starttime") or "")["hadm_id"]
    rx: "OrderedDict[str, CodedItem]" = OrderedDict()
    for row in rx_rows:
        drug = row["drug"].strip()
        key = drug.lower()
        status = "active" if row["hadm_id"] == latest_hadm else "stopped"
        strength = " ".join(filter(None, [row.get("prod_strength"), row.get("route")])).strip() or None
        item = rx.get(key)
        if item is None:
            rx[key] = CodedItem(
                display=drug,
                code=(row.get("ndc") or "").strip() or None,
                system="text",
                status=status,
                onset=(row.get("starttime") or "")[:10] or None,
                detail=strength,
                source_ref=f"prescriptions hadm_id={row['hadm_id']} pharmacy_id={row.get('pharmacy_id', '')}",
            )
        else:
            if status == "active":
                item.status = "active"
                item.source_ref = f"prescriptions hadm_id={row['hadm_id']} pharmacy_id={row.get('pharmacy_id', '')}"
            if (row.get("starttime") or "")[:10] > (item.onset or ""):
                item.onset = row["starttime"][:10]
    profile.medications = list(rx.values())
    if latest_hadm:
        profile.warnings.append(f"MIMIC medications marked active are the orders from the latest admission (hadm_id={latest_hadm})")

    # Procedures
    px: "OrderedDict[tuple[str, str], dict[str, str]]" = OrderedDict()
    for row in _rows(data_dir, "procedures_icd"):
        if row["subject_id"] != sid:
            continue
        key = (row["icd_code"].strip(), row["icd_version"].strip())
        px.setdefault(key, row)
    ptitles = _lookup_titles(data_dir, "d_icd_procedures", set(px))
    for key, row in px.items():
        code, version = key
        profile.procedures.append(
            CodedItem(
                display=ptitles.get(key, f"ICD-{version} procedure {code}"),
                code=code,
                system=_icd_system(version, "px"),
                status="completed",
                onset=(row.get("chartdate") or "")[:10] or None,
                source_ref=f"procedures_icd hadm_id={row['hadm_id']} seq={row['seq_num']}",
            )
        )

    profile.warnings.append("MIMIC-IV has no allergy table; allergies must come from the intake form")
    if not profile.conditions and not profile.medications:
        profile.source = "degraded"
        profile.warnings.append(f"No diagnoses or prescriptions found for subject_id={sid}")
    profile.risk_flags = derive_risk_flags(profile)
    return profile
