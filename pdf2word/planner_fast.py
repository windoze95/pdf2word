"""Deterministic fallback planner -- no AI, no network.

Infers structure from typography: font size relative to body text gives heading
levels, leading markers and x-indent give list nesting, PyMuPDF's table finder
gives tables. Good enough for straightforward text documents and useful when
you want a conversion with no model call at all.

It cannot make the editorial judgements the AI planner makes -- telling a
content screenshot from a decorative frame, noticing that a section is empty,
reworking a page-number index for a page-less wiki -- so treat its output as a
starting draft on anything visually complex.
"""

from __future__ import annotations

import re
from typing import Any

import pymupdf as fitz

from .extract import RawDoc

BULLET_RE = re.compile(r"^\s*[•▪◦·‣–—*]\s+")
ORDERED_RE = re.compile(r"^\s*(\d{1,2}|[a-zA-Z]|[ivxIVX]{1,4})[.)]\s+")

FLAG_ITALIC = 1 << 1
FLAG_BOLD = 1 << 4


def _hex_color(value: int) -> str:
    if not isinstance(value, int) or value <= 0:
        return ""
    hexed = f"{value & 0xFFFFFF:06X}"
    # Near-black is the default; recording it would just add noise.
    return "" if hexed in {"000000", "010101", "0D0D0D", "1A1A1A"} else hexed


def _looks_like_data_table(data) -> bool:
    """Reject the layout frames PyMuPDF's table finder reports as tables.

    A real data table is a dense grid: at least two columns, at least two rows,
    and most cells carrying a value. Callout boxes and card layouts trip the
    finder but come back nearly empty, or as a single column.
    """
    if not data or len(data) < 2:
        return False
    columns = max(len(row) for row in data)
    if columns < 2:
        return False
    cells = [(cell or "").strip() for row in data for cell in row]
    if not cells:
        return False
    filled = sum(1 for cell in cells if cell)
    if filled / len(cells) < 0.6:
        return False
    header_filled = sum(1 for cell in data[0] if (cell or "").strip())
    return header_filled >= 2


def _line_text(line: dict[str, Any]) -> str:
    return "".join(span["text"] for span in line["spans"]).replace("\xa0", " ")


def _dominant_size(pages_dict: list[dict[str, Any]]) -> float:
    """Body text size = the size covering the most characters."""
    weights: dict[float, int] = {}
    for page in pages_dict:
        for block in page.get("blocks", []):
            for line in block.get("lines", []):
                for span in line["spans"]:
                    size = round(span["size"], 1)
                    weights[size] = weights.get(size, 0) + len(span["text"].strip())
    return max(weights, key=weights.get) if weights else 11.0


def _runs_for_line(line: dict[str, Any], links: list[dict[str, Any]]) -> list[dict[str, Any]]:
    runs = []
    for span in line["spans"]:
        text = span["text"].replace("\xa0", " ")
        if not text:
            continue
        rect = fitz.Rect(span["bbox"])
        url = ""
        for link in links:
            if not (rect & fitz.Rect(link["rect"])).is_empty:
                url = link["url"]
                break
        run = {"text": text}
        if span["flags"] & FLAG_BOLD:
            run["bold"] = True
        if span["flags"] & FLAG_ITALIC:
            run["italic"] = True
        color = _hex_color(span.get("color", 0))
        if color:
            run["color"] = color
        if url:
            run["link"] = url
        runs.append(run)

    merged: list[dict[str, Any]] = []
    for run in runs:
        if merged and {k: v for k, v in merged[-1].items() if k != "text"} == {
            k: v for k, v in run.items() if k != "text"
        }:
            merged[-1]["text"] += run["text"]
        else:
            merged.append(run)
    return merged


def plan_document(doc: RawDoc) -> dict[str, Any]:
    pdf = fitz.open(doc.path)
    pages_dict = [page.get_text("dict") for page in pdf]
    body_size = _dominant_size(pages_dict)

    blocks: list[dict[str, Any]] = []
    title = ""
    list_counter = 0
    open_list: str | None = None

    for page_index, page in enumerate(pdf):
        page_meta = doc.pages[page_index]
        raw_links = [
            {"rect": link["from"], "url": link["uri"]}
            for link in page.get_links()
            if link.get("uri")
        ]

        table_rects: list[fitz.Rect] = []
        pending_tables: list[tuple[float, dict[str, Any]]] = []
        try:
            for table in page.find_tables().tables:
                data = table.extract()
                if not _looks_like_data_table(data):
                    continue
                rect = fitz.Rect(table.bbox)
                table_rects.append(rect)
                header = [(c or "").strip() for c in data[0]]
                rows = [[(c or "").strip() for c in row] for row in data[1:]]
                pending_tables.append((rect.y0, {"type": "table", "header": header, "rows": rows}))
        except Exception:
            pass

        images = [
            (img.y, {"type": "image", "image_id": img.id, "alt": "", "width_pt": img.width_pt})
            for img in page_meta.images
            if not img.is_background
        ]

        text_items: list[tuple[float, dict[str, Any]]] = []
        for block in pages_dict[page_index].get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                rect = fitz.Rect(line["bbox"])
                if any(not (rect & t).is_empty for t in table_rects):
                    continue

                text = _line_text(line)
                if not text.strip():
                    continue

                runs = _runs_for_line(line, raw_links)
                if not runs:
                    continue

                max_size = max(span["size"] for span in line["spans"])
                is_bold = any(span["flags"] & FLAG_BOLD for span in line["spans"])
                stripped = text.strip()

                bullet = BULLET_RE.match(text)
                ordered = ORDERED_RE.match(text)
                if bullet or ordered:
                    marker_len = len((bullet or ordered).group(0))
                    runs[0] = dict(runs[0])
                    runs[0]["text"] = runs[0]["text"][marker_len:] if len(
                        runs[0]["text"]
                    ) >= marker_len else runs[0]["text"].lstrip()
                    level = min(4, max(0, int((rect.x0 - 55) // 28)))
                    text_items.append(
                        (
                            rect.y0,
                            {
                                "type": "list_item",
                                "level": level,
                                "ordered": bool(ordered),
                                "list_id": open_list or "",
                                "runs": [r for r in runs if r["text"]],
                                "_is_list": True,
                            },
                        )
                    )
                    continue

                if max_size >= body_size * 1.55 and not title and page_index == 0:
                    title = stripped
                    continue

                if (max_size > body_size * 1.14 or (is_bold and max_size > body_size * 1.04)) and len(
                    stripped
                ) < 90:
                    if max_size > body_size * 1.4:
                        level = 1
                    elif max_size > body_size * 1.18:
                        level = 2
                    else:
                        level = 3
                    text_items.append((rect.y0, {"type": "heading", "level": level, "runs": runs}))
                    continue

                text_items.append((rect.y0, {"type": "paragraph", "runs": runs}))

        for _, block in sorted(text_items + pending_tables + images, key=lambda item: item[0]):
            if block.get("_is_list"):
                if open_list is None:
                    list_counter += 1
                    open_list = f"L{list_counter}"
                block["list_id"] = open_list
                block.pop("_is_list")
            elif block["type"] != "image":
                open_list = None
            blocks.append(block)

    pdf.close()

    if not title:
        title = doc.metadata.get("title") or ""
    return {"title": title, "blocks": blocks}
