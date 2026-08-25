# PDF → Confluence-ready Word

Drop PDFs on a page — or paste straight out of OneNote — and get `.docx` files
that Confluence's Word importer accepts without mangling them.

```bash
./run.sh
```

On Windows, double-click `run.bat` (or run it from a terminal).

That's it. The first run builds a virtualenv and installs dependencies; every
run after starts in a second or two and opens the drop page in your browser.
The only requirement is Python 3.10 or newer — everything else installs itself.

## Giving it to your team

Send people the folder and this line:

> **Install Python 3.10+, make sure you're signed in to Codex or Claude Code, then run `run.sh` (`run.bat` on Windows).**

Nothing else — no API keys, no environment variables, no config file. Everyone
runs their own copy: the app works by borrowing whichever CLI you're already
logged into on that machine, so there is no shared instance to stand up and
nothing to provision centrally. That is the trade for needing no keys. (Hosting
one central instance for everybody would mean putting an API key on the server,
which is the thing this design avoids.)

## Why this exists

The obvious way to convert a PDF to Word — `pdf2docx`, Acrobat's *Export to
Word*, or asking a chatbot to "convert this" — tries to reproduce the **page
layout**. To pin text where it sat on the page, those tools emit invisible
tables, text boxes, and positioning frames.

Confluence's Word importer only understands flowing semantic content: heading
styles, paragraphs, lists, simple tables, inline images. Hand it layout
scaffolding and it renders a phantom empty table with all the text orphaned
underneath — the classic broken import.

This tool converts the **content**, not the layout. It reads each page, works
out what the document actually says and how it is organised, and writes a fresh
Word file using only constructs Confluence understands.

The tradeoff is deliberate: the output is not a pixel-perfect copy of the PDF.
Chasing that is what breaks the import.

### What that looks like in practice

A 21-page internal troubleshooting guide, converted in Accurate mode in under
two minutes:

| | This tool | A layout converter |
|---|---|---|
| Tables in the output | **1** — the one real data table | dozens, mostly invisible layout scaffolding |
| Text boxes | **0** | many |
| Floating frames | **0** | many |
| Images | 19, all inline | often floating or dropped |
| Headings | 15 real `Heading 1/2/3` | usually none — bold body text instead |

It also picked up things a script would miss: it recognised three sections that
were empty because the original captured a collapsed accordion, rejoined a
screenshot the PDF had split across a page break, ignored the decorative card
art behind each step, and converted the page-numbered front index into a plain
topic list.

## Pasting from OneNote

The **Paste from OneNote** tab takes a page copied straight out of OneNote —
no export step, no file on disk. Select the page in OneNote, copy, paste into
the canvas, check it looks right, and convert.

This matters because OneNote's own *Export to Word* has the same disease as a
PDF layout converter: OneNote pages are free-form canvases of absolutely
positioned boxes, and the export carries that structure into the `.docx`, which
is exactly what Confluence chokes on. Pasting routes the content through the
same rebuild everything else gets, so OneNote's *fake* lists — a literal "1."
typed into a text box, indented with a margin — come out as real Word numbered
lists that restart correctly.

**About images.** Office apps put images on the clipboard as `file://`
references that browsers refuse to load, and hand the actual bytes over
separately. The canvas pairs the two back up, which is what rescues your
screenshots. Occasionally one doesn't come through — usually in a big
multi-image selection. When that happens the canvas shows a red placeholder and
says how many are missing, and the Word file gets a visible
*(Image missing — re-paste or attach this one manually.)* line. It will never
quietly drop a screenshot. To fill a gap, copy that image on its own and paste
again, or drag the image file straight onto the canvas.

Pasted content always uses Accurate mode; Fast mode reads PDF typography and has
nothing to work with here.

## The two modes

**Accurate** (default) sends each page — the rendered image, the text layer, the
hyperlink targets, and an inventory of extractable images — to a model, which
returns a structured content plan. This is the mode that makes editorial
judgements a script cannot: telling a screenshot from a decorative card frame,
noticing a section is empty because it was a collapsed accordion, reworking a
page-number index for a wiki that has no pages, and transcribing pages that have
no text layer at all (so scanned PDFs work).

**Fast** uses typography heuristics only — no model call, no network. Font sizes
give heading levels, leading markers and indentation give list nesting. It is
instant and fine for straightforward text documents, but it cannot make those
judgement calls, so treat its output as a first draft on anything visually
complex.

Choosing Accurate means Accurate: if the engine can't run, the conversion fails
and says why. It never quietly hands back the rougher Fast output — you'd have
no reason to look twice at a document that silently got worse. (The `--mode auto`
command-line default *does* fall back, and prints a warning saying so.)

## Engines

Accurate mode needs a model, and the app uses whichever ones the machine
already has. **No API key required** — being signed in to Claude Code or Codex
is enough:

| Engine | Enabled by | Needs a key? |
|---|---|---|
| **Codex** (default) | the `codex` command | No — uses your existing ChatGPT/Codex login |
| **Claude Code** | the `claude` command | No — uses your existing login |
| Claude API | `ANTHROPIC_API_KEY` | Yes |
| OpenAI / Azure | `OPENAI_API_KEY`, or `AZURE_OPENAI_API_KEY` + `AZURE_OPENAI_ENDPOINT` | Yes |

The two CLI engines are preferred, because a seat someone already has beats a
key somebody has to provision. When more than one engine is available an
**Engine** dropdown appears on the page and you can switch per conversion;
`PDF2WORD_BACKEND` sets the default. If none is available the page says so and
offers Fast mode only.

Both engines are pinned to a flagship model at high reasoning effort — Codex to
`gpt-5.6-sol`, Claude Code to `opus` — and pinned deliberately rather than left
to whatever your CLI defaults to, so the same document converts the same way
next week.

That choice came out of benchmarking, not taste. A cheaper model at reduced
effort (Sonnet 5 at medium) was around 20 seconds quicker on a 21-page guide,
but across two identical runs its heading count swung 17 → 13 and one pass came
back with a screenshot missing — 18 images where every other engine found 19.
A converter whose promise is that you don't have to check the output twice
cannot afford that; the seconds are the cheaper thing to spend.

If your documents are simple and volume matters more than fidelity, the levers
are `PDF2WORD_CODEX_MODEL=gpt-5.6-luna` (or `-terra`) and
`PDF2WORD_CODEX_EFFORT=medium`. Just re-read a few outputs before trusting a
batch.

Every engine must accept images, since the converter looks at the rendered pages.

## What comes out

- Built-in `Heading 1/2/3` styles for real section structure
- Numbered and bulleted lists with correct nesting, restarting per list
- Genuine data tables only, with a repeating header row — never layout tables
- Inline images at their original resolution, with alt text
- Working hyperlinks pointing at the URLs the PDF actually linked to
- Bold, italic, underline, and meaningful colour (red warnings survive)

Files download from the page and are also written to `output/`.

## Importing to Confluence

On the target page: **••• → Import Word document**. Choosing *Split by Heading
1* turns each top-level section into its own child page, which is usually the
better structure for a long guide.

## Configuration

Environment variables, all optional:

| Variable | Default | Purpose |
|---|---|---|
| `PDF2WORD_PORT` | `8756` | Port to serve on (auto-increments if busy) |
| `PDF2WORD_BACKEND` | `codex-cli` if present | Default engine: `codex-cli`, `claude-cli`, `anthropic`, `openai` |
| `PDF2WORD_ANTHROPIC_MODEL` | `claude-opus-5` | Model for the Claude API engine |
| `PDF2WORD_OPENAI_MODEL` | `gpt-5.6-sol` | Model for OpenAI, or the deployment name on Azure |
| `PDF2WORD_CLI_MODEL` | `opus` | Model for the Claude Code engine |
| `PDF2WORD_CLI_EFFORT` | `high` | Reasoning effort for the Claude Code engine |
| `PDF2WORD_CODEX_MODEL` | `gpt-5.6-sol` | Model for the Codex engine (`""` uses your Codex default) |
| `PDF2WORD_CODEX_EFFORT` | `high` | Reasoning effort for the Codex engine (`""` leaves it unset) |
| `AZURE_OPENAI_API_VERSION` | `2024-10-21` | Azure API version |
| `PDF2WORD_PAGES_PER_CHUNK` | `5` | Pages per model request |
| `PDF2WORD_PARALLEL` | `4` | Chunks analysed at once |
| `PDF2WORD_CONCURRENCY` | `2` | Files converted at once |
| `PDF2WORD_CLI_TIMEOUT` | `300` | Seconds before a wedged CLI chunk is killed |
| `PDF2WORD_NO_BROWSER` | — | Set to `1` to not open a browser |

## Command line

For batches and scripts, skip the web page:

```bash
.venv/bin/python -m pdf2word.cli guide.pdf -o "Guide - Confluence.docx"
```

```bash
.venv/bin/python -m pdf2word.cli ~/Documents/*.pdf --outdir ./converted
```

`--list-engines` shows what was detected, `--engine` picks one, and `--mode fast`
skips the model entirely.

## Testing

```bash
.venv/bin/python tests/test_pipeline.py
```

No network and no model calls. Alongside the obvious checks it asserts the
things that actually break Confluence imports — that the output contains no
text boxes, no floating frames, and no table beyond the real data tables.

## Layout

```
pdf2word/
  extract.py       PDF → text, links, images, page renders (no structure decisions)
  extract_html.py  Pasted HTML → the same evidence, styling noise stripped
  schema.py        The document-plan contract and the conversion prompt
  backends.py      The engines: Claude Code, Codex, Claude API, OpenAI/Azure
  planner_ai.py    Chunking, parallelism, and stitching the plan together
  planner_fast.py  Plan via typography heuristics
  render.py        Plan → .docx, using only Confluence-safe constructs
  convert.py       Orchestration
  cli.py           Command-line entry point
server.py          Local web server and job queue
web/index.html     The drop page
run.sh / run.bat   Launchers for macOS/Linux and Windows
```

The interesting seam is `schema.py`: the document plan is the only contract
between a planner and the renderer. Anything that can emit a valid plan — a new
engine, a hand-written rule, a different model — plugs in without touching the
renderer, and the renderer's restricted vocabulary is what keeps every output
importable.

The same seam is why OneNote support was a new *extractor* rather than a second
tool: `extract_html.py` produces the same evidence a PDF does, and planning and
rendering are shared. A future source — a Graph API pull of whole notebooks,
say — would slot in the same way.

Everything runs locally and the server binds to `127.0.0.1` only. In Accurate
mode the page text and rendered page images go to whichever engine you selected.
