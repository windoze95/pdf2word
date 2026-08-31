# PDF → Confluence-ready Word

Drop a PDF on a web page — or paste straight out of OneNote — and download a
`.docx` file that Confluence can import cleanly.

## Start here

You do not need to know Git, Python, or the command line. Follow the section for
your computer **in order**. Copy only the text inside the code boxes.

> **Important: Codex or Claude Code is not where you use this app.** You sign in
> to one of them once so this app can borrow its document-reading ability behind
> the scenes. After setup, you use a separate page that opens in your web browser.
> **Do not reopen ChatGPT, and do not paste your document into a chat.**

What happens is:

```text
You put a PDF or OneNote page into this app's browser page
                              ↓
The app automatically asks Codex or Claude Code to understand the document
                              ↓
The app gives you a Word file to download
```

The saved Codex or Claude Code login is the only connection. The ChatGPT or
Claude website is not part of the conversion workflow.

Pick either **Codex** or **Claude Code** for that behind-the-scenes step; you do
not need both. Codex is the default in these instructions. Neither option needs
an API key.

### Windows — first-time setup

#### 1. Open PowerShell

Click **Start**, type **PowerShell**, and press **Enter**. A blue or black window
will open. Paste every Windows command below into that window and press **Enter**.

#### 2. Install Python and Git

Paste this whole box:

```powershell
winget install -e --id Python.Python.3.13
winget install -e --id Git.Git
```

Wait for both installs to finish. If it asks you to accept an agreement, type
`Y` and press **Enter**. Then close PowerShell and open it again.

#### 3. Install Codex and sign in

Paste this:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://chatgpt.com/codex/install.ps1 | iex"
```

When it finishes, close PowerShell and open it again. Then paste:

```powershell
codex
```

Choose **Sign in with ChatGPT**. Your browser will open; sign in with the ChatGPT
account that has Codex access. Return to PowerShell when it says you are signed
in. Type `/exit` and press **Enter** to leave Codex.

Already use Claude Code instead? Skip the Codex commands above and use these:

```powershell
irm https://claude.ai/install.ps1 | iex
```

Close and reopen PowerShell, run `claude`, and follow the browser login. Type
`/exit` when the Claude Code prompt appears.

#### 4. Download and start the app

Paste this whole box:

```powershell
cd $HOME
git clone https://github.com/windoze95/pdf2word.git
cd pdf2word
.\run.bat
```

The first start takes a few minutes because it installs the app's remaining
pieces. Later starts are much faster.

### Mac — first-time setup

#### 1. Open Terminal

Press **Command + Space**, type **Terminal**, and press **Return**. Paste every
Mac command below into that window and press **Return**.

#### 2. Check Python and Git

Paste this:

```bash
python3 --version
git --version
```

Python must say `3.10` or newer. If Python is missing or older, install the
current version from [Python for macOS](https://www.python.org/downloads/macos/),
then close and reopen Terminal. If checking Git opens an Apple installation
window, click **Install**, wait for it to finish, and run `git --version` again.

#### 3. Install Codex and sign in

Paste this:

```bash
curl -fsSL https://chatgpt.com/codex/install.sh | sh
```

When it finishes, close Terminal and open it again. Then paste:

```bash
codex
```

Choose **Sign in with ChatGPT**. Your browser will open; sign in with the ChatGPT
account that has Codex access. Return to Terminal when it says you are signed
in. Type `/exit` and press **Return** to leave Codex.

Already use Claude Code instead? Skip the Codex commands above and use this:

```bash
curl -fsSL https://claude.ai/install.sh | bash
```

Close and reopen Terminal, run `claude`, and follow the browser login. Type
`/exit` when the Claude Code prompt appears.

#### 4. Download and start the app

Paste this whole box:

```bash
cd ~
git clone https://github.com/windoze95/pdf2word.git
cd pdf2word
./run.sh
```

The first start takes a few minutes because it installs the app's remaining
pieces. Later starts are much faster.

Linux users can follow the Mac instructions after installing Python 3.10 or
newer and Git with their normal package manager.

The Codex and Claude Code install commands above come from their official
[Codex CLI](https://learn.chatgpt.com/docs/codex/cli) and
[Claude Code](https://code.claude.com/docs/en/quickstart) instructions.

### What happens after the last command

After you run `run.bat` on Windows or `run.sh` on Mac, **stop typing commands**
and wait. Keep the PowerShell or Terminal window open.

A separate browser page should open with the title **PDF to Confluence-ready
Word** and the words **Documents in. Clean Word out.** That browser page is the
app. From this point on, work in the browser—not in PowerShell, Codex, Claude
Code, or ChatGPT.

On that browser page:

1. Drag your PDF onto **Drop PDFs to convert**, or click **Paste from OneNote**.
2. Leave **Accurate** selected.
3. Start the conversion. The app contacts Codex or Claude Code automatically;
   you will not see or use a chat window.
4. Download the Word file when it finishes.

If the browser does not open automatically, paste this into the browser's
address bar:

```text
http://127.0.0.1:8756
```

If that address does not work, look in PowerShell or Terminal for the line that
starts with **Open** and copy the address shown there. The final number may be
`8757`, `8758`, or another nearby number if `8756` was already in use.

To stop the app, return to PowerShell or Terminal and press **Ctrl + C**.

### Every later time

You do **not** need to install or clone anything again.

On Windows, open PowerShell and paste:

```powershell
cd "$HOME\pdf2word"
.\run.bat
```

On Mac or Linux, open Terminal and paste:

```bash
cd ~/pdf2word
./run.sh
```

Then stop typing and wait for the browser page to open. **Do not run Codex or
Claude Code again, and do not open ChatGPT.** The saved login is used
automatically behind the scenes.

The app also saves every finished file in the `pdf2word/output` folder on your
computer.

### If something goes wrong

| What you see | What to do |
|---|---|
| `winget` is not recognized | Install [Python for Windows](https://www.python.org/downloads/windows/) and [Git for Windows](https://git-scm.com/download/win) manually, then close and reopen PowerShell. |
| `codex` or `claude` is not recognized | Close PowerShell or Terminal, open it again, and retry. If it still fails, repeat that tool's install step. |
| `Python 3.10 or newer is required` | Install the current Python from [python.org](https://www.python.org/downloads/), then close and reopen PowerShell or Terminal. |
| `destination path 'pdf2word' already exists` | The app is already downloaded. Use the commands under **Every later time** instead. |
| The browser did not open | Copy the exact address after **Open** in PowerShell or Terminal and paste it into your browser. |
| A window immediately closes on Windows | Open PowerShell and run the **Every later time** commands there so the error stays visible. |

Nothing else is required: no API keys, environment variables, or config file.
Everyone runs their own local copy, and the app uses the Codex or Claude Code
login already stored on that computer.

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
