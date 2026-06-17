"""Verify that code snippets cited by the manuscript point at real files.

PT: O diferenciador do livro é "código que corre, não código pedagógico". Cada
bloco de código no manuscrito começa por um comentário com o caminho do
ficheiro real que cita (ex.: ``# receita-1-.../ingest/mqtt_to_db.py (excerto)``).
Esta ferramenta varre os capítulos, extrai esses caminhos e confirma que todos
existem no repositório de código. Falha se algum capítulo citar um ficheiro que
não existe — o que impede o livro de mostrar código fantasma.

EN: The book's differentiator is "code that runs, not pedagogical code". Every
manuscript code block starts with a comment carrying the path of the real file
it cites (e.g. ``# receita-1-.../ingest/mqtt_to_db.py (excerto)``). This tool
scans the chapters, extracts those paths and checks each one exists in the code
repository. It fails when a chapter cites a file that does not exist — keeping
the book from showing phantom code.

The manuscript lives in the *private* book repository, a sibling of this one.
When it is not present (e.g. public CI), the tool skips gracefully with exit 0.

Run with::

    uv run python -m tools.verify_ebook_sync            # all chapters
    uv run python -m tools.verify_ebook_sync --cap 1     # one chapter
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANUSCRIPT_DIR = REPO_ROOT.parent / "moredevs-ebook-001" / "manuscrito-pt"

# Only treat a first-line comment as a citation when the token it carries lives
# under one of these top-level directories and ends in a known code suffix.
CITATION_DIR_PREFIXES = ("receita-", "lib_comum/", "tools/", "tests/", "pack-extra/")
CODE_SUFFIXES = {
    ".py",
    ".cpp",
    ".h",
    ".hpp",
    ".sql",
    ".json",
    ".toml",
    ".ini",
    ".sh",
    ".yml",
    ".yaml",
    ".cfg",
}
COMMENT_MARKERS = ("#", "//", "--", "<!--")
PATH_TOKEN_RE = re.compile(r"[A-Za-z0-9_./\-]+")


@dataclass(frozen=True, slots=True)
class Citation:
    """One ``path`` cited at ``line_no`` of chapter file ``chapter``."""

    chapter: str
    line_no: int
    path: str


def parse_citation_line(line: str) -> str | None:
    """Return the cited code path on *line*, or None when it is not a citation.

    PT: Devolve o caminho citado na linha, ou None se não for citação.
    EN: Returns the code path cited on the line, or None when it is not one.
    """
    stripped = line.strip()
    rest: str | None = None
    for marker in COMMENT_MARKERS:
        if stripped.startswith(marker):
            rest = stripped[len(marker) :].strip()
            break
    if rest is None:
        return None
    match = PATH_TOKEN_RE.search(rest)
    if match is None:
        return None
    token = match.group(0)
    if "/" not in token or not token.startswith(CITATION_DIR_PREFIXES):
        return None
    if Path(token).suffix not in CODE_SUFFIXES:
        return None
    return token


def extract_citations(md_text: str, chapter: str) -> list[Citation]:
    """Extract every code-path citation from one manuscript file.

    PT: Extrai todas as citações de caminho de um ficheiro de manuscrito.
    EN: Extracts every code-path citation from one manuscript file.

    A citation is the first line *inside* a fenced code block when that line is
    a comment carrying a recognised path.
    """
    citations: list[Citation] = []
    in_block = False
    expect_first = False
    for line_no, raw in enumerate(md_text.splitlines(), start=1):
        if raw.lstrip().startswith("```"):
            in_block = not in_block
            expect_first = in_block
            continue
        if in_block and expect_first:
            expect_first = False
            path = parse_citation_line(raw)
            if path is not None:
                citations.append(Citation(chapter=chapter, line_no=line_no, path=path))
    return citations


def _chapter_files(manuscript_dir: Path, cap: int | None) -> list[Path]:
    files = sorted(p for p in manuscript_dir.glob("*.md") if p.name[0].isdigit())
    if cap is None:
        return files
    prefix = f"{cap:02d}-"
    return [p for p in files if p.name.startswith(prefix)]


def verify(
    *,
    manuscript_dir: Path,
    code_root: Path,
    cap: int | None,
) -> int:
    """Check every citation and print a report. Returns a process exit code.

    PT: Verifica todas as citações e imprime um relatório.
    EN: Checks every citation and prints a report.
    """
    if not manuscript_dir.is_dir():
        print(f"[verify-ebook-sync] manuscript dir not found: {manuscript_dir}")
        print("[verify-ebook-sync] nothing to check (private manuscript absent) — skipping.")
        return 0

    files = _chapter_files(manuscript_dir, cap)
    if not files:
        scope = "all chapters" if cap is None else f"cap {cap}"
        print(f"[verify-ebook-sync] no manuscript files matched {scope} in {manuscript_dir}.")
        return 0

    total = 0
    missing: list[Citation] = []
    for md in files:
        citations = extract_citations(md.read_text(encoding="utf-8"), md.name)
        if not citations:
            print(f"  {md.name}: no code citations found")
            continue
        ok = 0
        for cite in citations:
            total += 1
            if (code_root / cite.path).exists():
                ok += 1
            else:
                missing.append(cite)
        print(f"  {md.name}: {ok}/{len(citations)} cited files exist")

    print(f"[verify-ebook-sync] {total - len(missing)}/{total} citations resolved.")
    if missing:
        print("[verify-ebook-sync] MISSING:")
        for cite in missing:
            print(f"  - {cite.chapter}:{cite.line_no} -> {cite.path}")
        return 1
    print("[verify-ebook-sync] OK — every cited snippet maps to a real file.")
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cap", type=int, default=None, help="Restrict to one chapter number.")
    parser.add_argument(
        "--manuscript-dir",
        type=Path,
        default=Path(os.environ.get("EBOOK_MANUSCRIPT_DIR", str(DEFAULT_MANUSCRIPT_DIR))),
        help="Path to the manuscript directory (defaults to the sibling book repo).",
    )
    parser.add_argument(
        "--code-root",
        type=Path,
        default=REPO_ROOT,
        help="Root of the code repository (defaults to this repo).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    return verify(
        manuscript_dir=args.manuscript_dir,
        code_root=args.code_root,
        cap=args.cap,
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
