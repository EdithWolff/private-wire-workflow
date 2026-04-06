# Private Wire Workflow

Screens companies for private wire solar PPA opportunities by fetching Companies House filings, OCR-extracting financial data, and answering five bankability and signal questions per company.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Add your Companies House API key to `.env.local`:

```
COMPANIES_HOUSE_API_KEY=your_key_here
```

## Primary workflow

Run the full assessment for all companies in `data/company_rating_screening_findings.csv`:

```bash
PYTHONPATH=src python3 scripts/build_company_filing_text_assessment.py
```

Test with a small batch first:

```bash
PYTHONPATH=src python3 scripts/build_company_filing_text_assessment.py --limit 3
```

Outputs:
- `data/filing_texts/*.txt` — OCR-extracted filing text, one file per company
- `data/company_filing_text_assessment.csv` — full assessment results with ratios and Q1–Q5 answers

## AI rating review

After filing texts are extracted, use the Claude slash commands:

```
/rating abbvie_inc__2025__08004972.txt     # analyse one company
/batch-rating                               # analyse next 3 unanalyzed companies
/batch-rating 5                            # analyse next 5
/batch-rating status                       # show progress
```

Results are tracked in `data/rating_log.json`.

## Other scripts

| Script | Purpose |
|---|---|
| `run_company_bankability_master.py` | Parallel multi-threaded pipeline with checkpointing — use for large batches |
| `build_pharma_case_by_case.py` | Pharma-specific batch processor with per-company timeout |
| `build_plastic_company_filing_texts.py` | OCR batch for plastic industry companies |
| `build_plastic_bankability_workbook.py` | Bankability workbook for plastic company filing texts |
| `compare_ocr_on_one_filing.py` | Dev tool: compare OCR engines on a single filing |

## Tests

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Directory structure

```
data/
  company_rating_screening_findings.csv   # input: 60 companies with ratings
  plastic_company_names.txt               # input: plastic industry batch
  filing_texts/                           # output: OCR filing text files
  templates/                              # CSV templates for screening tabs
  rating_log.json                         # AI rating review progress tracker
  company_filing_text_assessment.csv      # output: full assessment results
docs/
  workflow.md                             # operating model and workflow rules
instructions.md                          # filing text assessment instructions
scripts/                                 # runnable entry points
src/private_wire_workflow/               # library package
tests/                                   # unit tests
.github/prompts/                         # Claude slash commands (/rating, /batch-rating)
```

## Notes

- The API key loads automatically from `.env.local` — no need to `export` manually.
- Companies House does not provide credit ratings or revenue in the company profile API. Ratings must come from the filing text itself or an external source.
- The filing text OCR stage extracts text only. Financial interpretation is done separately by the AI rating commands.
- Official credit ratings are only recorded when explicitly stated in the filing text. Ratio-based views are clearly labelled as AI analysis, not official ratings.
