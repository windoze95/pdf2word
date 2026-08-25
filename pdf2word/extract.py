"""Pull raw material out of a PDF: text, links, images, and page renders.

Nothing here decides document *structure* -- it only gathers evidence. The
planners (planner_ai / planner_fast) turn that evidence into a document plan.
"""

from __future__ import annotations

import dataclasses
import os
from typing import Any

import pymupdf as fitz

# Page render resolution used for the vision pass. 110 DPI keeps a Letter page
# near 1200px on the long edge -- enough to read UI screenshots, small enough
# to stay cheap.
PAGE_RENDER_DPI = 110

# Images smaller than this in either dimension are separator rules, bullets, or
# compression artifacts rather than content.
MIN_IMAGE_PT = 12

# How close to a page edge a clipped image must sit for it to be a candidate
# half of an image split across two pages.
EDGE_TOLERANCE_PT = 26


@dataclasses.dataclass
class ImageCandidate:
    id: str
    path: str
    page: int
    y: float
    x0: float
    x1: float
    width_pt: float
    height_pt: float
    is_background: bool
    certain_decoration: bool = False
    stitched_from: list[str] = dataclasses.field(default_factory=list)

    def manifest_entry(self) -> dict[str, Any]:
        entry = {
            "id": self.id,
            "page": self.page,
            "width_pt": round(self.width_pt),
            "height_pt": round(self.height_pt),
        }
        if self.is_background:
            entry["likely"] = "decoration"
            entry["why"] = (
                "frames another image, or has live page text drawn over it"
                if self.certain_decoration
                else "spans nearly the full page width"
            )
        if self.stitched_from:
            entry["note"] = "one image that the PDF split across two pages; already rejoined"
        return entry


@dataclasses.dataclass
class Page:
    number: int
    width: float
    height: float
    text: str
    links: list[dict[str, Any]]
    images: list[ImageCandidate]
    render_path: str


@dataclasses.dataclass
class RawDoc:
    path: str
    page_count: int
    pages: list[Page]
    metadata: dict[str, Any]
    workdir: str
    # "pdf" pages carry a rendered image the model can look at; "paste" content
    # is HTML only, so the planners fall back to reading the markup.
    source_kind: str = "pdf"
    unresolved_images: int = 0

    @property
    def images(self) -> list[ImageCandidate]:
        return [img for page in self.pages for img in page.images]

    def image_by_id(self, image_id: str) -> ImageCandidate | None:
        for img in self.images:
            if img.id == image_id:
                return img
        return None

    def has_text_layer(self) -> bool:
        return any(page.text.strip() for page in self.pages)


def _rects_overlap_significantly(outer: fitz.Rect, inner: fitz.Rect, page: fitz.Rect) -> bool:
    """True when `outer` effectively contains `inner`.

    Both rects are clipped to the page first. An image running off the bottom of
    a page is only drawn as far as the page goes, so judging containment by its
    full nominal height would miss frames around images that continue overleaf.
    """
    inner_visible = inner & page
    if inner_visible.is_empty:
        return False
    clipped = outer & inner_visible
    if clipped.is_empty:
        return False
    return clipped.get_area() / inner_visible.get_area() > 0.92


def _text_line_rects(page: fitz.Page) -> list[fitz.Rect]:
    rects = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            if "".join(span["text"] for span in line["spans"]).strip():
                rects.append(fitz.Rect(line["bbox"]))
    return rects


def _collect_image_rects(page: fitz.Page) -> list[dict[str, Any]]:
    """Displayed image rects on a page, in reading order, with decoration flagged.

    Styled PDFs -- the kind produced when someone asks a tool to "make it look
    nice" -- draw card and callout backgrounds as full-width rasters, layer the
    real screenshot on top, and often paint the whole lot twice to fake a drop
    shadow. Duplicates are collapsed first, then these signals mark scenery:

      * it frames another image (a card or callout around a screenshot)
      * live page text is drawn over it -- a screenshot's text is baked into the
        raster, so genuine screenshots have no selectable text on top
      * it is small and carries a glyph, i.e. a numbered step badge or an icon
      * it spans nearly the full page width, or most of the page area
    """
    raw = []
    for info in page.get_image_info():
        rect = fitz.Rect(info["bbox"])
        if rect.width < MIN_IMAGE_PT or rect.height < MIN_IMAGE_PT:
            continue
        raw.append({"rect": rect, "src_w": info["width"], "src_h": info["height"]})

    # Collapse near-coincident rasters into one. Two kinds show up: the same
    # artwork painted twice at a small offset to fake a drop shadow, and the
    # same picture stored at two resolutions. Both are duplicates rather than a
    # frame around content -- a real frame has visible margin around what it
    # holds, so it is materially larger. Keep whichever copy has more source
    # pixels, since that is the one that will still look sharp in Word.
    deduped: list[dict[str, Any]] = []
    for item in raw:
        visible = item["rect"] & page.rect
        item_area = max(visible.get_area(), 1.0)
        twin_index = None
        for index, kept in enumerate(deduped):
            kept_visible = kept["rect"] & page.rect
            overlap = (kept_visible & visible).get_area()
            smaller = max(min(kept_visible.get_area(), item_area), 1.0)
            larger = max(kept_visible.get_area(), item_area, 1.0)
            if overlap / smaller > 0.85 and smaller / larger > 0.8:
                twin_index = index
                break

        if twin_index is None:
            deduped.append(item)
        else:
            kept = deduped[twin_index]
            if item["src_w"] * item["src_h"] > kept["src_w"] * kept["src_h"]:
                deduped[twin_index] = item
    raw = deduped

    text_rects = _text_line_rects(page)
    page_area = page.rect.get_area() or 1.0

    for item in raw:
        rect = item["rect"]
        frames_another = any(
            other is not item
            and _rects_overlap_significantly(rect, other["rect"], page.rect)
            for other in raw
        )
        text_on_top = sum(
            1
            for line in text_rects
            if rect.contains(fitz.Point((line.x0 + line.x1) / 2, (line.y0 + line.y1) / 2))
        )
        # A small graphic with a glyph drawn over it is a numbered badge or an
        # icon; a screenshot that small would have its text baked into the
        # raster instead.
        is_badge = max(rect.width, rect.height) < 55 and text_on_top >= 1

        item["certain_decoration"] = frames_another or text_on_top >= 2 or is_badge
        item["is_background"] = (
            item["certain_decoration"]
            or rect.width / (page.rect.width or 1) > 0.85
            or (rect.get_area() / page_area) > 0.55
        )

    raw.sort(key=lambda item: (round(item["rect"].y0), item["rect"].x0))
    return raw


def _render_clip(page: fitz.Page, rect: fitz.Rect, src_w: int, dest: str) -> tuple[int, int]:
    """Rasterize a region of the page at roughly the image's native resolution.

    Rendering the *region* rather than pulling the embedded stream keeps
    annotations (arrows, highlight boxes) that were drawn on top of the
    screenshot, and works for inline images that have no xref at all.
    """
    clip = rect & page.rect
    if clip.is_empty:
        clip = rect
    zoom = max(2.0, min(5.0, (src_w / clip.width) if clip.width else 3.0))
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip)
    pix.save(dest)
    return pix.width, pix.height


def _trim_blank_edge(image, at_bottom: bool, max_fraction: float = 0.3):
    """Shave the page margin off one end of a half-image before joining it.

    Each half carries the whitespace that ran to the page edge, so pasting them
    together leaves a white band through the middle of the picture. Trimming is
    capped so a genuinely pale image can never be eaten away.
    """
    grey = image.convert("L")
    width, height = grey.size
    limit = int(height * max_fraction)
    rows = range(height - 1, -1, -1) if at_bottom else range(height)

    blank = 0
    for row in rows:
        if blank >= limit:
            break
        line = grey.crop((0, row, width, row + 1))
        if line.getextrema()[0] < 246:  # any non-white pixel ends the run
            break
        blank += 1

    if blank == 0:
        return image
    box = (0, 0, width, height - blank) if at_bottom else (0, blank, width, height)
    return image.crop(box)


def _stitch_split_images(doc: fitz.Document, pages: list[Page], images_dir: str) -> None:
    """Rejoin an image the PDF cut in half across a page break.

    Detected geometrically: bottom half ends at the page edge, top half starts
    at the next page's edge, and both occupy the same horizontal band.
    """
    try:
        from PIL import Image  # noqa: PLC0415
    except ImportError:
        return

    for idx in range(len(pages) - 1):
        upper, lower = pages[idx], pages[idx + 1]

        # Only real content is worth rejoining. Card and banner artwork often
        # runs to both page edges too, and merging those just inflates scenery.
        tails = [
            image
            for image in upper.images
            if not image.is_background
            and (upper.height - (image.y + image.height_pt)) < EDGE_TOLERANCE_PT
        ]
        heads = [
            image
            for image in lower.images
            if not image.is_background and image.y < EDGE_TOLERANCE_PT
        ]
        if not tails or not heads:
            continue

        for tail in sorted(tails, key=lambda i: i.x0):
            partner = next(
                (
                    head
                    for head in heads
                    if abs(tail.x0 - head.x0) < 3 and abs(tail.x1 - head.x1) < 3
                ),
                None,
            )
            if partner is None:
                continue

            try:
                top_img = _trim_blank_edge(Image.open(tail.path), at_bottom=True)
                bottom_img = _trim_blank_edge(Image.open(partner.path), at_bottom=False)
            except Exception:
                continue

            width = min(top_img.width, bottom_img.width)
            merged = Image.new("RGB", (width, top_img.height + bottom_img.height), "white")
            merged.paste(top_img.crop((0, 0, width, top_img.height)), (0, 0))
            merged.paste(bottom_img.crop((0, 0, width, bottom_img.height)), (0, top_img.height))

            merged_path = os.path.join(images_dir, f"{tail.id}_joined.png")
            merged.save(merged_path)

            tail.path = merged_path
            tail.height_pt += partner.height_pt
            tail.stitched_from = [tail.id, partner.id]
            heads.remove(partner)
            lower.images.remove(partner)

    # Anything still hanging off the top of a page is the tail of a picture that
    # began earlier and was already placed, so it is a leftover sliver rather
    # than content in its own right.
    for page in pages:
        for image in page.images:
            if not image.is_background and not image.stitched_from and image.y < -EDGE_TOLERANCE_PT:
                image.is_background = True
                image.certain_decoration = True


def extract(pdf_path: str, workdir: str) -> RawDoc:
    """Read `pdf_path` and write page renders + image crops under `workdir`."""
    images_dir = os.path.join(workdir, "images")
    renders_dir = os.path.join(workdir, "pages")
    os.makedirs(images_dir, exist_ok=True)
    os.makedirs(renders_dir, exist_ok=True)

    doc = fitz.open(pdf_path)
    pages: list[Page] = []

    for page_index in range(len(doc)):
        page = doc[page_index]
        page_no = page_index + 1

        links = []
        for link in page.get_links():
            uri = link.get("uri")
            if not uri:
                continue
            rect = fitz.Rect(link["from"])
            anchor = page.get_textbox(rect + (-2, -2, 2, 2)).strip().replace("\n", " ")
            links.append({"anchor_text": anchor, "url": uri, "y": round(rect.y0)})

        images: list[ImageCandidate] = []
        for slot, info in enumerate(_collect_image_rects(page), start=1):
            image_id = f"p{page_no:02d}_i{slot}"
            dest = os.path.join(images_dir, f"{image_id}.png")
            rect = info["rect"]
            try:
                _render_clip(page, rect, info["src_w"], dest)
            except Exception:
                continue
            images.append(
                ImageCandidate(
                    id=image_id,
                    path=dest,
                    page=page_no,
                    y=rect.y0,
                    x0=rect.x0,
                    x1=rect.x1,
                    width_pt=rect.width,
                    height_pt=rect.height,
                    is_background=info["is_background"],
                    certain_decoration=info["certain_decoration"],
                )
            )

        render_path = os.path.join(renders_dir, f"page{page_no:02d}.png")
        page.get_pixmap(dpi=PAGE_RENDER_DPI).save(render_path)

        pages.append(
            Page(
                number=page_no,
                width=page.rect.width,
                height=page.rect.height,
                text=page.get_text("text").replace("\xa0", " "),
                links=links,
                images=images,
                render_path=render_path,
            )
        )

    _stitch_split_images(doc, pages, images_dir)

    metadata = {k: v for k, v in (doc.metadata or {}).items() if v}
    doc.close()

    return RawDoc(
        path=pdf_path,
        page_count=len(pages),
        pages=pages,
        metadata=metadata,
        workdir=workdir,
    )
