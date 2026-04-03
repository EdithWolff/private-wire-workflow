from typing import Dict, List


REQUIRED_ACCOUNT_FIELDS = [
    "account_name",
    "revenue_gbp",
    "uk_presence",
    "bankability_status",
    "next_action",
]

REQUIRED_SITE_FIELDS = [
    "account_name",
    "site_name",
    "site_size_sqm",
    "grade",
    "jonathan_qualification",
]


def validate_account_row(row: Dict[str, str]) -> List[str]:
    errors = []
    for field in REQUIRED_ACCOUNT_FIELDS:
        if not str(row.get(field, "")).strip():
            errors.append(f"Missing account field: {field}")
    revenue = str(row.get("revenue_gbp", "")).strip()
    if revenue:
        try:
            if float(revenue) <= 0:
                errors.append("Revenue must be positive.")
        except ValueError:
            errors.append("Revenue must be numeric.")
    return errors


def validate_site_row(row: Dict[str, str]) -> List[str]:
    errors = []
    for field in REQUIRED_SITE_FIELDS:
        if not str(row.get(field, "")).strip():
            errors.append(f"Missing site field: {field}")
    size = str(row.get("site_size_sqm", "")).strip()
    if size:
        try:
            if float(size) < 10_000:
                errors.append("Site size is below the 10,000 sqm threshold.")
        except ValueError:
            errors.append("Site size must be numeric.")
    return errors
