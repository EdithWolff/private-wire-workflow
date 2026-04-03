# Private Wire Workflow Toolkit

This repository turns the sales workflow into a reusable operating toolkit for:

- bankability screening
- site screening
- contact enrichment preparation
- outreach handoff preparation
- repeatable QA checks

The implementation is intentionally lightweight and dependency-free so it can run on a blank machine with the Python standard library only.

## What is included

- A documented workflow and operating guidance in [docs/workflow.md](/Users/ssebl/Documents/New project/docs/workflow.md)
- CSV templates for the Excel tabs in [data/templates/account_screening_template.csv](/Users/ssebl/Documents/New project/data/templates/account_screening_template.csv) and [data/templates/site_screening_template.csv](/Users/ssebl/Documents/New project/data/templates/site_screening_template.csv)
- A Python package in [src/private_wire_workflow](/Users/ssebl/Documents/New project/src/private_wire_workflow) that:
  - scores bankability
  - ranks sites
  - deduplicates and filters contacts
  - builds outreach-ready account summaries
  - validates workflow data quality
- A workbook enrichment script in [scripts/fill_batch2_companies_house.py](/Users/ssebl/Documents/New project/scripts/fill_batch2_companies_house.py) for the `Batch 2 account screening` tab
- A filing-ratio exporter in [scripts/export_batch2_filing_bankability_csv.py](/Users/ssebl/Documents/New project/scripts/export_batch2_filing_bankability_csv.py) that attempts to calculate bankability from filings
- A final Excel builder in [scripts/build_bankability_screening_workbook.py](/Users/ssebl/Documents/New project/scripts/build_bankability_screening_workbook.py) that applies `official rating first`, then filing fallback
- A filing-text assessment builder in [scripts/build_company_filing_text_assessment.py](/Users/ssebl/Documents/New project/scripts/build_company_filing_text_assessment.py) that uses Tesseract OCR on full accounts filings and answers workflow questions in a consolidated CSV
- Executable regression tests in [tests](/Users/ssebl/Documents/New project/tests)

## Quick start

Run the test suite:

```bash
python3 -m unittest discover -s tests -v
```

Run the sample workflow on the included templates:

```bash
PYTHONPATH=src python3 -m private_wire_workflow.cli
```

Populate the `Batch 2 account screening` workbook with Companies House entity matches:

```bash
export COMPANIES_HOUSE_API_KEY=your_key_here
PYTHONPATH=src python3 scripts/fill_batch2_companies_house.py
```

Export filing-derived bankability ratios for a small batch:

```bash
export COMPANIES_HOUSE_API_KEY=your_key_here
PYTHONPATH=src python3 scripts/export_batch2_filing_bankability_csv.py --start-row 2 --max-rows 25
```

Build the final bankability workbook:

```bash
export COMPANIES_HOUSE_API_KEY=your_key_here
PYTHONPATH=src python3 scripts/build_bankability_screening_workbook.py
```

Build filing-text-only assessment outputs:

```bash
export COMPANIES_HOUSE_API_KEY=your_key_here
PYTHONPATH=src python3 scripts/build_company_filing_text_assessment.py
```

Run the parallel resumable OCR + bankability master workbook pipeline:

```bash
export COMPANIES_HOUSE_API_KEY=your_key_here
PYTHONPATH=src python3 scripts/run_company_bankability_master.py --max-workers 5
```

## Operating model

1. Work from the `Batch 2 account screening` template.
2. Screen bankability first.
3. Screen sites only for `Bankable` or `Needs review` accounts.
4. Add the best 1-3 sites to the `Batch 2 site screening` handoff.
5. Enrich 5 target contacts.
6. Prepare outreach-ready data for Salesforce and Slack.

## Notes

- Companies House and Searchland lookups are represented as structured inputs in this repository.
- The Companies House enrichment script writes a copy of the workbook and does not modify the original file in place.
- Companies House does not expose public credit ratings or a ready-to-use revenue field in the company profile API, so those fields still require an external rating source or accounts-document review.
- The filing-ratio exporter now attempts PDF text extraction as well, but still flags accounts as `Needs review` when the PDF text is too poor or the required financial fields cannot be recovered safely.
