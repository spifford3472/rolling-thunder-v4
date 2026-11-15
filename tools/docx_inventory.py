"""Verify current engineering indexes and local Markdown links without host access.

This source-only check makes no device, network, service, or database changes.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

SOURCE = 'src/rolling_thunder'
TESTS = 'tests'
REFERENCES = re.compile(r'(?:src/rolling_thunder|tests)/[A-Za-z0-9_./-]+\.py')
MARKDOWN_LINK = re.compile(r'(?<!!)\[[^\]]+\]\(([^)]+)\)')
COUNT = re.compile(r'\*\*Cataloged Python modules: (\d+)(?:[. ]|\*)')


@dataclass(frozen=True)
class Inventory:
    """Deterministic source/test/doc evidence for one checkout."""

    source_actual: int
    test_actual: int
    failures: tuple[str, ...]
    local_links: int


def inspect(root: Path) -> Inventory:
    """Validate an isolated source tree and collect actionable drift reports."""
    failures: list[str] = []
    counts: dict[str, int] = {}
    for prefix, document in (
        (SOURCE, 'source-file-index.md'), (TESTS, 'test-index.md')
    ):
        expected = {p.relative_to(root).as_posix() for p in (root / prefix).rglob('*.py')}
        doc = root / 'docs/engineering' / document
        text = doc.read_text(encoding='utf-8')
        listed = {p for p in REFERENCES.findall(text) if p.startswith(prefix + '/')}
        counts[prefix] = len(expected)
        failures.extend(f'{document}: missing {path}' for path in sorted(expected - listed))
        failures.extend(f'{document}: stale {path}' for path in sorted(listed - expected))
        if document == 'source-file-index.md':
            match = COUNT.search(text)
            if match is None or int(match.group(1)) != len(expected):
                failures.append(f'{document}: displayed module count does not match {len(expected)}')

    links = 0
    for document in sorted((root / 'docs').rglob('*.md')) + [root / 'AGENTS.md']:
        content = document.read_text(encoding='utf-8')
        for match in MARKDOWN_LINK.finditer(content):
            target = match.group(1).strip().split(' ', 1)[0].strip('<>')
            if not target or target.startswith(('#', 'mailto:', 'data:')):
                continue
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path:
                continue
            # Ignore template variables; they are not local file references.
            if '{' in parsed.path or '}' in parsed.path:
                continue
            links += 1
            if not (document.parent / unquote(parsed.path)).exists():
                failures.append(
                    f'{document.relative_to(root)}: broken local link {target}'
                )

    return Inventory(counts[SOURCE], counts[TESTS], tuple(failures), links)


def main() -> int:
    """Print a bounded, reproducible report; fail only on confirmed drift."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    result = inspect(args.root.resolve())
    print(
        f'DOCX inventory: source={result.source_actual}, '
        f'tests={result.test_actual}, local_links={result.local_links}, '
        f'drift={len(result.failures)}'
    )
    for failure in result.failures:
        print(f'DOCX DRIFT: {failure}')
    return 1 if result.failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
