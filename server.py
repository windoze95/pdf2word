#!/usr/bin/env python3
"""Local drag-and-drop server for PDF -> Confluence-ready .docx conversion.

Binds to localhost only. Start it with `./run.sh` (or `python3 server.py`) and
drop PDFs on the page it opens.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import traceback
import uuid
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pdf2word import backends  # noqa: E402
from pdf2word import convert as convert_module  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(HERE, "web")
OUTPUT_DIR = os.path.join(HERE, "output")

DEFAULT_PORT = int(os.environ.get("PDF2WORD_PORT", "8756"))
MAX_UPLOAD_BYTES = 200 * 1024 * 1024

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
# The CLI backends spawn a subprocess per chunk, so keep concurrency modest.
CONCURRENCY = int(os.environ.get("PDF2WORD_CONCURRENCY", "2"))
_slots = threading.Semaphore(CONCURRENCY)


def _safe_stem(name: str) -> str:
    stem = os.path.splitext(os.path.basename(name))[0].strip() or "document"
    for ch in '<>:"/\\|?*':
        stem = stem.replace(ch, "-")
    return stem[:120]


def _reserve_output_path(original_name: str) -> str:
    """Claim a free output filename atomically.

    Two people dropping files with the same name at the same moment would
    otherwise both pick the same path and one would silently overwrite the
    other, so the name is claimed by creating the file, not by checking for it.
    """
    stem = _safe_stem(original_name)
    counter = 1
    while True:
        suffix = "" if counter == 1 else f" ({counter})"
        candidate = os.path.join(OUTPUT_DIR, f"{stem} - Confluence{suffix}.docx")
        try:
            handle = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            counter += 1
            continue
        os.close(handle)
        return candidate


def _update(job_id: str, **fields) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job:
            job.update(fields)


def _run_job(
    job_id: str,
    source: dict,
    original_name: str,
    mode: str,
    backend_id: str | None,
) -> None:
    """Run one conversion. `source` is either {"pdf": path} or {"html": markup}."""
    if not _slots.acquire(blocking=False):
        # Say what it is waiting for; a bare "Queued" that never moves reads as
        # a hang rather than a queue.
        _update(job_id, message=f"Waiting — {CONCURRENCY} conversions already running")
        _slots.acquire()
    try:
        _update(job_id, state="running", message="Starting", progress=0.02)
        workdir = tempfile.mkdtemp(prefix="pdf2word-job-")
        try:
            out_path = _reserve_output_path(original_name)

            def progress(message: str, fraction: float) -> None:
                _update(job_id, message=message, progress=fraction)

            if "pdf" in source:
                result = convert_module.convert(
                    source["pdf"],
                    out_path,
                    mode=mode,
                    backend_id=backend_id,
                    progress=progress,
                    workdir=workdir,
                )
            else:
                result = convert_module.convert_paste(
                    source["html"],
                    out_path,
                    title=os.path.splitext(original_name)[0],
                    mode=mode,
                    backend_id=backend_id,
                    unresolved_images=source.get("unresolved", 0),
                    progress=progress,
                    workdir=workdir,
                )

            _update(
                job_id,
                state="done",
                message="Ready",
                progress=1.0,
                output=out_path,
                download_name=os.path.basename(out_path),
                engine=result["engine"],
                pages=result["pages"],
                stats=result["stats"],
                warnings=result.get("warnings") or [],
                size=os.path.getsize(out_path),
            )
        except Exception as exc:  # surfaced to the page, not swallowed
            traceback.print_exc()
            _update(job_id, state="error", message=str(exc)[:400], progress=1.0)
            # Don't leave the reserved-but-never-written placeholder behind.
            try:
                if os.path.exists(out_path) and os.path.getsize(out_path) == 0:
                    os.unlink(out_path)
            except (OSError, UnboundLocalError):
                pass
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
            if "pdf" in source:
                try:
                    os.unlink(source["pdf"])
                except OSError:
                    pass
    finally:
        _slots.release()


class Handler(BaseHTTPRequestHandler):
    server_version = "pdf2word"

    def log_message(self, fmt, *args):  # quieter console
        if "/api/job" not in (self.path or ""):
            sys.stderr.write(f"  {self.address_string()} {fmt % args}\n")

    # -- helpers ----------------------------------------------------------
    def _send(self, code: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, code: int = 200) -> None:
        self._send(code, json.dumps(payload).encode(), "application/json")

    # -- routes -----------------------------------------------------------
    def do_GET(self) -> None:
        route = urlparse(self.path)
        query = parse_qs(route.query)

        if route.path in ("/", "/index.html"):
            try:
                with open(os.path.join(WEB_DIR, "index.html"), "rb") as handle:
                    self._send(200, handle.read(), "text/html; charset=utf-8")
            except OSError:
                self._send(500, b"index.html missing", "text/plain")
            return

        if route.path == "/api/config":
            options = backends.available()
            self._json(
                {
                    "backends": options,
                    "default_backend": backends.preferred()["id"],
                    "output_dir": OUTPUT_DIR,
                    "ai_available": bool(options),
                }
            )
            return

        if route.path == "/api/job":
            job_id = (query.get("id") or [""])[0]
            with _jobs_lock:
                job = dict(_jobs.get(job_id) or {})
            if not job:
                self._json({"error": "unknown job"}, 404)
                return
            job.pop("output", None)
            self._json(job)
            return

        if route.path == "/api/download":
            job_id = (query.get("id") or [""])[0]
            with _jobs_lock:
                job = dict(_jobs.get(job_id) or {})
            path = job.get("output")
            if not path or not os.path.exists(path):
                self._json({"error": "not ready"}, 404)
                return
            with open(path, "rb") as handle:
                data = handle.read()
            self._send(
                200,
                data,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                {"Content-Disposition": f'attachment; filename="{job["download_name"]}"'},
            )
            return

        if route.path == "/api/zip":
            ids = [i for i in (query.get("ids") or [""])[0].split(",") if i]
            buffer = io.BytesIO()
            count = 0
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                for job_id in ids:
                    with _jobs_lock:
                        job = dict(_jobs.get(job_id) or {})
                    path = job.get("output")
                    if path and os.path.exists(path):
                        archive.write(path, job["download_name"])
                        count += 1
            if not count:
                self._json({"error": "nothing to zip"}, 404)
                return
            self._send(
                200,
                buffer.getvalue(),
                "application/zip",
                {"Content-Disposition": 'attachment; filename="confluence-docs.zip"'},
            )
            return

        self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:
        route = urlparse(self.path)
        if route.path not in ("/api/convert", "/api/convert-paste"):
            self._send(404, b"not found", "text/plain")
            return

        query = parse_qs(route.query)
        default_name = "document.pdf" if route.path == "/api/convert" else "Pasted note"
        name = unquote((query.get("name") or [default_name])[0])
        mode = (query.get("mode") or ["auto"])[0]
        if mode not in ("auto", "ai", "fast"):
            mode = "auto"

        backend_id = (query.get("backend") or [""])[0] or None
        if backend_id and backend_id not in {b["id"] for b in backends.available()}:
            backend_id = None

        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self._json({"error": "nothing was sent"}, 400)
            return
        if length > MAX_UPLOAD_BYTES:
            self._json({"error": "content larger than 200 MB"}, 413)
            return

        payload = self.rfile.read(length)

        if route.path == "/api/convert-paste":
            try:
                body = json.loads(payload.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._json({"error": "could not read the pasted content"}, 400)
                return
            html = body.get("html") or ""
            if not html.strip():
                self._json({"error": "the paste was empty"}, 400)
                return
            name = body.get("name") or name
            source = {"html": html, "unresolved": int(body.get("unresolved") or 0)}
        else:
            if not payload.startswith(b"%PDF"):
                self._json({"error": f"{name} is not a PDF"}, 400)
                return
            handle, pdf_path = tempfile.mkstemp(suffix=".pdf", prefix="pdf2word-in-")
            with os.fdopen(handle, "wb") as out:
                out.write(payload)
            source = {"pdf": pdf_path}

        job_id = uuid.uuid4().hex[:12]
        with _jobs_lock:
            _jobs[job_id] = {
                "id": job_id,
                "name": name,
                "state": "queued",
                "message": "Queued",
                "progress": 0.0,
                "created": time.time(),
            }

        threading.Thread(
            target=_run_job, args=(job_id, source, name, mode, backend_id), daemon=True
        ).start()
        self._json({"job_id": job_id})


def _pick_port(preferred: int) -> int:
    for port in [preferred] + list(range(preferred + 1, preferred + 25)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit("No free port found near " + str(preferred))


def main() -> None:
    args = sys.argv[1:]
    if "-h" in args or "--help" in args:
        print(__doc__)
        print(f"  --port N      listen on port N (default {DEFAULT_PORT})")
        print("  --no-browser  do not open a browser window")
        print("\nTo convert without the web page: python -m pdf2word.cli file.pdf\n")
        return

    requested_port = DEFAULT_PORT
    if "--port" in args:
        try:
            requested_port = int(args[args.index("--port") + 1])
        except (IndexError, ValueError):
            raise SystemExit("--port needs a number")

    # Without this the start-up banner -- which carries the URL people need --
    # sits in a buffer whenever output is piped or logged rather than typed to
    # a terminal.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except (AttributeError, ValueError):
        pass

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    port = _pick_port(requested_port)
    url = f"http://127.0.0.1:{port}/"

    options = backends.available()
    print("\n  PDF -> Confluence-ready Word")
    if options:
        print("  Engines available :")
        for index, option in enumerate(options):
            marker = "*" if index == 0 else " "
            print(f"                    {marker} {option['label']}")
    else:
        print("  Engines available : none — Fast mode only")
        print("                      Set OPENAI_API_KEY or ANTHROPIC_API_KEY, or install")
        print("                      Claude Code, to enable Accurate mode.")
    print(f"  Saving files to   : {OUTPUT_DIR}")
    print(f"  Open              : {url}")
    print("\n  Press Ctrl+C to stop.\n")

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    if os.environ.get("PDF2WORD_NO_BROWSER") != "1" and "--no-browser" not in args:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopped.\n")
        server.shutdown()


if __name__ == "__main__":
    main()
