---
name: "Rating"
description: "Use when you want AI to extract key financial ratios from an OCR filing text file, optionally targeting a specific file in data/filing_texts, and give a ratio-based credit view without assuming any official credit rating unless the text explicitly states one"
argument-hint: "Optional filing text path, filename, or focus such as 'company__2024__12345678.txt' or 'show all calculations'"
agent: "agent"
---
Using the current chat context, the slash-command argument, selected text, or the open OCR-extracted filing `.txt` file, do the following:

1. If the user supplied a specific filing text filename or path, use that file from `data/filing_texts/` as the primary source.
2. If the user supplied only a bare filename, treat it as relative to `data/filing_texts/`.
3. If the user supplied a company name or partial filename, identify the best match in `data/filing_texts/`; if the match is ambiguous, ask a brief clarifying question.
4. If no file argument was supplied, use the open OCR-extracted filing `.txt` file, selected text, or current chat context.
5. If no filing text is available, ask the user to open, paste, or specify a file from `data/filing_texts/`.

Then:

1. Extract the key financial values relevant to a ratio-based credit assessment.
2. Prefer values stated directly in the filing text. If a value is ambiguous, say so clearly.
3. Calculate, where possible:
   - EBITDA margin = EBITDA / Turnover
   - Interest coverage = EBITDA / Interest Expense
   - Net debt to EBITDA = (Debt - Cash) / EBITDA
4. If a required value is missing, do not invent it. State `No information found` for that value or ratio.
5. Separate two concepts clearly:
   - Official credit rating mentioned in the text
   - AI ratio-based credit view inferred from the extracted figures
6. Never claim there is an official credit rating unless the OCR text explicitly states one.

Return the answer in this structure:

## Official Rating Mention
- State whether the filing text explicitly mentions an official credit rating.
- If yes, quote the relevant wording.
- If not, say `No information found`.

## Extracted Values
- Turnover
- EBITDA
- Interest Expense
- Debt
- Cash
- Net Debt

## Calculated Ratios
- EBITDA Margin
- Interest Coverage
- Net Debt / EBITDA

## Ratio-Based Credit View
- Explain whether the ratios indicate stronger, weaker, or mixed credit quality.
- Do not label this as an official rating.

## Evidence
- Quote the exact filing text snippets used for each extracted figure where possible.

When a specific file was requested, state which file was used at the top of the answer.