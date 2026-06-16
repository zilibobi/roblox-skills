#!/usr/bin/env python3
"""Roblox creator-docs search tool.

Keeps a local, auto-updating clone of github.com/Roblox/creator-docs and runs
ranked full-text search over it. Designed to be called by an agent: it prints
ranked `path:line` hits with trimmed snippets so the agent can then Read the
top files in full and summarize.

Why a local clone instead of live fetching create.roblox.com?
  Live fetch can only grep a single page at a time and the official index does
  not list methods/properties. A clone lets us grep all ~2200 files (API YAML
  *and* the guide markdown) at once, which is the thing live fetch can't do.

Usage:
    python robloxdocs.py "anchored part physics"
    python robloxdocs.py "TweenService:Create" --top 5 --context 4
    python robloxdocs.py --update            # force a git pull, then exit
    python robloxdocs.py "raycast" --no-update   # skip the staleness check

No third-party dependencies. Cross-platform (Linux/macOS/Windows). Requires
`git` on PATH. Uses `ripgrep` (rg) or `git grep` if available for speed, else
falls back to a pure-Python scan.
"""

from __future__ import annotations

import argparse
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_URL = "https://github.com/Roblox/creator-docs"
DEFAULT_MAX_AGE_HOURS = 24
SEARCH_SUBDIR = os.path.join("content", "en-us")
SENTINEL = ".robloxdocs_last_update"

TEXT_EXTS = {".md", ".yaml", ".yml", ".txt"}


# --------------------------------------------------------------------------- #
# Clone location + freshness
# --------------------------------------------------------------------------- #
def cache_root() -> Path:
    """Per-OS cache directory, overridable with ROBLOX_DOCS_CACHE."""
    override = os.environ.get("ROBLOX_DOCS_CACHE")
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Caches")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return Path(base) / "roblox-docs-explorer"


def repo_path() -> Path:
    return cache_root() / "creator-docs"


def _run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd, cwd=str(cwd) if cwd else None,
        capture_output=True, text=True, check=check,
    )


def _have(tool: str) -> bool:
    return shutil.which(tool) is not None


def _touch_sentinel(repo: Path) -> None:
    (repo / SENTINEL).write_text(str(int(time.time())), encoding="utf-8")


def _is_stale(repo: Path, max_age_hours: float) -> bool:
    sentinel = repo / SENTINEL
    if not sentinel.exists():
        return True
    age = time.time() - sentinel.stat().st_mtime
    return age > max_age_hours * 3600


def ensure_repo(max_age_hours: float, do_update: bool, force_update: bool = False) -> Path:
    """Clone if missing; pull if stale. Offline failures degrade gracefully."""
    if not _have("git"):
        sys.exit("error: `git` is required but was not found on PATH.")

    repo = repo_path()
    if not (repo / ".git").exists():
        print(f"[robloxdocs] cloning {REPO_URL} -> {repo} (first run, ~1 min)...",
              file=sys.stderr)
        repo.parent.mkdir(parents=True, exist_ok=True)
        try:
            _run(["git", "clone", "--depth", "1", REPO_URL, str(repo)])
        except subprocess.CalledProcessError as exc:
            sys.exit(f"error: clone failed:\n{exc.stderr}")
        _touch_sentinel(repo)
        return repo

    if force_update or (do_update and _is_stale(repo, max_age_hours)):
        print("[robloxdocs] docs are stale, pulling latest...", file=sys.stderr)
        result = _run(["git", "pull", "--ff-only", "--depth", "1"], cwd=repo, check=False)
        if result.returncode == 0:
            _touch_sentinel(repo)
        else:
            # Almost always offline. Keep using the existing clone.
            print("[robloxdocs] warning: pull failed (offline?). Using cached docs.",
                  file=sys.stderr)
    return repo


# --------------------------------------------------------------------------- #
# Search
# --------------------------------------------------------------------------- #
def tokenize(query: str) -> list[str]:
    """Split a query into search terms — no semantic filtering.

    Keeps dotted/colon API forms intact (e.g. `TweenService:Create`) and also
    emits their components so a hit on either ranks. We deliberately don't drop
    "common" words here: IDF weighting (below) handles relevance, so a word like
    `part` simply earns a low weight rather than being discarded — which means
    real API names like `Create` or `Get` are never thrown away by mistake.
    """
    raw = re.findall(r"[A-Za-z0-9_:.]+", query)
    terms: list[str] = []
    for tok in raw:
        terms.append(tok)
        for part in re.split(r"[:.]", tok):
            if part and part != tok:
                terms.append(part)
    seen, out = set(), []
    for t in terms:
        low = t.lower()
        if low in seen or len(t) < 2:  # 1-char tokens carry no signal
            continue
        seen.add(low)
        out.append(t)
    return out or [query.strip()]


def corpus_size(repo: Path) -> int:
    """Number of text docs — the N in IDF. Cheap and good enough as a constant."""
    if _have("git"):
        proc = _run(["git", "ls-files", SEARCH_SUBDIR], cwd=repo, check=False)
        n = sum(1 for f in proc.stdout.splitlines()
                if Path(f).suffix.lower() in TEXT_EXTS)
        if n:
            return n
    return sum(1 for p in (repo / SEARCH_SUBDIR).rglob("*")
               if p.suffix.lower() in TEXT_EXTS)


def _grep_term(repo: Path, term: str) -> dict[str, list[int]]:
    """Return {relative_path: [line numbers]} where `term` appears (literal, ci).

    Literal (fixed-string) matching is what we want here: API names contain `:`
    and `.`, which we must match verbatim, not as regex. Tries ripgrep, then
    git grep, then a pure-Python walk.
    """
    search_dir = repo / SEARCH_SUBDIR
    hits: dict[str, list[int]] = {}

    def add(path: str, line: int) -> None:
        rel = (os.path.relpath(path, repo) if os.path.isabs(path) else path).replace("\\", "/")
        # Search only human docs. rg/git grep otherwise also scan huge generated
        # artifacts (openapi.json, cloud.docs.json) that swamp results.
        if Path(rel).suffix.lower() not in TEXT_EXTS:
            return
        hits.setdefault(rel, []).append(line)

    if _have("rg"):
        proc = _run(["rg", "--no-heading", "--line-number", "--ignore-case",
                     "--fixed-strings", term, str(search_dir)], check=False)
    elif _have("git"):
        proc = _run(["git", "grep", "-n", "-I", "-i", "-F", "-e", term,
                     "--", SEARCH_SUBDIR], cwd=repo, check=False)
    else:
        needle = term.lower()
        for root, _dirs, files in os.walk(search_dir):
            for fn in files:
                if Path(fn).suffix.lower() not in TEXT_EXTS:
                    continue
                fp = Path(root) / fn
                try:
                    for i, line in enumerate(
                            fp.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                        if needle in line.lower():
                            add(str(fp), i)
                except OSError:
                    continue
        return hits

    for ln in proc.stdout.splitlines():
        m = re.match(r"(.*?):(\d+):", ln)
        if m:
            add(m.group(1), int(m.group(2)))
    return hits


def search(repo: Path, query: str, top_k: int,
           context: int) -> list[tuple[str, float, list[int]]]:
    """Rank docs by IDF-weighted term frequency.

    Each query term is weighted by how rare it is across the corpus (inverse
    document frequency). A file's score sums, per term, its match count times
    that term's IDF — so a handful of hits on a rare term (`Anchored`) outranks
    hundreds of hits on a ubiquitous one (`part`). Exact filename/API-name
    matches and frontmatter hits get a further IDF-scaled boost, since the doc
    *named* after the term is almost always the one you want.
    """
    terms = tokenize(query)
    n_docs = max(corpus_size(repo), 1)

    per_term = {t: _grep_term(repo, t) for t in terms}
    idf = {
        t: math.log((n_docs + 1) / (len(files) + 1)) + 1.0
        for t, files in per_term.items()
    }

    scores: dict[str, float] = {}
    all_lines: dict[str, set[int]] = {}
    for term, files in per_term.items():
        w = idf[term]
        tl = term.lower()
        for path, lines in files.items():
            stem = Path(path).stem.lower()
            # Saturate term frequency (BM25-style): the 50th hit in a file adds
            # far less than the 2nd, so a long doc can't win on bulk alone.
            s = (1 + math.log(len(lines))) * w
            if tl == stem:
                s += 25 * w        # doc named exactly after the term
            elif tl in stem:
                s += 8 * w         # partial filename match
            if any(ln <= 40 for ln in lines):
                s += 3 * w         # hit in YAML frontmatter (name/summary)
            scores[path] = scores.get(path, 0.0) + s
            all_lines.setdefault(path, set()).update(lines)

    ranked = sorted(scores, key=lambda p: scores[p], reverse=True)[:top_k]
    return [(p, scores[p], sorted(all_lines[p])) for p in ranked]


def snippet(repo: Path, path: str, lines: list[int], context: int, max_hunks: int = 3) -> str:
    fp = repo / path
    try:
        content = fp.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return "    (could not read file)"
    out = []
    for ln in lines[:max_hunks]:
        lo = max(1, ln - context)
        hi = min(len(content), ln + context)
        for i in range(lo, hi + 1):
            marker = ">" if i == ln else " "
            out.append(f"    {marker} {i}: {content[i - 1].rstrip()}")
        out.append("")
    return "\n".join(out).rstrip()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Search the Roblox creator-docs.")
    p.add_argument("query", nargs="?", help="search query")
    p.add_argument("--top", type=int, default=8, help="max files to return")
    p.add_argument("--context", type=int, default=3, help="context lines per hit")
    p.add_argument("--max-age", type=float, default=DEFAULT_MAX_AGE_HOURS,
                   help="hours before docs are considered stale")
    p.add_argument("--no-update", action="store_true", help="skip the staleness check")
    p.add_argument("--update", action="store_true", help="force a git pull then exit")
    args = p.parse_args(argv)

    repo = ensure_repo(args.max_age, do_update=not args.no_update, force_update=args.update)

    if args.update:
        print(f"[robloxdocs] updated. Clone at {repo}")
        return 0

    if not args.query:
        p.error("a query is required (or use --update)")

    results = search(repo, args.query, args.top, args.context)
    if not results:
        print(f'No matches for "{args.query}".')
        print("Try broader/different terms, or check the index of all APIs:")
        print(f"  {repo / SEARCH_SUBDIR / 'reference' / 'engine'}")
        print("  (or https://create.roblox.com/docs/reference/engine/llms.txt)")
        return 0

    print(f'Top {len(results)} matches for "{args.query}" (clone: {repo}):\n')
    for i, (path, sc, lines) in enumerate(results, 1):
        print(f"{i}. {path}  (score {sc:.0f}, {len(lines)} hit(s))")
        print(snippet(repo, path, lines, args.context))
        print()
    print("Next: Read the full file(s) above for the complete reference, "
          "then summarize with citations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
