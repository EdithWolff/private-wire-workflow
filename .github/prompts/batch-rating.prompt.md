---
name: "Batch Rating"
description: "Run /rating analysis across multiple filing text files in data/filing_texts/, skipping already-analyzed companies. Tracks progress in data/rating_log.json."
argument-hint: "Optional: number of companies to process this run (default 3), e.g. '5' or 'all'. Pass 'status' to see progress without processing."
agent: "agent"
---

## Setup

1. Read `data/rating_log.json` if it exists. If it does not exist, treat the log as an empty object `{}`.
2. List all `.txt` files in `data/filing_texts/`.
3. Determine which files have NOT yet been analyzed (i.e. their filename stem is not a key in the log with `"status": "done"`).

## Argument handling

- If the argument is `status` or `progress`: print the progress summary (see below) and stop — do not process any files.
- If the argument is a number (e.g. `5`): process that many unanalyzed files this run.
- If the argument is `all`: process every remaining unanalyzed file. Only do this if there are 5 or fewer remaining — otherwise warn the user and ask them to confirm.
- If no argument: default to processing **3** unanalyzed files.

Always prefer smaller files first (under 100KB) unless the user specifies otherwise, to stay within context limits. If all remaining files are large (over 100KB), process 1 at a time and warn the user.

## For each file to process

Read the file and apply the full `/rating` analysis:

1. Extract: Turnover, EBITDA, Interest Expense, Debt, Cash, Net Debt
2. Calculate: EBITDA Margin, Interest Coverage, Net Debt / EBITDA
3. Assess Q1–Q5:
   - `q1_investment_grade`: Is there an explicit credit rating ≥ BBB- in the text? (`Yes` / `No` / `No information found`)
   - `q2_ratio_test`: Do all three ratio thresholds pass — EBITDA Margin ≥ 10%, Interest Cover ≥ 3x, Net Debt/EBITDA ≤ 2? (`Yes` / `No` / `No information found`)
   - `q3_electricity`: Electricity consumption ≥ 30 GWh total or ≥ 8 GWh per site? (`Yes` / `No` / `No information found`)
   - `q4_sustainability`: Explicit renewable/sustainability targets? (`Yes` / `No information found`)
   - `q5_ppa`: Prior PPA experience (wind or solar)? (`Yes` / `No information found`)
4. Write a one-sentence credit view summary.
5. Never claim an official credit rating unless it is explicitly stated in the filing text.

## After processing each file

Update `data/rating_log.json` immediately after each company (do not wait until the end). Add or update the entry:

```json
{
  "<filename_stem>": {
    "status": "done",
    "analyzed_date": "<today's date as YYYY-MM-DD>",
    "file": "data/filing_texts/<filename>",
    "turnover": <number or null>,
    "ebitda": <number or null>,
    "interest_expense": <number or null>,
    "debt": <number or null>,
    "cash": <number or null>,
    "net_debt": <number or null>,
    "ebitda_margin_pct": <number or null>,
    "interest_coverage": <number or null>,
    "net_debt_to_ebitda": <number or null>,
    "q1_investment_grade": "<Yes|No|No information found>",
    "q2_ratio_test": "<Yes|No|No information found>",
    "q3_electricity": "<Yes|No|No information found>",
    "q4_sustainability": "<Yes|No information found>",
    "q5_ppa": "<Yes|No information found>",
    "official_rating_text": "<quoted text or null>",
    "credit_view_summary": "<one sentence>",
    "notes": "<any caveats about extraction quality>"
  }
}
```

Store all financial figures in the original unit found in the filing (state the unit in `notes` if it is thousands or millions).

## Output format

After each company, print a compact result block:

```
### [Company Name] — <filename>
- Turnover: X | EBITDA: X | Interest Expense: X | Net Debt: X
- EBITDA Margin: X% | Interest Cover: Xx | Net Debt/EBITDA: X
- Q1 (rating): X | Q2 (ratios): X | Q3 (electricity): X | Q4 (sustainability): X | Q5 (PPA): X
- Credit view: <one sentence>
- Notes: <extraction caveats if any>
```

## Progress summary

At the end of each run (and when `status` argument is used), print:

```
## Batch Rating Progress
- Total files in data/filing_texts/: X
- Analyzed: X
- Remaining: X
- Qualified (Q2=Yes): X
- Needs review (Q2=No information found): X
- Disqualified (Q2=No): X
```

List remaining filenames so the user knows what is left.
