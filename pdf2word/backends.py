"""Reasoning backends: whatever this machine can actually reach.

All of them are interchangeable -- each takes the same prompt and JSON schema
and returns the same document plan, so nothing downstream knows which one ran.

The two CLI backends are listed first on purpose: they run against a seat the
person already has, so nobody needs an API key provisioned to use this tool.

  codex-cli   the `codex` command     GPT, via an existing ChatGPT/Codex login
  claude-cli  the `claude` command    Claude, via an existing Claude Code login
  anthropic   ANTHROPIC_API_KEY       Claude via the Anthropic SDK
  openai      OPENAI_API_KEY or Azure GPT via the OpenAI SDK
  (none)                              only Fast mode is possible
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import subprocess
from typing import Any

from .schema import PLAN_SCHEMA, SYSTEM_PROMPT, strict_schema, strip_nulls

ANTHROPIC_MODEL = os.environ.get("PDF2WORD_ANTHROPIC_MODEL", "claude-opus-5")
CLAUDE_CLI_MODEL = os.environ.get("PDF2WORD_CLI_MODEL", "opus")
# Pinned rather than left to the session default, so a conversion doesn't
# silently change behaviour with whatever the person last set in Claude Code.
CLAUDE_CLI_EFFORT = os.environ.get("PDF2WORD_CLI_EFFORT", "high")
OPENAI_MODEL = os.environ.get("PDF2WORD_OPENAI_MODEL", "gpt-5.6-sol")

# Both engines are pinned to a flagship model at high effort, and pinned
# deliberately: benchmarking a cheaper model at reduced effort showed the output
# varying between identical runs -- one pass quietly came back with a screenshot
# missing. For a converter whose whole promise is that you don't have to check
# the result twice, consistency is worth more than the seconds saved. Lower
# these to trade accuracy back for speed and cost.
CODEX_MODEL = os.environ.get("PDF2WORD_CODEX_MODEL", "gpt-5.6-sol")
CODEX_EFFORT = os.environ.get("PDF2WORD_CODEX_EFFORT", "high")

# A chunk that hasn't answered in five minutes is wedged, not slow. Waiting
# longer just holds a job slot and leaves the queue looking stuck.
CLI_TIMEOUT_SECONDS = int(os.environ.get("PDF2WORD_CLI_TIMEOUT", "300"))
API_MAX_TOKENS = 32000

# Every backend this module knows how to run, in preference order. `available()`
# filters this down to the ones the machine can actually reach.
ALL_BACKEND_IDS = ("codex-cli", "claude-cli", "anthropic", "openai")


class BackendError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# discovery
# --------------------------------------------------------------------------

def _claude_cli_path() -> str | None:
    explicit = os.environ.get("PDF2WORD_CLAUDE_BIN")
    if explicit and os.path.exists(explicit):
        return explicit
    found = shutil.which("claude")
    if found:
        return found
    fallback = os.path.expanduser("~/.local/bin/claude")
    return fallback if os.path.exists(fallback) else None


def _codex_cli_path() -> str | None:
    explicit = os.environ.get("PDF2WORD_CODEX_BIN")
    if explicit and os.path.exists(explicit):
        return explicit
    return shutil.which("codex")


def _run_cli(
    command: list[str], cwd: str, label: str, stdin_text: str | None = None
) -> subprocess.CompletedProcess:
    """Run a CLI with a hard deadline, taking its whole process tree down on timeout.

    Both CLIs are launchers that spawn a longer-lived child, and
    `subprocess.run(timeout=...)` only kills the process it started -- the
    grandchild survives, keeps its slot busy, and the queue behind it looks
    frozen. Running in a new session lets the whole group be signalled at once.
    """
    popen_kwargs: dict[str, Any] = {
        "cwd": cwd,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
    }
    if stdin_text is not None:
        popen_kwargs["stdin"] = subprocess.PIPE
    if os.name != "nt":
        popen_kwargs["start_new_session"] = True

    proc = subprocess.Popen(command, **popen_kwargs)
    try:
        stdout, stderr = proc.communicate(input=stdin_text, timeout=CLI_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        _terminate_tree(proc)
        proc.communicate()
        raise BackendError(
            f"{label} did not answer within {CLI_TIMEOUT_SECONDS}s and was stopped. "
            "Try again, switch engine, or raise PDF2WORD_CLI_TIMEOUT."
        ) from None

    return subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)


def _terminate_tree(proc: subprocess.Popen) -> None:
    try:
        if os.name == "nt":
            proc.kill()
            return
        import signal  # noqa: PLC0415

        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            proc.kill()
        except OSError:
            pass


def _launch(path: str) -> list[str]:
    """Build the argv prefix that actually starts a CLI.

    On Windows both tools install as `.cmd` shims, and CreateProcess cannot run
    a batch file directly -- it has to go through the command interpreter.
    """
    if os.name == "nt" and path.lower().endswith((".cmd", ".bat")):
        return [os.environ.get("COMSPEC", "cmd.exe"), "/c", path]
    return [path]


def _module_available(name: str) -> bool:
    import importlib.util  # noqa: PLC0415

    return importlib.util.find_spec(name) is not None


def _azure_configured() -> bool:
    return bool(os.environ.get("AZURE_OPENAI_API_KEY") and os.environ.get("AZURE_OPENAI_ENDPOINT"))


def available() -> list[dict[str, Any]]:
    """Every usable backend, most preferred first.

    Seat-based CLIs come first: they work with the login someone already has,
    whereas the API backends need a key that has to be provisioned.
    """
    found: list[dict[str, Any]] = []

    if _codex_cli_path():
        found.append(
            {
                "id": "codex-cli",
                "label": "Codex",
                "detail": (
                    "Uses your existing ChatGPT/Codex login. No API key needed. "
                    + (
                        f"Running {CODEX_MODEL}"
                        + (f" at {CODEX_EFFORT} effort." if CODEX_EFFORT else ".")
                        if CODEX_MODEL
                        else "Uses your own Codex default model."
                    )
                ),
                "parallel": True,
            }
        )

    if _claude_cli_path():
        found.append(
            {
                "id": "claude-cli",
                "label": "Claude Code",
                "detail": (
                    "Uses your existing Claude Code login. No API key needed. "
                    f"Running {CLAUDE_CLI_MODEL}"
                    + (f" at {CLAUDE_CLI_EFFORT} effort." if CLAUDE_CLI_EFFORT else ".")
                ),
                "parallel": True,
            }
        )

    if os.environ.get("ANTHROPIC_API_KEY") and _module_available("anthropic"):
        found.append(
            {
                "id": "anthropic",
                "label": f"Claude API ({ANTHROPIC_MODEL})",
                "detail": "Using ANTHROPIC_API_KEY.",
                "parallel": True,
            }
        )

    if _module_available("openai") and (os.environ.get("OPENAI_API_KEY") or _azure_configured()):
        via = "Azure OpenAI" if _azure_configured() else "OpenAI API"
        found.append(
            {
                "id": "openai",
                "label": f"{via} ({OPENAI_MODEL})",
                "detail": f"Using your {via} key.",
                "parallel": True,
            }
        )

    return found


def preferred() -> dict[str, Any]:
    forced = os.environ.get("PDF2WORD_BACKEND")
    options = available()
    if forced:
        for option in options:
            if option["id"] == forced:
                return option
    if options:
        return options[0]
    return {
        "id": "none",
        "label": "Unavailable",
        "detail": (
            "No ANTHROPIC_API_KEY, no OPENAI_API_KEY, and no `claude` CLI. "
            "Only Fast mode can run."
        ),
        "parallel": False,
    }


def describe(backend_id: str) -> dict[str, Any]:
    for option in available():
        if option["id"] == backend_id:
            return option
    return preferred()


# --------------------------------------------------------------------------
# per-backend chunk execution
# --------------------------------------------------------------------------

def _encoded_images(paths: list[str]) -> list[str]:
    encoded = []
    for path in paths:
        with open(path, "rb") as handle:
            encoded.append(base64.standard_b64encode(handle.read()).decode())
    return encoded


def _run_anthropic(user_prompt: str, page_images: list[str]) -> dict[str, Any]:
    import anthropic  # noqa: PLC0415

    content: list[dict[str, Any]] = [
        {
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": data},
        }
        for data in _encoded_images(page_images)
    ]
    content.append({"type": "text", "text": user_prompt})

    client = anthropic.Anthropic()
    with client.messages.stream(
        model=ANTHROPIC_MODEL,
        max_tokens=API_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
        output_config={"format": {"type": "json_schema", "schema": PLAN_SCHEMA}},
    ) as stream:
        response = stream.get_final_message()

    if response.stop_reason == "refusal":
        raise BackendError("Claude declined to process this document.")

    text = next((block.text for block in response.content if block.type == "text"), None)
    if not text:
        raise BackendError("Empty response from the Claude API.")
    return json.loads(text)


def _openai_client():
    if _azure_configured():
        from openai import AzureOpenAI  # noqa: PLC0415

        return AzureOpenAI(
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
        )
    from openai import OpenAI  # noqa: PLC0415

    return OpenAI()


def _is_unknown_model_error(error: Exception) -> bool:
    text = str(error).lower()
    return "model" in text and any(
        phrase in text
        for phrase in ("does not exist", "not found", "unknown model", "invalid model")
    )


def _unknown_model_message(client, error: Exception) -> str:
    """Turn 'model does not exist' into something the user can act on.

    Model names move faster than any default baked into this file, so when the
    configured one is rejected, show what this key can actually reach.
    """
    hint = (
        f"The model {OPENAI_MODEL!r} was rejected. "
        "Set PDF2WORD_OPENAI_MODEL to one your account can use"
    )
    if _azure_configured():
        return hint + " (on Azure this must be your deployment name, not the model name)."
    try:
        names = sorted(m.id for m in client.models.list().data if m.id.startswith("gpt"))
        if names:
            return f"{hint}. Available to this key: {', '.join(names[:15])}"
    except Exception:
        pass
    return hint + f". Original error: {str(error)[:200]}"


def _run_openai(user_prompt: str, page_images: list[str]) -> dict[str, Any]:
    client = _openai_client()

    content: list[dict[str, Any]] = [{"type": "text", "text": user_prompt}]
    for data in _encoded_images(page_images):
        content.append(
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{data}"}}
        )

    request: dict[str, Any] = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ],
        # OpenAI's strict mode requires every property to be listed in
        # `required`, so optional fields are sent as nullable and the nulls are
        # stripped from the reply.
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "document_plan",
                "strict": True,
                "schema": strict_schema(PLAN_SCHEMA),
            },
        },
    }

    try:
        response = client.chat.completions.create(
            **request, max_completion_tokens=API_MAX_TOKENS
        )
    except Exception as first_error:
        if _is_unknown_model_error(first_error):
            raise BackendError(_unknown_model_message(client, first_error)) from first_error
        # Older deployments still use max_tokens; some reject any limit at all.
        try:
            response = client.chat.completions.create(**request, max_tokens=API_MAX_TOKENS)
        except Exception:
            response = client.chat.completions.create(**request)

    choice = response.choices[0]
    if getattr(choice, "finish_reason", None) == "content_filter":
        raise BackendError("The content filter blocked this document.")

    text = choice.message.content
    if not text:
        refusal = getattr(choice.message, "refusal", None)
        raise BackendError(refusal or "Empty response from OpenAI.")
    return strip_nulls(json.loads(text))


def _run_claude_cli(user_prompt: str, page_images: list[str], workdir: str) -> dict[str, Any]:
    cli = _claude_cli_path()
    if not cli:
        raise BackendError("The `claude` CLI is not installed.")

    if page_images:
        image_list = "\n".join(f"  {path}" for path in page_images)
        look_first = (
            "Use the Read tool to look at each of these rendered page images before "
            "planning, so you can see the layout, colours, and screenshots:\n"
            f"{image_list}\n\n"
        )
    else:
        look_first = ""

    prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"{look_first}"
        f"{user_prompt}\n\n"
        "Return only the plan object matching the required schema."
    )

    command = [
        *_launch(cli), "-p", prompt,
        "--tools", "Read",
        "--permission-mode", "acceptEdits",
        "--add-dir", workdir,
        "--output-format", "json",
        "--json-schema", json.dumps(PLAN_SCHEMA),
        "--model", CLAUDE_CLI_MODEL,
        "--no-session-persistence",
        "--disable-slash-commands",
    ]
    if CLAUDE_CLI_EFFORT:
        command += ["--effort", CLAUDE_CLI_EFFORT]

    proc = _run_cli(command, workdir, "Claude Code")

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-400:]
        raise BackendError(f"Claude CLI failed: {detail}")

    try:
        envelope = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise BackendError(f"Could not parse CLI output: {exc}") from exc

    if envelope.get("is_error"):
        raise BackendError(str(envelope.get("result", "CLI reported an error"))[:400])

    plan = envelope.get("structured_output")
    if plan is None:
        raw = envelope.get("result", "")
        try:
            plan = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise BackendError(f"CLI returned no structured output: {str(raw)[:300]}") from exc
    return plan


def _parse_plan_text(raw: str, source: str) -> dict[str, Any]:
    """Read a plan out of a CLI's final message, fenced or bare."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    if not text:
        raise BackendError(f"{source} returned an empty response.")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # A model that ignored the schema still usually emits the object inline.
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                pass
        raise BackendError(f"{source} did not return valid JSON: {text[:250]}") from None


def _run_codex_cli(user_prompt: str, page_images: list[str], workdir: str) -> dict[str, Any]:
    cli = _codex_cli_path()
    if not cli:
        raise BackendError("The `codex` CLI is not installed.")

    # Codex validates against OpenAI's strict structured-output rules, which
    # demand that every property be listed in `required` -- so it gets the same
    # nullable rewrite the OpenAI API backend uses.
    schema_path = os.path.join(workdir, "plan.schema.json")
    if not os.path.exists(schema_path):
        with open(schema_path, "w") as handle:
            json.dump(strict_schema(PLAN_SCHEMA), handle)

    # Unique per chunk so parallel chunks never overwrite each other's answer.
    stem = os.path.basename(page_images[0]) if page_images else f"paste-{abs(hash(user_prompt))}"
    reply_path = os.path.join(workdir, f"codex-reply-{stem}.json")

    command = [
        *_launch(cli), "exec",
        "--skip-git-repo-check",   # the work directory is a scratch dir, not a repo
        "--ephemeral",             # don't leave session files behind
        "-s", "read-only",         # the task is pure analysis; no writes, no shell
        "-C", workdir,
        "--output-schema", schema_path,
        "-o", reply_path,
        "--color", "never",
        # The user's own MCP servers are irrelevant here and only add start-up
        # latency (and noise when their tokens have expired).
        "-c", "mcp_servers={}",
    ]
    if CODEX_MODEL:
        command += ["-m", CODEX_MODEL]
    if CODEX_EFFORT:
        command += ["-c", f'model_reasoning_effort="{CODEX_EFFORT}"']
    for image in page_images:
        command += ["-i", image]

    # The prompt goes over stdin, not argv: `-i` is variadic and would otherwise
    # swallow a trailing positional prompt, and page text can be large.
    attached = (
        "The rendered page images are attached to this message; read them for "
        "layout, colour, and screenshots.\n\n"
        if page_images
        else ""
    )
    prompt = (
        f"{SYSTEM_PROMPT}\n\n"
        f"{attached}"
        f"{user_prompt}\n\n"
        "Reply with only the plan object matching the required schema."
    )

    proc = _run_cli(command, workdir, "Codex", stdin_text=prompt)

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()[-400:]
        raise BackendError(f"Codex failed: {detail}")

    if os.path.exists(reply_path):
        with open(reply_path) as handle:
            reply = handle.read()
    else:
        reply = proc.stdout

    return strip_nulls(_parse_plan_text(reply, "Codex"))


def run_chunk(
    backend_id: str, user_prompt: str, page_images: list[str], workdir: str
) -> dict[str, Any]:
    if backend_id == "claude-cli":
        return _run_claude_cli(user_prompt, page_images, workdir)
    if backend_id == "codex-cli":
        return _run_codex_cli(user_prompt, page_images, workdir)
    if backend_id == "anthropic":
        return _run_anthropic(user_prompt, page_images)
    if backend_id == "openai":
        return _run_openai(user_prompt, page_images)
    raise BackendError(f"Unknown backend: {backend_id}")
