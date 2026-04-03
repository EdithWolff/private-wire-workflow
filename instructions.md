# Filing Text-Only Assessment Instructions

## Purpose
This workflow processes companies from `data/company_rating_screening_findings.csv` (column `Company Name`), fetches the latest **non-dormant full accounts** filing from Companies House, OCR-extracts **all PDF pages using Tesseract**, saves one `.txt` file per company filing, and produces a consolidated assessment CSV.

All existing CSV files remain untouched. This workflow writes a new CSV.

## Inputs and Outputs

- Input CSV:
  - `data/company_rating_screening_findings.csv`
- Company column:
  - `Company Name`
- Output folder for OCR text files:
  - `data/filing_texts/`
- OCR text file naming convention:
  - `{normalized_company_name}__{filing_year}__{company_number}.txt`
- New consolidated CSV output:
  - `data/company_filing_text_assessment.csv`

## Filing Retrieval Rules

1. Resolve company legal entity using Companies House company search + profile.
2. Retrieve filing history and select:
   - latest filing in `accounts` category
   - must be `full` accounts
   - must **not** be `dormant` or `micro`
3. If no qualifying filing is found:
   - output row must still be written
   - all question answers must be `No information found`
4. Download filing via Companies House Document API as PDF.

## OCR and Text File Creation

1. Convert each PDF page to image.
2. OCR every page with Tesseract language `eng`.
3. Concatenate all page text in page order.
4. Save one `.txt` file per company filing in `data/filing_texts/`.
5. Record OCR metadata in CSV:
   - `page_count`
   - `ocr_engine`
   - `ocr_runtime_sec`
   - `ocr_char_count`

## Mandatory Questions and Answer Rules

All questions must be answered for every company. If information is missing, answer exactly:

- `No information found`

### Q1
`q1_investment_grade_from_filing_text`  
Question: Is the company investment grade (minimum BBB-) based on filing text only?

- Parse rating mentions from filing text only.
- Do not use rating values from existing CSV columns.
- Answer:
  - `Yes` if rating is `>= BBB-`
  - `No` if rating is explicitly below `BBB-`
  - `No information found` if no rating is found in text

### Q2
`q2_ratio_test_result`  
Question: Does company fulfill:
- EBITDA Margin `(EBITDA/Turnover) >= 10%`
- Interest Coverage `(EBITDA/Interest Expense) >= 3x`
- Net Debt / EBITDA `((Debt - Cash)/EBITDA) <= 2`

Raw values to extract from OCR text:
- `turnover`
- `ebitda`
- `interest_expense`
- `debt`
- `cash`
- `net_debt` (if absent, derive as `debt - cash`)

Answer:
- `Yes` if all three thresholds pass
- `No` if all required values exist but one or more fail
- `No information found` if required values are missing

### Q3
`q3_electricity_consumption_signal`  
Question: Minimum electricity consumption:
- total `>= 30 GWh`
- per site `>= 8 GWh`

Answer:
- `Yes` if both signals are supported in text
- `No` if explicit values found but thresholds not met
- `No information found` if consumption information is absent

### Q4
`q4_sustainability_target_signal`  
Question: Any renewable/sustainability targets that BtM solar can support and create urgency?

Answer:
- `Yes` if target/commitment is explicitly present
- `No information found` if absent

### Q5
`q5_previous_ppa_signal`  
Question: Any previous PPA experience (wind or solar)?

Answer:
- `Yes` if explicit PPA mention exists
- `No information found` if absent

## Consolidated CSV Schema

The workflow writes `data/company_filing_text_assessment.csv` with:

- Identity and filing:
  - `company_name`
  - `matched_entity_name`
  - `company_number`
  - `filing_date`
  - `filing_description`
  - `txt_file_path`
- OCR metadata:
  - `page_count`
  - `ocr_engine`
  - `ocr_runtime_sec`
  - `ocr_char_count`
- Raw extracted values:
  - `turnover`
  - `ebitda`
  - `interest_expense`
  - `debt`
  - `cash`
  - `net_debt`
- Calculated ratios:
  - `ebitda_margin`
  - `interest_coverage`
  - `net_debt_to_ebitda`
- Mandatory answers:
  - `q1_investment_grade_from_filing_text`
  - `q2_ratio_test_result`
  - `q3_electricity_consumption_signal`
  - `q4_sustainability_target_signal`
  - `q5_previous_ppa_signal`
- Traceability:
  - `evidence_snippets`
  - `notes`
  - `no_information_flags`

## Run Command

```bash
export COMPANIES_HOUSE_API_KEY='YOUR_KEY'
PYTHONPATH=src python3 scripts/build_company_filing_text_assessment.py
```

Optional limit for testing:

```bash
export COMPANIES_HOUSE_API_KEY='YOUR_KEY'
PYTHONPATH=src python3 scripts/build_company_filing_text_assessment.py --limit 10
```

## Quality and Validation

After running:

1. Confirm one output row per input company.
2. Confirm all 5 mandatory question fields are populated (`Yes`, `No`, or `No information found`).
3. Confirm `.txt` files are created in `data/filing_texts/` with correct naming.
4. Confirm existing CSV files were not modified.
