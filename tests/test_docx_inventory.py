"""DOC-X documentation-index drift checks using disposable file trees."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'tools/docx_inventory.py'
SPEC = importlib.util.spec_from_file_location('docx_inventory', SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
# Dataclasses resolve annotation modules through sys.modules on import.
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _fixture(tmp_path: Path) -> Path:
    """Create a complete minimal fake repository for source-only inspection."""
    source = tmp_path / 'src/rolling_thunder'
    tests = tmp_path / 'tests'
    docs = tmp_path / 'docs/engineering'
    source.mkdir(parents=True)
    tests.mkdir()
    docs.mkdir(parents=True)
    (source / 'component.py').write_text('"""Fake component."""\n')
    (tests / 'test_component.py').write_text('"""Fake test."""\n')
    (docs / 'source-file-index.md').write_text(
        '**Cataloged Python modules: 1.**\n'
        '`src/rolling_thunder/component.py`\n'
    )
    (docs / 'test-index.md').write_text('`tests/test_component.py`\n')
    (docs / 'index.md').write_text('[Source](source-file-index.md)\n')
    (tmp_path / 'AGENTS.md').write_text('Repository fixture.\n')
    return tmp_path


def test_current_checkout_has_complete_indexes_and_valid_links() -> None:
    """Guard the exact reviewed source/test/docs baseline against drift."""
    report = MODULE.inspect(SCRIPT.parents[1])
    assert report.source_actual > 300
    assert report.test_actual > 300
    assert report.failures == ()


def test_detects_missing_source_stale_test_and_wrong_count(tmp_path: Path) -> None:
    """A check must not be green just because reference files exist."""
    root = _fixture(tmp_path)
    (root / 'src/rolling_thunder/new_worker.py').write_text('"""Worker."""\n')
    (root / 'tests/test_component.py').unlink()
    failures = MODULE.inspect(root).failures
    assert any('missing src/rolling_thunder/new_worker.py' in msg for msg in failures)
    assert any('stale tests/test_component.py' in msg for msg in failures)
    assert any('displayed module count' in msg for msg in failures)


def test_local_broken_link_is_detected_without_network(tmp_path: Path) -> None:
    """Local references are checked, but remote URLs are not fetched."""
    root = _fixture(tmp_path)
    path = root / 'docs/engineering/index.md'
    path.write_text('[Missing](./gone.md) and [External](https://example.com/)\n')
    report = MODULE.inspect(root)
    assert report.local_links == 1
    assert any('broken local link' in msg for msg in report.failures)


def test_corrected_fixture_is_clean(tmp_path: Path) -> None:
    """No false error for a complete catalog and valid relative document link."""
    assert MODULE.inspect(_fixture(tmp_path)).failures == ()
