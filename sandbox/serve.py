#!/usr/bin/env python3
"""Minimal scoreboard: stdlib-only HTTP server over results/*.json.

    python3 harness/serve.py   ->  http://localhost:8765
"""
from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX = ROOT / "frontend" / "index.html"

# Only ever used to sanitize a path segment before it touches the filesystem.
_AGENT_NAME_RE = re.compile(r"^[\w-]+$")


def _check_function_names(agent_name: str) -> list[str]:
    """check_* function names from evals/<agent>/properties.py, read as text (no
    import) so this stdlib-only server never has to load router/requests."""
    path = ROOT / "evals" / agent_name / "properties.py"
    if not path.exists():
        return []
    return re.findall(r"^def (check_\w+)", path.read_text(), re.MULTILINE)


def _rubric_bullets(agent_name: str) -> list[str]:
    """Same '-'/'*' bullet convention as judges.py's _parse_rubric, kept independent
    so serve.py has no import on judges.py (which pulls in router -> requests)."""
    path = ROOT / "evals" / agent_name / "rubric.md"
    if not path.exists():
        return []
    return [line.lstrip("-* ").strip() for line in path.read_text().splitlines()
            if line.strip().startswith(("-", "*"))]


def _read_json(path):
    """Read a COMMITTED repo file (cases.json / snapshot.json).

    Deliberately raises: a malformed committed file is a broken repo, and the golden
    principle is fail loud, never a placeholder — serving a partial exam list would
    hide it. The only thing added here is which file, since a bare JSONDecodeError in
    a server traceback does not say.
    """
    try:
        return json.loads(path.read_text())
    except ValueError as exc:
        raise ValueError(f"{path.relative_to(ROOT)}: {exc}") from exc


def _exams_payload() -> dict:
    """Per agent: exam mode, not_verified note, and each case's id/split/input/expected.
    Properties-mode agents also get check_* names + rubric bullets, when those files
    exist."""
    out = {}
    for agent_dir in sorted((ROOT / "evals").iterdir()):
        cases_path = agent_dir / "cases.json"
        if not agent_dir.is_dir() or not cases_path.exists():
            continue
        exam = _read_json(cases_path)
        name = agent_dir.name
        mode = exam.get("mode", "labels")
        entry = {
            "mode": mode,
            "not_verified": exam.get("not_verified"),
            "cases": [
                {"id": c["id"], "split": c.get("split", "train"),
                 "input": c["input"], "expected": c["expected"]}
                for c in exam.get("cases", [])
            ],
        }
        if mode == "properties":
            checks = _check_function_names(name)
            if checks:
                entry["check_functions"] = checks
            bullets = _rubric_bullets(name)
            if bullets:
                entry["rubric"] = bullets
        out[name] = entry
    return out


def _snapshots_payload() -> dict:
    """Every evals/*/snapshot.json, keyed by agent."""
    out = {}
    for agent_dir in sorted((ROOT / "evals").iterdir()):
        snap_path = agent_dir / "snapshot.json"
        if agent_dir.is_dir() and snap_path.exists():
            out[agent_dir.name] = _read_json(snap_path)
    return out


def _live_payload(agent: str) -> list:
    """Parsed lines of results/live/<agent>.jsonl. Missing file -> [], never a 500.

    cmd_live appends to this file with no locking or fsync, so a truncated final line
    is an expected state of a live log, not a corrupt repo — one bad line must not
    blind the whole feed. Bad lines are SURFACED as a _parse_error entry rather than
    dropped: "fail loud" means never silently pretending the data was fine, which is
    not the same as refusing to serve the other 99 records.
    """
    if not _AGENT_NAME_RE.match(agent):
        return []
    path = ROOT / "results" / "live" / f"{agent}.jsonl"
    if not path.exists():
        return []
    lines = []
    for lineno, raw_line in enumerate(path.read_text().splitlines(), 1):
        raw_line = raw_line.strip()
        if not raw_line:  # a trailing newline splits into a blank final element
            continue
        try:
            lines.append(json.loads(raw_line))
        except ValueError as exc:
            lines.append({"_parse_error": str(exc), "_line": lineno})
    return lines


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/results":
            results = [json.loads(p.read_text())
                       for p in sorted((ROOT / "results").glob("*.json"))]
            self._send(200, "application/json",
                       json.dumps(results, ensure_ascii=False).encode())
        elif self.path == "/api/exams":
            self._send(200, "application/json",
                       json.dumps(_exams_payload(), ensure_ascii=False).encode())
        elif self.path == "/api/snapshots":
            self._send(200, "application/json",
                       json.dumps(_snapshots_payload(), ensure_ascii=False).encode())
        elif self.path.startswith("/api/live/"):
            agent = self.path[len("/api/live/"):]
            self._send(200, "application/json",
                       json.dumps(_live_payload(agent), ensure_ascii=False).encode())
        elif self.path in ("/", "/index.html"):
            self._send(200, "text/html", INDEX.read_bytes())
        else:
            self._send(404, "text/plain", b"not found")

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print("scoreboard: http://localhost:8765")
    HTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
