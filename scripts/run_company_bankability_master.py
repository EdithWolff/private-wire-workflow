import argparse
from pathlib import Path

from private_wire_workflow.bankability_master import PipelineConfig, run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser()
    base_dir = Path(__file__).resolve().parents[1]
    parser.add_argument(
        "--input-csv",
        default=str(base_dir / "data" / "inputs" / "company_rating_screening_findings.csv"),
    )
    parser.add_argument(
        "--txt-dir",
        default=str(base_dir / "data" / "filing_texts"),
    )
    parser.add_argument(
        "--output-xlsx",
        default=str(base_dir / "data" / "bankability_enriched.xlsx"),
    )
    parser.add_argument(
        "--checkpoint-json",
        default=str(base_dir / "data" / "bankability_checkpoint.json"),
    )
    parser.add_argument(
        "--summary-json",
        default=str(base_dir / "data" / "bankability_summary.json"),
    )
    parser.add_argument("--max-workers", type=int, default=5)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-backoff-sec", type=float, default=2.0)
    parser.add_argument("--ocr-page-timeout-sec", type=int, default=25)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    config = PipelineConfig(
        input_csv_path=Path(args.input_csv),
        txt_dir=Path(args.txt_dir),
        output_xlsx_path=Path(args.output_xlsx),
        checkpoint_path=Path(args.checkpoint_json),
        summary_path=Path(args.summary_json),
        max_workers=args.max_workers,
        retries=args.retries,
        retry_backoff_sec=args.retry_backoff_sec,
        ocr_page_timeout_sec=args.ocr_page_timeout_sec,
        limit=args.limit,
    )
    summary = run_pipeline(config)
    print(summary)
    print(args.output_xlsx)


if __name__ == "__main__":
    main()
