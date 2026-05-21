#!/usr/bin/env python3
"""Lint the LLM wiki: orphans, dangling [[wiki-links]], stale Updated: dates.

Usage:  python3 wiki/lint.py [--wiki-dir wiki] [--stale-days 90]

Exit code 0 = clean, 1 = issues found (suitable for cron / CI).
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

WIKI_LINK_RX = re.compile(r"\[\[([a-zA-Z0-9_\-./]+)\]\]")
UPDATED_RX = re.compile(r"^\s*\*\*Updated:\*\*\s*(\d{4}-\d{2}-\d{2})", re.MULTILINE)


def find_pages(wiki_dir: Path) -> list[Path]:
    return sorted(p for p in wiki_dir.rglob("*.md")
                  if p.name not in ("index.md", "log.md", "CLAUDE.md"))


def stem_index(pages: list[Path]) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for p in pages:
        out[p.stem] = p
    return out


def parse_links(text: str) -> set[str]:
    return set(WIKI_LINK_RX.findall(text))


def lint_dangling_links(pages: list[Path], stems: dict[str, Path],
                        index_text: str) -> list[str]:
    issues = []
    for p in pages:
        for tgt in parse_links(p.read_text()):
            if tgt not in stems and tgt != "CLAUDE":
                issues.append(f"  {p.relative_to(p.parents[1])}: dangling [[{tgt}]]")
    for tgt in parse_links(index_text):
        if tgt not in stems and tgt != "CLAUDE":
            issues.append(f"  index.md: dangling [[{tgt}]]")
    return issues


def lint_orphans(pages: list[Path], index_text: str) -> list[str]:
    """Page is orphaned if not linked from index.md AND not linked from any page."""
    referenced: set[str] = set()
    referenced |= parse_links(index_text)
    # Index also references pages by relative path in markdown links
    for m in re.finditer(r"\]\((\w[\w\-./]*?)\.md\)", index_text):
        referenced.add(Path(m.group(1)).stem)
    for p in pages:
        referenced |= parse_links(p.read_text())
    return [f"  {p.relative_to(p.parents[1])}: not referenced from index.md or any page"
            for p in pages if p.stem not in referenced]


def lint_stale(pages: list[Path], stale_days: int) -> list[str]:
    today = dt.date.today()
    issues = []
    for p in pages:
        m = UPDATED_RX.search(p.read_text())
        if not m:
            issues.append(f"  {p.relative_to(p.parents[1])}: missing **Updated:** line")
            continue
        try:
            d = dt.date.fromisoformat(m.group(1))
        except ValueError:
            issues.append(f"  {p.relative_to(p.parents[1])}: bad date {m.group(1)!r}")
            continue
        age = (today - d).days
        if age > stale_days:
            issues.append(f"  {p.relative_to(p.parents[1])}: stale ({age} days)")
    return issues


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wiki-dir", default=str(Path(__file__).parent),
                    help="Wiki root (default: dir of this script)")
    ap.add_argument("--stale-days", type=int, default=90)
    args = ap.parse_args()

    wiki = Path(args.wiki_dir).resolve()
    if not wiki.is_dir():
        print(f"Not a directory: {wiki}", file=sys.stderr)
        return 2

    index = wiki / "index.md"
    if not index.exists():
        print(f"Missing index.md at {index}", file=sys.stderr)
        return 2

    pages = find_pages(wiki)
    stems = stem_index(pages)
    index_text = index.read_text()

    print(f"Linting {len(pages)} entity pages in {wiki}")

    sections = [
        ("dangling [[wiki-links]]", lint_dangling_links(pages, stems, index_text)),
        ("orphan pages",            lint_orphans(pages, index_text)),
        (f"stale (>{args.stale_days}d)", lint_stale(pages, args.stale_days)),
    ]

    total = 0
    for label, issues in sections:
        print(f"\n{label}: {len(issues)}")
        for line in issues:
            print(line)
        total += len(issues)

    print(f"\nTotal issues: {total}")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
