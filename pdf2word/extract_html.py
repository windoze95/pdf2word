"""Turn pasted rich content into the same evidence a PDF produces.

The browser hands us HTML plus the images it managed to recover from the
clipboard. This module reduces that to a semantic skeleton -- the tags and the
formatting cues that carry meaning, with the pile of inline styling that Office
apps emit thrown away -- and writes the images out as files, so the planners
and the renderer see exactly the shape they see for a PDF.

Nothing here decides document structure; that stays with the planners.
"""

from __future__ import annotations

import base64
import binascii
import os
import re
from html.parser import HTMLParser
from typing import Any

from .extract import ImageCandidate, Page, RawDoc

# Tags worth keeping: they carry structure or emphasis. Everything else is
# layout scaffolding from the source app.
STRUCTURAL_TAGS = {
    "p", "div", "br", "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "table", "thead", "tbody", "tr", "td", "th",
    "b", "strong", "i", "em", "u", "s", "strike", "sub", "sup",
    "blockquote", "pre", "code", "hr", "a", "img", "span", "font",
}

DROP_ENTIRELY = {"script", "style", "meta", "link", "head", "title", "colgroup", "col"}

VOID_TAGS = {"br", "img", "hr"}

# Inline style declarations that actually mean something for the conversion.
MEANINGFUL_STYLE = re.compile(
    r"(font-weight\s*:\s*(bold|[6-9]00)"
    r"|font-style\s*:\s*italic"
    r"|text-decoration[^;]*underline"
    r"|text-decoration[^;]*line-through"
    r"|color\s*:\s*(?!inherit|initial|windowtext|black|#000000\b|#000\b)[^;]+"
    r"|font-size\s*:\s*[^;]+"
    r"|margin-left\s*:\s*[^;]+)",
    re.I,
)

DATA_URI = re.compile(r"^data:(image/[a-z.+-]+);base64,(.*)$", re.I | re.S)

EXTENSION_FOR = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/svg+xml": ".svg",
}


class _Skeleton(HTMLParser):
    """Reduce pasted HTML to structure + meaningful emphasis.

    Office clipboard HTML is mostly `<span style="font-family:Calibri;
    mso-fareast-...">` noise wrapped around a little real content. Feeding that
    to a model wastes context and buries the signal, so styling is filtered down
    to the handful of declarations that change meaning.
    """

    def __init__(self, images_dir: str):
        super().__init__(convert_charrefs=True)
        self.images_dir = images_dir
        self.parts: list[str] = []
        self.images: list[ImageCandidate] = []
        self.links: list[dict[str, Any]] = []
        self.unresolved_images = 0
        self._suppress = 0

    # -- helpers ---------------------------------------------------------
    def _keep_style(self, attrs: dict[str, str]) -> str:
        style = attrs.get("style") or ""
        kept = [m.group(0).strip() for m in MEANINGFUL_STYLE.finditer(style)]
        return "; ".join(kept)

    def _save_image(self, src: str) -> str | None:
        match = DATA_URI.match(src.strip())
        if not match:
            return None
        media_type, payload = match.group(1).lower(), match.group(2)
        try:
            raw = base64.b64decode(re.sub(r"\s+", "", payload), validate=False)
        except (binascii.Error, ValueError):
            return None
        if len(raw) < 128:  # tracking pixels and spacer gifs
            return None

        index = len(self.images) + 1
        name = f"paste_i{index}{EXTENSION_FOR.get(media_type, '.png')}"
        path = os.path.join(self.images_dir, name)
        with open(path, "wb") as handle:
            handle.write(raw)
        return path

    # -- parser hooks ----------------------------------------------------
    def handle_starttag(self, tag: str, attrs_list) -> None:
        tag = tag.lower()
        if tag in DROP_ENTIRELY:
            self._suppress += 1
            return
        if self._suppress or tag not in STRUCTURAL_TAGS:
            return

        attrs = {k.lower(): (v or "") for k, v in attrs_list}

        if tag == "img":
            path = self._save_image(attrs.get("src", ""))
            if path is None:
                self.unresolved_images += 1
                self.parts.append("[image could not be read from the clipboard]")
                return
            image_id = f"paste_i{len(self.images) + 1}"
            width = _to_float(attrs.get("width")) or 0.0
            height = _to_float(attrs.get("height")) or 0.0
            self.images.append(
                ImageCandidate(
                    id=image_id,
                    path=path,
                    page=1,
                    y=float(len(self.parts)),
                    x0=0.0,
                    x1=width,
                    # Clipboard sizes are CSS pixels; points are 3/4 of that.
                    width_pt=(width * 0.75) if width else 0.0,
                    height_pt=(height * 0.75) if height else 0.0,
                    is_background=False,
                )
            )
            alt = attrs.get("alt", "").strip()
            self.parts.append(f'<img id="{image_id}"' + (f' alt="{alt}"' if alt else "") + ">")
            return

        if tag == "a":
            href = attrs.get("href", "").strip()
            if href.startswith(("http://", "https://", "mailto:")):
                self.links.append({"anchor_text": "", "url": href, "y": len(self.parts)})
                self.parts.append(f'<a href="{href}">')
            else:
                self.parts.append("<a>")
            return

        if tag in ("span", "font", "div", "p", "li", "td", "th"):
            style = self._keep_style(attrs)
            colour = attrs.get("color", "")
            if colour and "color" not in style:
                style = (style + "; " if style else "") + f"color: {colour}"
            if tag in ("span", "font") and not style:
                return  # a span with nothing to say is pure noise
            self.parts.append(f'<{tag}' + (f' style="{style}"' if style else "") + ">")
            return

        self.parts.append(f"<{tag}>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in DROP_ENTIRELY:
            self._suppress = max(0, self._suppress - 1)
            return
        if self._suppress or tag not in STRUCTURAL_TAGS or tag in VOID_TAGS:
            return
        if tag in ("span", "font"):
            # Only close what we chose to open.
            for part in reversed(self.parts):
                if part.startswith(f"<{tag}"):
                    self.parts.append(f"</{tag}>")
                    return
                if part.startswith(f"</{tag}"):
                    return
            return
        self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self._suppress:
            return
        text = data.replace("\xa0", " ")
        if text.strip():
            self.parts.append(text)
            if self.links and not self.links[-1]["anchor_text"]:
                self.links[-1]["anchor_text"] = text.strip()[:90]
        elif self.parts and not self.parts[-1].endswith(" "):
            self.parts.append(" ")


def _to_float(value: str | None) -> float:
    try:
        return float(re.sub(r"[^0-9.]", "", value or "") or 0)
    except ValueError:
        return 0.0


def _tidy(markup: str) -> str:
    markup = re.sub(r"[ \t]+", " ", markup)
    markup = re.sub(r"(\s*<br>\s*){3,}", "<br><br>", markup)
    markup = re.sub(r"(<div>\s*</div>|<p>\s*</p>|<span>\s*</span>)", "", markup)
    return markup.strip()


def extract_paste(
    html: str,
    workdir: str,
    title: str = "",
    unresolved_from_client: int = 0,
) -> RawDoc:
    """Build a RawDoc from pasted HTML, matching what extract() returns for a PDF."""
    images_dir = os.path.join(workdir, "images")
    os.makedirs(images_dir, exist_ok=True)

    skeleton = _Skeleton(images_dir)
    skeleton.feed(html)
    skeleton.close()

    body = _tidy("".join(skeleton.parts))

    page = Page(
        number=1,
        width=612.0,
        height=792.0,
        text=body,
        links=skeleton.links,
        images=skeleton.images,
        render_path="",  # pasted content has no rendered page to look at
    )

    doc = RawDoc(
        path=title or "Pasted content",
        page_count=1,
        pages=[page],
        metadata={"title": title} if title else {},
        workdir=workdir,
    )
    doc.source_kind = "paste"
    doc.unresolved_images = skeleton.unresolved_images + unresolved_from_client
    return doc
