import argparse
import re
import time
from pathlib import Path

import fitz
import numpy as np
import pytesseract
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

try:
    import easyocr
except Exception:
    easyocr = None

from private_wire_workflow.companies_house import (
    download_document_content,
    find_best_match,
    get_api_key,
    list_accounts_filings,
    select_best_accounts_filing,
)


def _image_from_page(page: fitz.Page, scale: float = 2.0) -> np.ndarray:
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)


def _score_text(text: str) -> dict:
    keywords = [
        "turnover",
        "revenue",
        "ebitda",
        "operating profit",
        "finance costs",
        "interest",
        "borrowings",
        "cash",
        "net debt",
    ]
    return {
        "chars": len(text),
        "alnum_chars": len(re.findall(r"[A-Za-z0-9]", text)),
        "digit_chars": len(re.findall(r"\d", text)),
        "keyword_hits": sum(text.lower().count(keyword) for keyword in keywords),
    }


def run_comparison(company_name: str, max_pages: int, output_path: Path) -> Path:
    api_key = get_api_key()
    match = find_best_match(company_name, api_key)
    if not match:
        raise RuntimeError(f"No Companies House match found for: {company_name}")

    filings = list_accounts_filings(match.company_number, api_key)
    filing = select_best_accounts_filing(filings)
    if not filing or not filing.document_metadata_url:
        raise RuntimeError("No accounts filing with document metadata found.")

    content, source_format = download_document_content(filing.document_metadata_url, api_key)
    if source_format != "pdf":
        raise RuntimeError(f"Expected PDF filing, got: {source_format}")

    rapid = RapidOCR()
    easy_reader = easyocr.Reader(["en"], gpu=False) if easyocr is not None else None

    with fitz.open(stream=content, filetype="pdf") as pdf:
        pages = min(max_pages, len(pdf))
        rapid_lines = []
        tess_lines = []
        easy_lines = []

        t0 = time.time()
        for idx in range(pages):
            img_np = _image_from_page(pdf[idx], scale=1.8)
            rapid_result, _elapsed = rapid(img_np)
            if rapid_result:
                rapid_lines.extend(item[1] for item in rapid_result if len(item) >= 2)
        rapid_sec = time.time() - t0

        t0 = time.time()
        for idx in range(pages):
            img_np = _image_from_page(pdf[idx], scale=1.8)
            img = Image.fromarray(img_np)
            tess_lines.append(pytesseract.image_to_string(img))
        tess_sec = time.time() - t0

        if easy_reader is not None:
            t0 = time.time()
            for idx in range(pages):
                img_np = _image_from_page(pdf[idx], scale=1.8)
                result = easy_reader.readtext(img_np, detail=0, paragraph=False)
                easy_lines.extend(result)
            easy_sec = time.time() - t0
        else:
            easy_sec = None

    rapid_text = "\n".join(rapid_lines)
    tess_text = "\n".join(tess_lines)
    easy_text = "\n".join(easy_lines)

    rapid_score = _score_text(rapid_text)
    tess_score = _score_text(tess_text)
    easy_score = _score_text(easy_text) if easy_reader is not None else {}

    report_lines = [
        f"Company: {company_name}",
        f"Matched entity: {match.company_name} ({match.company_number})",
        f"Filing date: {filing.date}",
        f"Filing description: {filing.description}",
        f"Document URL: {filing.document_metadata_url}",
        f"Pages processed: {max_pages}",
        "",
        "=== RapidOCR ===",
        f"runtime_sec: {rapid_sec:.2f}",
        f"scores: {rapid_score}",
        "excerpt:",
        rapid_text[:2000] or "[empty]",
        "",
        "=== Tesseract ===",
        f"runtime_sec: {tess_sec:.2f}",
        f"scores: {tess_score}",
        "excerpt:",
        tess_text[:2000] or "[empty]",
        "",
        "=== EasyOCR ===",
    ]

    if easy_reader is not None:
        report_lines.extend(
            [
                f"runtime_sec: {easy_sec:.2f}",
                f"scores: {easy_score}",
                "excerpt:",
                easy_text[:2000] or "[empty]",
            ]
        )
    else:
        report_lines.append("easyocr unavailable")

    output_path.write_text("\n".join(report_lines), encoding="utf-8")
    return output_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--company", default="Almac Group")
    parser.add_argument("--max-pages", type=int, default=4)
    parser.add_argument(
        "--output",
        default="/Users/ssebl/Documents/New project/data/ocr_comparison_one_filing.txt",
    )
    args = parser.parse_args()

    out = run_comparison(
        company_name=args.company,
        max_pages=args.max_pages,
        output_path=Path(args.output),
    )
    print(out)
