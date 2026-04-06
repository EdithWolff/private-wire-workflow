import argparse
from pathlib import Path
from typing import Dict, List

from openpyxl import Workbook

from private_wire_workflow.filing_text_assessment import (
    assess_ratio_thresholds,
    compute_ratio_assessment_from_text,
    normalize_company_name,
)


from private_wire_workflow.report_utils import NO_INFO, fmt_number as _format_number, fmt_pct as _format_pct, ratio_flags as _ratio_flags

BASE_DIR = Path(__file__).resolve().parents[1]
DEFAULT_TXT_DIR = BASE_DIR / "data" / "filing_texts" / "plastic"
DEFAULT_OUTPUT_XLSX = BASE_DIR / "data" / "plastic_bankability.xlsx"
DISPLAY_NAME_SOURCE = BASE_DIR / "data" / "inputs" / "plastic_company_names.txt"


def _load_display_names(source_path: Path) -> Dict[str, str]:
    if not source_path.exists():
        return {}

    mapping: Dict[str, str] = {}
    for line in source_path.read_text(encoding="utf-8").splitlines():
        company_name = line.strip()
        if company_name:
            mapping[normalize_company_name(company_name)] = company_name
    return mapping


def _parse_txt_filename(path: Path) -> Dict[str, str]:
    parts = path.stem.split("__")
    if len(parts) < 3:
        return {
            "normalized_company_name": path.stem,
            "filing_year": NO_INFO,
            "company_number": NO_INFO,
        }
    return {
        "normalized_company_name": parts[0],
        "filing_year": parts[1] or NO_INFO,
        "company_number": parts[2] or NO_INFO,
    }


def _build_final_check(flags: Dict[str, str], ratio_result: str) -> str:
    if ratio_result == "Yes":
        return "Qualified: EBITDA Margin passed; Interest Coverage passed; Net Debt/EBITDA passed"
    if ratio_result == "No":
        outcomes = [
            ("EBITDA Margin", flags["margin_ge_10"]),
            ("Interest Coverage", flags["coverage_ge_3x"]),
            ("Net Debt/EBITDA", flags["netdebt_ebitda_le_2x"]),
        ]
        return "; ".join(f"{label} {'passed' if value == 'Yes' else 'failed'}" for label, value in outcomes)

    missing_checks = [
        label
        for label, value in [
            ("EBITDA Margin", flags["margin_ge_10"]),
            ("Interest Coverage", flags["coverage_ge_3x"]),
            ("Net Debt/EBITDA", flags["netdebt_ebitda_le_2x"]),
        ]
        if value == NO_INFO
    ]
    return f"Could not fully qualify: missing {'; '.join(missing_checks)} checks"


def _build_notes(metrics: Dict[str, float], ratio_result: str) -> str:
    missing = [
        label
        for label in ["turnover", "ebitda", "interest_expense", "debt", "cash", "net_debt"]
        if metrics.get(label) is None
    ]
    if ratio_result == NO_INFO:
        if missing:
            return f"Missing values: {', '.join(missing)}"
        return NO_INFO
    if ratio_result == "Yes":
        return "All ratio thresholds met"
    return "One or more ratio thresholds failed"


def build_workbook(
    txt_dir: Path = DEFAULT_TXT_DIR,
    output_xlsx: Path = DEFAULT_OUTPUT_XLSX,
) -> Path:
    display_names = _load_display_names(DISPLAY_NAME_SOURCE)
    txt_files: List[Path] = sorted(txt_dir.glob("*.txt"))

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "plastic bankability"

    headers = [
        "company_name",
        "txt_file_name",
        "txt_file_path",
        "company_number",
        "filing_year",
        "turnover",
        "ebitda",
        "interest_expense",
        "debt",
        "cash",
        "net_debt",
        "ebitda_margin",
        "interest_coverage",
        "net_debt_to_ebitda",
        "margin_ge_10",
        "coverage_ge_3x",
        "netdebt_ebitda_le_2x",
        "q2_ratio_test_result",
        "final_check",
        "notes",
    ]
    sheet.append(headers)

    for txt_path in txt_files:
        metadata = _parse_txt_filename(txt_path)
        text = txt_path.read_text(encoding="utf-8", errors="ignore")
        metrics = compute_ratio_assessment_from_text(text)
        flags = _ratio_flags(metrics)
        ratio_result = assess_ratio_thresholds(metrics)
        normalized_name = metadata["normalized_company_name"]
        company_name = display_names.get(
            normalized_name,
            normalized_name.replace("_", " "),
        )

        row = [
            company_name,
            txt_path.name,
            str(txt_path),
            metadata["company_number"],
            metadata["filing_year"],
            _format_number(metrics.get("turnover")),
            _format_number(metrics.get("ebitda")),
            _format_number(metrics.get("interest_expense")),
            _format_number(metrics.get("debt")),
            _format_number(metrics.get("cash")),
            _format_number(metrics.get("net_debt")),
            _format_pct(metrics.get("ebitda_margin")),
            _format_number(metrics.get("interest_coverage")),
            _format_number(metrics.get("net_debt_to_ebitda")),
            flags["margin_ge_10"],
            flags["coverage_ge_3x"],
            flags["netdebt_ebitda_le_2x"],
            ratio_result,
            _build_final_check(flags, ratio_result),
            _build_notes(metrics, ratio_result),
        ]
        sheet.append(row)

    output_xlsx.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(output_xlsx)
    return output_xlsx


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Build a ratio-focused Excel workbook from the plastic company OCR text files."
    )
    parser.add_argument(
        "--txt-dir",
        type=Path,
        default=DEFAULT_TXT_DIR,
        help="Directory containing the OCR text files to analyze.",
    )
    parser.add_argument(
        "--output-xlsx",
        type=Path,
        default=DEFAULT_OUTPUT_XLSX,
        help="Workbook path to write.",
    )
    args = parser.parse_args()
    print(build_workbook(txt_dir=args.txt_dir, output_xlsx=args.output_xlsx))
