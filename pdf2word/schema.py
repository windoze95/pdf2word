"""The document plan: the contract between a planner and the .docx renderer.

A plan describes *content and structure* -- headings, paragraphs, lists,
tables, images -- and deliberately says nothing about page geometry. That
restriction is the whole point: Confluence's Word importer understands flowing
semantic content and chokes on the layout tables and text boxes that
layout-faithful PDF converters emit.

Kept as a flat schema (no $ref/$defs) because structured-output validators
handle flat schemas most reliably.
"""

from __future__ import annotations

RUN_PROPERTIES = {
    "text": {"type": "string", "description": "Literal text. Reproduce source wording exactly."},
    "bold": {"type": "boolean"},
    "italic": {"type": "boolean"},
    "underline": {"type": "boolean"},
    "color": {
        "type": "string",
        "description": "Hex RRGGBB without '#'. Empty string for default. Use for coloured warnings.",
    },
    "link": {"type": "string", "description": "Absolute URL, or empty string for plain text."},
}

BLOCK_PROPERTIES = {
    "type": {
        "type": "string",
        "enum": ["heading", "paragraph", "list_item", "table", "image", "divider"],
    },
    "level": {
        "type": "integer",
        "description": "heading: 1-3. list_item: nesting depth 0-4.",
    },
    "runs": {
        "type": "array",
        "description": "Text content for heading / paragraph / list_item.",
        "items": {
            "type": "object",
            "properties": RUN_PROPERTIES,
            "required": ["text"],
            "additionalProperties": False,
        },
    },
    "list_id": {
        "type": "string",
        "description": (
            "Groups list_items into one list. Numbering restarts for each distinct id, "
            "so give every separate list its own id."
        ),
    },
    "ordered": {"type": "boolean", "description": "list_item: numbered (true) or bulleted (false)."},
    "align": {"type": "string", "enum": ["left", "center"]},
    "indent": {"type": "integer", "description": "paragraph/image: indent steps (0-3)."},
    "header": {"type": "array", "items": {"type": "string"}, "description": "table: header cells."},
    "rows": {
        "type": "array",
        "description": "table: body rows, each an array of cell strings.",
        "items": {"type": "array", "items": {"type": "string"}},
    },
    "image_id": {"type": "string", "description": "image: an id from the supplied image inventory."},
    "alt": {"type": "string", "description": "image: short description for accessibility."},
    "width_pt": {
        "type": "number",
        "description": "image: display width in points. Omit to use the size it had in the PDF.",
    },
}

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "Document title. Only set this in the first chunk; empty string otherwise.",
        },
        "blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": BLOCK_PROPERTIES,
                "required": ["type"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["blocks"],
    "additionalProperties": False,
}


CARRY_LIST_ID = "carry"


def strict_schema(schema: dict) -> dict:
    """Rewrite a schema for validators that demand every property be required.

    OpenAI's strict structured-output mode requires `required` to name every
    property and `additionalProperties: false` on every object. Genuinely
    optional fields become nullable so the model can still omit them in spirit;
    `strip_nulls` removes them again on the way back.
    """
    if not isinstance(schema, dict):
        return schema

    if schema.get("type") == "object" and "properties" in schema:
        properties = schema["properties"]
        already_required = set(schema.get("required", []))
        rebuilt = {}
        for name, definition in properties.items():
            converted = strict_schema(definition)
            if name not in already_required:
                converted = {"anyOf": [converted, {"type": "null"}]}
            rebuilt[name] = converted
        return {
            **{k: v for k, v in schema.items() if k not in ("properties", "required")},
            "properties": rebuilt,
            "required": list(properties.keys()),
            "additionalProperties": False,
        }

    if schema.get("type") == "array" and "items" in schema:
        return {**schema, "items": strict_schema(schema["items"])}

    return schema


def strip_nulls(value):
    """Drop the nulls that nullable-strict schemas force the model to emit."""
    if isinstance(value, dict):
        return {k: strip_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [strip_nulls(v) for v in value]
    return value


SYSTEM_PROMPT = """\
You convert PDF documents into a structured content plan that will be rendered \
as a Microsoft Word file and then imported into Atlassian Confluence.

Confluence's Word importer only understands flowing semantic content: heading \
styles, paragraphs, lists, simple data tables, and inline images. Layout \
scaffolding -- text boxes, positioning tables, multi-column frames -- is what \
breaks these imports, producing phantom empty tables with the text orphaned \
below them. So you must reproduce what the document SAYS and how it is \
ORGANISED, never how it was arranged on the page.

You will be given, for each page: a rendered image of the page, the extracted \
text layer, the hyperlink targets, and an inventory of images available for \
placement. Return a plan built from those.

RULES

Content fidelity
- Reproduce the source wording exactly, including typos, doubled spaces, and \
  odd capitalisation. You are converting, not editing.
- Never invent, summarise, or helpfully expand content.
- If a page's text layer is empty or garbled, transcribe the text from the page \
  image instead.
- Drop content that only exists to serve the paper format: running headers and \
  footers, page numbers, and "continued on page N" notes.

Structure
- Emit the document title once, as `title` on the first chunk only.
- Use `heading` blocks (level 1-3) for real section structure, mirroring the \
  document's own hierarchy. Do not promote emphasised body text to a heading.
- A visual section divider with no text is a `divider` block.
- If a section heading exists but its body is empty in the source (a collapsed \
  accordion, for example), keep the heading and add one italic grey paragraph \
  reading exactly: (No content in the source document.)

Lists
- Use `list_item` for anything the source presents as a numbered or bulleted \
  list, with `level` for nesting depth read from the visual indentation.
- Give every distinct list its own `list_id`; numbering restarts per id. A list \
  interrupted by an image or a note paragraph and then resumed is still ONE \
  list -- keep the same id so the numbers continue.

Text formatting
- Preserve bold, italic, and underline.
- Preserve meaningful colour, especially red warning text, via `color`.
- Attach `link` to exactly the run of text that was hyperlinked in the source, \
  using the URLs supplied for that page.
- If a bare URL or hostname appears as plain text and was not hyperlinked, you \
  may still link it to itself, since it is unambiguous and readers expect to \
  click it. Never invent a URL for text that is not one, and never reconstruct \
  a target you were not given.

Tables
- Only use `table` for genuine data tables -- rows and columns of related values.
- Never use a table for layout, side-by-side content, or callout boxes. Render a \
  callout or "Note:" box as an ordinary paragraph with its label bolded.

Images
- Place images inline where they occur in the reading flow, using `image_id` \
  values from the inventory.
- Skip decorative images: page backgrounds, card and callout container art, \
  banner bars, rounded-rectangle frames, and the little numbered circles beside \
  steps. Inventory entries marked `likely: decoration` are almost always \
  scenery -- skip them and place the real screenshot layered on top instead -- \
  but trust the page image over the flag if it clearly shows otherwise.
- Skip an image whose entire content is text that you have already transcribed \
  into blocks.
- Write a short factual `alt` for every image you keep.

Format-shift adjustments
- A Confluence page has no page numbers, so rework any front matter that indexes \
  the document by page: keep the topic list, drop or convert the page references.
- Drop instructions that only make sense in the PDF viewer, such as "use the PDF \
  bookmarks" or "click the triangle to expand this section".

When the input is pasted HTML rather than a PDF
- You get markup instead of page images. It has already been stripped down to \
  structure plus the styling that carries meaning, and every image is tagged \
  with the id to use in an `image` block.
- Notebook apps like OneNote are free-form canvases, so their markup leans on \
  positioned containers and inline styling instead of real headings and lists. \
  Read the intent: a short bold line above a block of text is a heading, lines \
  that begin with a bullet character or a number are a list, and indentation \
  means nesting. Emit proper `heading` and `list_item` blocks for them.
- Ignore positioning, widths, margins, fonts, and background colours. Keep bold, \
  italic, underline, and colour that marks a warning.
- A `[image could not be read from the clipboard]` marker means an image was \
  lost in transit. Leave a paragraph reading exactly: (Image missing — re-paste \
  or attach this one manually.) so the gap is visible rather than silent.
"""


def build_user_prompt(
    *,
    page_summaries: str,
    image_manifest: str,
    chunk_label: str,
    is_first_chunk: bool,
    tail_context: str,
) -> str:
    parts = [
        f"Convert {chunk_label} of this PDF into a content plan.",
        "",
        "PAGE DATA",
        page_summaries,
        "",
        "IMAGE INVENTORY (use these ids for image blocks)",
        image_manifest or "(no images on these pages)",
    ]
    if is_first_chunk:
        parts += [
            "",
            "This is the start of the document, so set `title` to the document's title.",
        ]
    else:
        parts += [
            "",
            "CONTINUATION",
            "This chunk continues a document already in progress, so leave `title` empty.",
            "The text below is the end of the previous page. It has ALREADY been converted --",
            "it is here only so you can see what this chunk continues from. Do not re-emit it.",
            "",
            tail_context,
            "",
            f'If this chunk opens midway through a list that began earlier, use list_id "{CARRY_LIST_ID}"',
            "for those items so the numbering can be joined up afterwards.",
        ]
    return "\n".join(parts)
