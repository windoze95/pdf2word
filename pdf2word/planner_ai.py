"""Turn extracted PDF material into a document plan, using a reasoning backend.

Pages are split into chunks and analysed concurrently. Concurrency means a
chunk cannot see the plan the previous chunk produced, so continuity is handled
two other ways: each chunk is shown the tail of the preceding page as read-only
context, and a list that spills across a chunk boundary is tagged with a
placeholder id that `_join_carried_lists` rewrites once every chunk is back.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable

from . import backends
from .backends import BackendError
from .extract import RawDoc
from .schema import CARRY_LIST_ID, build_user_prompt

# Pages per request. Small enough that the model can attend to every page
# carefully; large enough that structure spanning a page break stays visible.
PAGES_PER_CHUNK = int(os.environ.get("PDF2WORD_PAGES_PER_CHUNK", "5"))

MAX_PARALLEL_CHUNKS = int(os.environ.get("PDF2WORD_PARALLEL", "4"))

# Re-exported so callers can keep catching one error type.
PlannerError = BackendError


def _page_summary(page, source_kind: str = "pdf") -> str:
    if source_kind == "paste":
        lines = ["--- PASTED CONTENT (HTML) ---", page.text.strip() or "(nothing pasted)"]
    else:
        lines = [f"--- PAGE {page.number} ---", "Text layer:"]
        text = page.text.strip()
        lines.append(text if text else "(empty -- transcribe this page from its image)")

    if page.links:
        lines.append("Hyperlink targets:")
        for link in page.links:
            anchor = link["anchor_text"][:90] or "(url shown as text)"
            lines.append(f'  near "{anchor}" -> {link["url"]}')
    return "\n".join(lines)


def _preceding_context(pages, chunk_start_index: int) -> str:
    """The tail of the page before this chunk, as continuity context."""
    if chunk_start_index == 0:
        return "(nothing)"
    previous = pages[chunk_start_index - 1]
    text = previous.text.strip()
    if not text:
        return f"(page {previous.number} had no text layer)"
    tail = text[-900:]
    return f"--- end of page {previous.number} ---\n{tail}"


def _chunk_prompt(doc: RawDoc, pages, start_index: int) -> str:
    manifest_entries = [img.manifest_entry() for page in pages for img in page.images]

    if doc.source_kind == "paste":
        label = "this pasted content"
    else:
        first, last = pages[0].number, pages[-1].number
        label = f"pages {first}-{last}" if first != last else f"page {first}"

    return build_user_prompt(
        page_summaries="\n\n".join(_page_summary(page, doc.source_kind) for page in pages),
        image_manifest=json.dumps(manifest_entries, indent=1) if manifest_entries else "",
        chunk_label=label,
        is_first_chunk=start_index == 0,
        tail_context=_preceding_context(doc.pages, start_index),
    )


def _join_carried_lists(accumulated: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> None:
    """Rewrite the placeholder list id so a split list keeps counting."""
    last_list_id = next(
        (
            block.get("list_id")
            for block in reversed(accumulated)
            if block.get("type") == "list_item" and block.get("list_id")
        ),
        None,
    )
    for block in incoming:
        if block.get("type") != "list_item":
            continue
        if block.get("list_id") != CARRY_LIST_ID:
            break  # the carried run is only ever at the start of a chunk
        block["list_id"] = last_list_id or CARRY_LIST_ID


def plan_document(
    doc: RawDoc,
    backend_id: str,
    progress: Callable[[str, float], None] | None = None,
) -> dict[str, Any]:
    starts = list(range(0, len(doc.pages), PAGES_PER_CHUNK))
    chunks = [(start, doc.pages[start : start + PAGES_PER_CHUNK]) for start in starts]
    total = len(chunks)

    done = 0

    def report(label: str) -> None:
        if progress:
            progress(f"Reading {label} ({done}/{total} chunks done)", done / total if total else 1.0)

    report("document")

    def work(index: int) -> tuple[int, dict[str, Any]]:
        start, pages = chunks[index]
        prompt = _chunk_prompt(doc, pages, start)
        # Pasted content has no rendered page; the markup is the whole input.
        renders = [page.render_path for page in pages if page.render_path]
        return index, backends.run_chunk(backend_id, prompt, renders, doc.workdir)

    results: list[dict[str, Any] | None] = [None] * total
    errors: list[str] = []

    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_CHUNKS, max(total, 1))) as pool:
        futures = [pool.submit(work, index) for index in range(total)]
        # as_completed, not submission order: otherwise a slow first chunk keeps
        # the progress bar at zero while later chunks quietly finish.
        for future in as_completed(futures):
            try:
                index, result = future.result()
                results[index] = result
            except Exception as exc:
                errors.append(str(exc))
            finally:
                done += 1
                report("pages")

    if not any(results):
        raise BackendError(errors[0] if errors else "No pages could be analysed.")

    title = ""
    blocks: list[dict[str, Any]] = []
    for part in results:
        if not part:
            continue
        if not title and part.get("title"):
            title = part["title"]
        incoming = part.get("blocks") or []
        _join_carried_lists(blocks, incoming)
        blocks.extend(incoming)

    if not title:
        title = doc.metadata.get("title") or os.path.splitext(os.path.basename(doc.path))[0]

    return {
        "title": title,
        "blocks": blocks,
        "incomplete_chunks": len([r for r in results if r is None]),
    }
