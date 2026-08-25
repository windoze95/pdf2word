"""Command-line entry point: convert PDFs without the web page.

    python -m pdf2word.cli report.pdf
    python -m pdf2word.cli *.pdf --mode fast --outdir ./converted
"""

from __future__ import annotations

import argparse
import os
import sys

from . import backends
from . import convert as convert_module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pdf2word",
        description="Convert PDFs into Confluence-ready Word documents.",
    )
    parser.add_argument("pdfs", nargs="*", help="PDF files to convert")
    parser.add_argument("-o", "--output", help="Output path (single input only)")
    parser.add_argument("--outdir", default=".", help="Directory for outputs (default: .)")
    parser.add_argument(
        "--mode",
        choices=["auto", "ai", "fast"],
        default="auto",
        help="auto: use a model when available; ai: require one; fast: heuristics only",
    )
    parser.add_argument(
        "--engine",
        choices=backends.ALL_BACKEND_IDS,
        help="Which model backend to use (default: best available)",
    )
    parser.add_argument(
        "--list-engines", action="store_true", help="Show detected engines and exit"
    )
    args = parser.parse_args(argv)

    if args.list_engines:
        options = backends.available()
        if not options:
            print("No engines available — only Fast mode can run.")
        for index, option in enumerate(options):
            print(f"{'*' if index == 0 else ' '} {option['id']:<12} {option['label']}")
            print(f"  {'':<12} {option['detail']}")
        return 0

    if not args.pdfs:
        parser.error("give at least one PDF to convert")
    if args.output and len(args.pdfs) > 1:
        parser.error("--output works with a single input; use --outdir for several")

    if args.mode != "fast":
        backend = backends.describe(args.engine) if args.engine else backends.preferred()
        print(f"Engine: {backend['label']} — {backend['detail']}", file=sys.stderr)

    failures = 0
    for pdf_path in args.pdfs:
        if not os.path.exists(pdf_path):
            print(f"  ! {pdf_path}: not found", file=sys.stderr)
            failures += 1
            continue

        if args.output:
            out_path = args.output
        else:
            stem = os.path.splitext(os.path.basename(pdf_path))[0]
            os.makedirs(args.outdir, exist_ok=True)
            out_path = os.path.join(args.outdir, f"{stem} - Confluence.docx")

        print(f"\n{os.path.basename(pdf_path)}", file=sys.stderr)

        def progress(message: str, fraction: float) -> None:
            print(f"  [{fraction * 100:5.1f}%] {message}", file=sys.stderr)

        try:
            result = convert_module.convert(
                pdf_path,
                out_path,
                mode=args.mode,
                backend_id=args.engine,
                progress=progress,
            )
        except Exception as exc:
            print(f"  ! failed: {exc}", file=sys.stderr)
            failures += 1
            continue

        stats = result["stats"]
        print(
            f"  -> {out_path}\n"
            f"     {result['pages']} pages, {stats['headings']} headings, "
            f"{stats['list_items']} list items, {stats['tables']} tables, "
            f"{stats['images']} images, {stats['links']} links "
            f"({result['engine']})",
            file=sys.stderr,
        )
        for warning in result.get("warnings") or []:
            print(f"     ! {warning}", file=sys.stderr)

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
