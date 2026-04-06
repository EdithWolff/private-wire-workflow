---
name: "Rating"
description: "Analyse a Companies House OCR filing text from data/filing_texts/ and produce a structured bankability scorecard covering Q1–Q5: official rating, ratio test, electricity signal, sustainability targets, and PPA experience."
argument-hint: "Filing text filename, company name, or path — e.g. 'abbvie_inc__2025__08004972.txt' or 'AbbVie'. Omit to use open file or current context."
agent: "agent"
---

## Step 1 — Locate the filing text

1. If the user supplied a filename or path, use that file from `data/filing_texts/`.
2. If the user supplied a bare filename, treat it as relative to `data/filing_texts/`.
3. If the user supplied a company name or partial name, find the best match in `data/filing_texts/`. If ambiguous, ask a brief clarifying question.
4. If no argument, use the open file, selected text, or current chat context.
5. If no filing text is available, ask the user to specify a file from `data/filing_texts/`.

State the filename used at the top of your answer.

---

## Step 2 — Extract financial values

From the filing text, extract:

- **Turnover** (also: revenue, sales)
- **EBITDA** (if not stated, derive as Operating Profit + Depreciation + Amortisation — state clearly if derived)
- **Interest Expense** (also: finance costs, interest payable)
- **Debt** (also: borrowings, loans)
- **Cash** (also: cash at bank, cash equivalents)
- **Net Debt** (if not stated, derive as Debt − Cash — state clearly if derived)

Rules:
- Prefer values stated directly in the filing text.
- Note the unit (£000s, £m, etc.) and state it explicitly.
- If a value is ambiguous or appears multiple times, use the most prominent figure and note the ambiguity.
- If a value cannot be found, record it as `No information found`. Do not invent figures.

---

## Step 3 — Calculate ratios

| Ratio | Formula | Threshold |
|---|---|---|
| EBITDA Margin | EBITDA ÷ Turnover | ≥ 10% to pass |
| Interest Coverage | EBITDA ÷ Interest Expense | ≥ 3x to pass |
| Net Debt / EBITDA | Net Debt ÷ EBITDA | ≤ 2x to pass |

If any input value is missing, the ratio result is `No information found`.

---

## Step 4 — Answer Q1–Q5

**Q1 — Official Credit Rating**
- Only record an official rating if it is explicitly stated in the filing text (e.g. "Standard & Poor's rating of BBB+").
- Do not infer a rating from ratios, narrative, or financial strength alone.
- Answer: `Yes — [rating]` if ≥ BBB-, `No — [rating]` if explicitly below BBB-, or `No information found`.

**Q2 — Ratio Test**
- Answer `Yes` only if ALL THREE ratios pass their thresholds.
- Answer `No` if all required values exist but one or more ratios fail.
- Answer `No information found` if one or more required values are missing.

**Q3 — Electricity Consumption Signal**
- Look for explicit electricity consumption figures in the text.
- Thresholds: total ≥ 30 GWh, or per-site ≥ 8 GWh.
- Answer `Yes`, `No`, or `No information found`.

**Q4 — Sustainability / Renewable Target Signal**
- Look for explicit commitments: net zero, SBTi, RE100, renewable energy targets, carbon reduction targets.
- Answer `Yes` (with a brief quote) or `No information found`.

**Q5 — Previous PPA Experience**
- Look for explicit mentions of Power Purchase Agreements (wind or solar PPAs).
- Answer `Yes` (with a brief quote) or `No information found`.

---

## Output format

### [Company Name] — `[filename]`

#### Bankability Scorecard

| # | Check | Threshold | Result | Value |
|---|---|---|---|---|
| Q1 | Official Credit Rating | ≥ BBB- | [Yes / No / No information found] | [rating or —] |
| Q2a | EBITDA Margin | ≥ 10% | [Pass / Fail / No information found] | [X.X%] |
| Q2b | Interest Coverage | ≥ 3x | [Pass / Fail / No information found] | [X.Xx] |
| Q2c | Net Debt / EBITDA | ≤ 2x | [Pass / Fail / No information found] | [X.Xx] |
| **Q2** | **Ratio Test (all three)** | All pass | **[Yes / No / No information found]** | |
| Q3 | Electricity Consumption | ≥ 30 GWh total or ≥ 8 GWh/site | [Yes / No / No information found] | [figure or —] |
| Q4 | Sustainability Target | Any commitment | [Yes / No information found] | [brief quote or —] |
| Q5 | PPA Experience | Any PPA | [Yes / No information found] | [brief quote or —] |

**Overall verdict:** `Bankable` / `Not bankable` / `Needs review`

Use this logic:
- `Bankable` — Q2 = Yes (all ratios pass), or Q1 = Yes (explicit investment-grade rating)
- `Not bankable` — Q2 = No AND Q1 = No or No information found
- `Needs review` — Q2 = No information found (missing values), or Q1 and Q2 are mixed

---

#### Extracted Financials

| Item | Value | Unit | Notes |
|---|---|---|---|
| Turnover | | | |
| EBITDA | | | |
| Interest Expense | | | |
| Debt | | | |
| Cash | | | |
| Net Debt | | | |

---

#### Ratio-Based Credit View

One paragraph explaining what the ratios indicate about credit quality. Do not label this as an official rating. Highlight any red flags or strengths.

---

#### Evidence

Quote the exact filing text snippets used for each extracted figure. Keep quotes concise.

---

#### CSV Row

Output a single CSV row that can be appended directly to `data/company_filing_text_assessment.csv`.

First, output the header line (only needed when adding a new company not already in the file):
```
company_name,matched_entity_name,company_number,entity_match_score,entity_confidence,matched_query,runner_up_score,filing_date,filing_description,filing_confidence,filing_type,filing_attempts,txt_file_path,page_count,ocr_engine,ocr_runtime_sec,ocr_char_count,txt_quality_status,txt_quality_score,txt_quality_flags,turnover,ebitda,interest_expense,debt,cash,net_debt,ebitda_margin,interest_coverage,net_debt_to_ebitda,q1_investment_grade_from_filing_text,q2_ratio_test_result,q3_electricity_consumption_signal,q4_sustainability_target_signal,q5_previous_ppa_signal,evidence_snippets,notes,no_information_flags
```

Then output the data row. Rules:
- Use the company name exactly as it appears in the filename.
- Fields not derivable from the filing text alone (matched_entity_name, company_number, entity_match_score, entity_confidence, matched_query, runner_up_score, filing_date, filing_description, filing_confidence, filing_type, filing_attempts, page_count, ocr_engine, ocr_runtime_sec, ocr_char_count, txt_quality_status, txt_quality_score, txt_quality_flags) should be left blank.
- txt_file_path: the relative path used, e.g. `data/filing_texts/abbvie_inc__2025__08004972.txt`.
- Financial values (turnover, ebitda, interest_expense, debt, cash, net_debt): raw numbers only, no units or commas. Leave blank if not found.
- Ratio values (ebitda_margin, interest_coverage, net_debt_to_ebitda): decimal form (e.g. 0.142 not 14.2%). Leave blank if not calculable.
- Q1–Q5 fields: use exactly `Yes`, `No`, or `No information found`.
- evidence_snippets: pipe-separated short quotes, e.g. `Turnover: £142m | EBITDA: £20m`.
- notes: brief extraction notes, e.g. `EBITDA derived | unit=£000s`.
- no_information_flags: semicolon-separated list of missing fields, e.g. `q3;missing_debt;missing_cash`. Empty string if nothing is missing.
- Wrap any field containing commas in double quotes.

```csv
[data row here]
```

Also output a JSON snippet ready to be merged into `data/rating_log.json`:

```json
{
  "[company_name]": {
    "status": "done",
    "analyzed_date": "[today YYYY-MM-DD]",
    "file": "data/filing_texts/[filename]",
    "turnover": [number or null],
    "ebitda": [number or null],
    "interest_expense": [number or null],
    "debt": [number or null],
    "cash": [number or null],
    "net_debt": [number or null],
    "ebitda_margin_pct": [number or null],
    "interest_coverage": [number or null],
    "net_debt_to_ebitda": [number or null],
    "q1_investment_grade": "[Yes|No|No information found]",
    "q2_ratio_test": "[Yes|No|No information found]",
    "q3_electricity": "[Yes|No|No information found]",
    "q4_sustainability": "[Yes|No information found]",
    "q5_ppa": "[Yes|No information found]",
    "official_rating_text": "[quoted text or null]",
    "credit_view_summary": "[one sentence]",
    "notes": "[unit and extraction notes]"
  }
}
```
