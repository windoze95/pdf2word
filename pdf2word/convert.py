"""Top-level conversion: a PDF or a paste in, a Confluence-ready .docx out."""

from __future__ import annotations

import shutil
import tempfile
from typing import Any, Callable

from . import backends, extract, extract_html, planner_ai, planner_fast, render

ProgressFn = Callable[[str, float], None]


class BackendUnavailable(RuntimeError):
    pass


def _reporter(progress: ProgressFn | None) -> ProgressFn:
    def report(message: str, fraction: float) -> None:
        if progress:
            progress(message, max(0.0, min(1.0, fraction)))

    return report


def convert(
    pdf_path: str,
    out_path: str,
    mode: str = "auto",
    backend_id: str | None = None,
    progress: ProgressFn | None = None,
    workdir: str | None = None,
) -> dict[str, Any]:
    """Convert one PDF.

    mode: "ai"   -- always use a model (error if no backend is reachable)
          "fast" -- typography heuristics only, no model call
          "auto" -- use a model when one is reachable, else fall back to fast

    backend_id: pick a specific engine ("claude-cli", "codex-cli", "anthropic",
                "openai"). Defaults to the best one available.
    """
    report = _reporter(progress)
    owns_workdir = workdir is None
    workdir = workdir or tempfile.mkdtemp(prefix="pdf2word-")

    try:
        report("Reading the PDF", 0.05)
        doc = extract.extract(pdf_path, workdir)
        return _plan_and_render(doc, out_path, mode, backend_id, report)
    finally:
        if owns_workdir:
            shutil.rmtree(workdir, ignore_errors=True)


def convert_paste(
    html: str,
    out_path: str,
    title: str = "",
    mode: str = "auto",
    backend_id: str | None = None,
    unresolved_images: int = 0,
    progress: ProgressFn | None = None,
    workdir: str | None = None,
) -> dict[str, Any]:
    """Convert pasted rich content -- OneNote, Word, a web page -- the same way.

    The paste arrives as HTML with its images already inlined by the browser, so
    only the extraction step differs; planning and rendering are shared, which is
    what keeps the output as importable as the PDF path's.
    """
    report = _reporter(progress)
    owns_workdir = workdir is None
    workdir = workdir or tempfile.mkdtemp(prefix="pdf2word-")

    try:
        report("Reading the pasted content", 0.05)
        doc = extract_html.extract_paste(
            html, workdir, title=title, unresolved_from_client=unresolved_images
        )
        if not doc.pages[0].text.strip() and not doc.pages[0].images:
            raise ValueError("Nothing usable was pasted.")
        return _plan_and_render(doc, out_path, mode, backend_id, report)
    finally:
        if owns_workdir:
            shutil.rmtree(workdir, ignore_errors=True)


def _plan_and_render(
    doc,
    out_path: str,
    mode: str,
    backend_id: str | None,
    report: ProgressFn,
) -> dict[str, Any]:
    """Shared tail: choose a planner, build the plan, render the .docx."""
    backend = backends.describe(backend_id) if backend_id else backends.preferred()
    use_ai = mode == "ai" or (mode == "auto" and backend["id"] != "none")

    if mode == "ai" and backend["id"] == "none":
        raise BackendUnavailable(
            "Accurate mode needs Claude Code, Codex, or an API key, and none was found."
        )

    warnings: list[str] = []
    count = getattr(doc, "unresolved_images", 0)
    if count:
        plural = "s were" if count > 1 else " was"
        warnings.append(
            f"{count} image{plural} not readable from the clipboard and left as a "
            "placeholder. Paste that part again on its own, or drop the image file in."
        )

    # The heuristic planner reads typography straight out of the PDF, so it has
    # nothing to work with when the source was a paste.
    if not use_ai and getattr(doc, "source_kind", "pdf") == "paste":
        raise BackendUnavailable(
            "Pasted content needs Accurate mode — Fast mode only works on PDFs. "
            "Sign in to Claude Code or Codex, or set an API key."
        )

    if use_ai:
        def chunk_progress(message: str, fraction: float) -> None:
            report(message, 0.10 + fraction * 0.75)

        try:
            plan = planner_ai.plan_document(doc, backend["id"], chunk_progress)
            engine = backend["label"]
            missed = plan.get("incomplete_chunks") or 0
            if missed:
                warnings.append(
                    f"{missed} section(s) could not be analysed and are missing "
                    "from the output."
                )
        except backends.BackendError as exc:
            if mode == "ai" or getattr(doc, "source_kind", "pdf") == "paste":
                raise
            report("Model unavailable, falling back to Fast mode", 0.5)
            plan = planner_fast.plan_document(doc)
            engine = "Fast (no AI)"
            warnings.append(f"Fell back to Fast mode: {exc}")
    else:
        report("Analysing layout", 0.4)
        plan = planner_fast.plan_document(doc)
        engine = "Fast (no AI)"

    report("Building the Word document", 0.9)
    stats = render.render(plan, doc, out_path)

    report("Done", 1.0)
    return {
        "engine": engine,
        "pages": doc.page_count,
        "stats": stats,
        "output": out_path,
        "had_text_layer": doc.has_text_layer(),
        "warnings": warnings,
    }
