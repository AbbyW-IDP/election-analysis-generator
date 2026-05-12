"""
tests/test_dry_run.py
---------------------
Tests for the --dry-run flag on sync-sources (LoadSummary.sync and
cli.sync_sources).

Responsibilities:
  - LoadSummary.sync(dry_run=True) returns a preview dict of what would be
    loaded but makes no writes to the database.
  - LoadSummary.sync(dry_run=False) (default) still writes as before.
  - cli.sync_sources --dry-run passes dry_run=True to LoadSummary.sync and
    prints the expected output without calling any DB-mutating methods.

DB interactions are tested against a real in-memory ElectionDatabase (via
the db fixture from conftest). CLI tests mock ElectionDatabase and LoadSummary
because they are testing argument parsing and output formatting only — not
loader or DB logic.
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import election_analysis_generator.cli as cli
from election_analysis_generator.db import ElectionDatabase
from election_analysis_generator.loader import LoadSummary
from tests.conftest import make_elections_config, make_source_csv


# ---------------------------------------------------------------------------
# CLI test helpers (kept local — not reusable outside this module)
# ---------------------------------------------------------------------------


def _make_loader_mock(results: dict) -> MagicMock:
    mock = MagicMock()
    mock.sync.return_value = results
    return mock


def _make_db_ctx() -> tuple[MagicMock, MagicMock]:
    """Return (context-manager mock, inner db mock) for patching ElectionDatabase."""
    inner = MagicMock()
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=inner)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx, inner


# ---------------------------------------------------------------------------
# LoadSummary.sync dry_run=True — real in-memory DB
# ---------------------------------------------------------------------------


class TestLoadSummaryDryRun:
    def test_returns_preview_dict(self, db: ElectionDatabase, tmp_path: Path) -> None:
        """dry_run=True returns filename -> (election_name, new_names) for each
        would-be-loaded election."""
        sources = tmp_path / "sources"
        sources.mkdir()
        make_elections_config(tmp_path / "elections.csv")
        make_source_csv(sources)

        result = LoadSummary(db).sync(
            sources_dir=sources,
            config_path=tmp_path / "elections.csv",
            dry_run=True,
        )

        assert "2026-general.csv" in result
        election_name, new_names = result["2026-general.csv"]
        assert election_name == "2026 General Primary"
        assert isinstance(new_names, list)

    def test_does_not_insert_election(self, db: ElectionDatabase, tmp_path: Path) -> None:
        """dry_run=True must not write any election rows to the database."""
        sources = tmp_path / "sources"
        sources.mkdir()
        make_elections_config(tmp_path / "elections.csv")
        make_source_csv(sources)

        LoadSummary(db).sync(
            sources_dir=sources,
            config_path=tmp_path / "elections.csv",
            dry_run=True,
        )

        assert len(db.get_all_elections()) == 0

    def test_does_not_register_file(self, db: ElectionDatabase, tmp_path: Path) -> None:
        """dry_run=True must not register the file in loaded_files."""
        sources = tmp_path / "sources"
        sources.mkdir()
        make_elections_config(tmp_path / "elections.csv")
        make_source_csv(sources)

        LoadSummary(db).sync(
            sources_dir=sources,
            config_path=tmp_path / "elections.csv",
            dry_run=True,
        )

        assert not db.is_file_loaded("2026-general.csv")

    def test_skips_already_loaded(self, db: ElectionDatabase, tmp_path: Path) -> None:
        """dry_run=True excludes files already in loaded_files from the preview."""
        sources = tmp_path / "sources"
        sources.mkdir()
        make_elections_config(tmp_path / "elections.csv")
        make_source_csv(sources)

        # Load it for real first, then dry-run should see nothing pending
        LoadSummary(db).sync(
            sources_dir=sources,
            config_path=tmp_path / "elections.csv",
        )
        result = LoadSummary(db).sync(
            sources_dir=sources,
            config_path=tmp_path / "elections.csv",
            dry_run=True,
        )

        assert result == {}

    def test_skips_missing_source_file(self, db: ElectionDatabase, tmp_path: Path) -> None:
        """dry_run=True excludes elections whose source CSV is absent."""
        sources = tmp_path / "sources"
        sources.mkdir()
        make_elections_config(tmp_path / "elections.csv")
        # intentionally do NOT create the source CSV

        result = LoadSummary(db).sync(
            sources_dir=sources,
            config_path=tmp_path / "elections.csv",
            dry_run=True,
        )

        assert result == {}

    def test_empty_config_returns_empty(self, db: ElectionDatabase, tmp_path: Path) -> None:
        """dry_run=True with no elections in elections.csv returns {}."""
        sources = tmp_path / "sources"
        sources.mkdir()
        (tmp_path / "elections.csv").write_text(
            "name,year,election_date,summary_file\n"
        )

        result = LoadSummary(db).sync(
            sources_dir=sources,
            config_path=tmp_path / "elections.csv",
            dry_run=True,
        )

        assert result == {}

    def test_already_loaded_excluded_unloaded_included(
        self, db: ElectionDatabase, tmp_path: Path
    ) -> None:
        """When two elections are configured and one is already loaded, only the
        unloaded one appears in the dry-run preview."""
        sources = tmp_path / "sources"
        sources.mkdir()
        (tmp_path / "elections.csv").write_text(
            "name,year,election_date,category,summary_file\n"
            "2022 General Primary,2022,2022-06-28,General Primary,2022-general.csv\n"
            "2026 General Primary,2026,2026-04-07,General Primary,2026-general.csv\n"
        )
        make_source_csv(sources, "2022-general.csv")
        make_source_csv(sources, "2026-general.csv")

        # Load 2022 for real first
        config_2022_only = tmp_path / "elections_2022_only.csv"
        config_2022_only.write_text(
            "name,year,election_date,category,summary_file\n"
            "2022 General Primary,2022,2022-06-28,General Primary,2022-general.csv\n"
        )
        LoadSummary(db).sync(sources_dir=sources, config_path=config_2022_only)

        # Dry-run against the full config — only 2026 should appear
        result = LoadSummary(db).sync(
            sources_dir=sources,
            config_path=tmp_path / "elections.csv",
            dry_run=True,
        )

        assert "2022-general.csv" not in result
        assert "2026-general.csv" in result


# ---------------------------------------------------------------------------
# CLI --dry-run flag (mocked DB and loader — testing wiring only)
# ---------------------------------------------------------------------------


class TestSyncSourcesCLIDryRun:
    def test_prints_dry_run_header(self) -> None:
        """--dry-run prints a '[dry run]' prefix on the scanning line."""
        ctx, _ = _make_db_ctx()
        loader = _make_loader_mock({"2026-general.csv": ("2026 General Primary", [])})

        out = io.StringIO()
        with (
            redirect_stdout(out),
            patch("election_analysis_generator.cli.ElectionDatabase", return_value=ctx),
            patch("election_analysis_generator.cli.LoadSummary", return_value=loader),
            patch("sys.argv", ["sync-sources", "--dry-run"]),
        ):
            cli.sync_sources()

        assert "[dry run]" in out.getvalue()

    def test_prints_would_load_line(self) -> None:
        """--dry-run prints a 'Would load' line for each pending election."""
        ctx, _ = _make_db_ctx()
        loader = _make_loader_mock({"2026-general.csv": ("2026 General Primary", [])})

        out = io.StringIO()
        with (
            redirect_stdout(out),
            patch("election_analysis_generator.cli.ElectionDatabase", return_value=ctx),
            patch("election_analysis_generator.cli.LoadSummary", return_value=loader),
            patch("sys.argv", ["sync-sources", "--dry-run"]),
        ):
            cli.sync_sources()

        assert "Would load" in out.getvalue()

    @pytest.mark.parametrize("argv, expected", [
        pytest.param(["sync-sources", "--dry-run"], True,  id="dry-run"),
        pytest.param(["sync-sources"],              False, id="normal"),
    ])
    def test_passes_dry_run_flag_to_sync(self, argv: list[str], expected: bool) -> None:
        """dry_run kwarg passed to LoadSummary.sync matches the CLI flag."""
        ctx, _ = _make_db_ctx()
        loader = _make_loader_mock({})

        with (
            patch("election_analysis_generator.cli.ElectionDatabase", return_value=ctx),
            patch("election_analysis_generator.cli.LoadSummary", return_value=loader),
            patch("sys.argv", argv),
        ):
            cli.sync_sources()

        assert loader.sync.call_args.kwargs.get("dry_run") is expected

    @pytest.mark.parametrize("argv", [
        pytest.param(["sync-sources", "--dry-run"], id="dry-run"),
        pytest.param(["sync-sources"],              id="normal"),
    ])
    def test_empty_results_prints_shared_message(self, argv: list[str]) -> None:
        """Both modes print the same message when there are no elections to load."""
        ctx, _ = _make_db_ctx()
        loader = _make_loader_mock({})

        out = io.StringIO()
        with (
            redirect_stdout(out),
            patch("election_analysis_generator.cli.ElectionDatabase", return_value=ctx),
            patch("election_analysis_generator.cli.LoadSummary", return_value=loader),
            patch("sys.argv", argv),
        ):
            cli.sync_sources()

        assert "No new elections found." in out.getvalue()

    def test_normal_run_does_not_print_dry_run(self) -> None:
        """Without --dry-run, output must not contain '[dry run]'."""
        ctx, _ = _make_db_ctx()
        loader = _make_loader_mock({"2026-general.csv": ("2026 General Primary", [])})

        out = io.StringIO()
        with (
            redirect_stdout(out),
            patch("election_analysis_generator.cli.ElectionDatabase", return_value=ctx),
            patch("election_analysis_generator.cli.LoadSummary", return_value=loader),
            patch("sys.argv", ["sync-sources"]),
        ):
            cli.sync_sources()

        assert "[dry run]" not in out.getvalue()
        assert "loaded successfully" in out.getvalue()
