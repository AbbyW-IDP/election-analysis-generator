"""
tests/test_dry_run.py
---------------------
Tests for the --dry-run flag on sync-sources (LoadSummary.sync and
cli.sync_sources).

Responsibilities:
  - LoadSummary.sync(dry_run=True) returns a preview dict of what would be
    loaded but makes no writes to the database.
  - LoadSummary.sync(dry_run=False) (default) still writes as before.
  - cli.sync_sources --dry-run passes dry_run=True to LoadSummary.sync,
    prints a [dry run] header and "No changes made." footer, and does not
    call any DB-mutating methods.
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

import election_analysis_generator.cli as cli
from election_analysis_generator.loader import LoadSummary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db() -> MagicMock:
    """Return a mock ElectionDatabase with the surface area sync() needs."""
    db = MagicMock()
    db.is_file_loaded.return_value = False
    db.get_election_by_name.return_value = None
    db.insert_election_with_file.return_value = (
        MagicMock(id=1, name="2026 General Primary"),
        [],
    )
    return db


def _make_db_ctx(db: MagicMock | None = None) -> tuple[MagicMock, MagicMock]:
    """Return (context-manager mock, inner db mock) for patching ElectionDatabase."""
    inner = db if db is not None else _make_db()
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=inner)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx, inner


def _make_config(path: Path, filename: str = "2026-general.csv") -> None:
    """Write a minimal elections.csv with category so the name derives correctly."""
    path.write_text(
        "name,year,election_date,category,summary_file\n"
        f"2026 General Primary,2026,2026-04-07,General Primary,{filename}\n"
    )


def _make_source_csv(sources_dir: Path, filename: str = "2026-general.csv") -> None:
    """Write a minimal source CSV that passes column validation."""
    (sources_dir / filename).write_text(
        "Contest Name,Party Name,Total Votes\n"
        "FOR GOVERNOR,D,1000\n"
    )


# ---------------------------------------------------------------------------
# LoadSummary.sync dry_run=True
# ---------------------------------------------------------------------------


class TestLoadSummaryDryRun:
    def test_returns_preview_dict(self, tmp_path: Path) -> None:
        """dry_run=True returns filename -> (election_name, new_names) for each
        would-be-loaded election."""
        sources = tmp_path / "sources"
        sources.mkdir()
        _make_config(tmp_path / "elections.csv")
        _make_source_csv(sources)

        result = LoadSummary(_make_db()).sync(
            sources_dir=sources,
            config_path=tmp_path / "elections.csv",
            dry_run=True,
        )

        assert "2026-general.csv" in result
        election_name, new_names = result["2026-general.csv"]
        assert election_name == "2026 General Primary"
        assert isinstance(new_names, list)

    def test_does_not_call_insert(self, tmp_path: Path) -> None:
        """dry_run=True must not call insert_election_with_file."""
        sources = tmp_path / "sources"
        sources.mkdir()
        _make_config(tmp_path / "elections.csv")
        _make_source_csv(sources)

        db = _make_db()
        LoadSummary(db).sync(
            sources_dir=sources,
            config_path=tmp_path / "elections.csv",
            dry_run=True,
        )

        db.insert_election_with_file.assert_not_called()

    def test_does_not_register_file(self, tmp_path: Path) -> None:
        """dry_run=True must not register the file in loaded_files."""
        sources = tmp_path / "sources"
        sources.mkdir()
        _make_config(tmp_path / "elections.csv")
        _make_source_csv(sources)

        db = _make_db()
        LoadSummary(db).sync(
            sources_dir=sources,
            config_path=tmp_path / "elections.csv",
            dry_run=True,
        )

        db.register_file.assert_not_called()

    def test_skips_already_loaded(self, tmp_path: Path) -> None:
        """dry_run=True excludes files already in loaded_files from the preview."""
        sources = tmp_path / "sources"
        sources.mkdir()
        _make_config(tmp_path / "elections.csv")
        _make_source_csv(sources)

        db = _make_db()
        db.is_file_loaded.return_value = True

        result = LoadSummary(db).sync(
            sources_dir=sources,
            config_path=tmp_path / "elections.csv",
            dry_run=True,
        )

        assert result == {}

    def test_skips_missing_source_file(self, tmp_path: Path) -> None:
        """dry_run=True excludes elections whose source CSV is absent."""
        sources = tmp_path / "sources"
        sources.mkdir()
        _make_config(tmp_path / "elections.csv")
        # intentionally do NOT create the source CSV

        result = LoadSummary(_make_db()).sync(
            sources_dir=sources,
            config_path=tmp_path / "elections.csv",
            dry_run=True,
        )

        assert result == {}

    def test_empty_config_returns_empty(self, tmp_path: Path) -> None:
        """dry_run=True with no elections in elections.csv returns {}."""
        sources = tmp_path / "sources"
        sources.mkdir()
        (tmp_path / "elections.csv").write_text(
            "name,year,election_date,summary_file\n"
        )

        result = LoadSummary(_make_db()).sync(
            sources_dir=sources,
            config_path=tmp_path / "elections.csv",
            dry_run=True,
        )

        assert result == {}

    def test_already_loaded_excluded_unloaded_included(self, tmp_path: Path) -> None:
        """When two elections are configured and one is already loaded, only the
        unloaded one appears in the dry-run preview."""
        sources = tmp_path / "sources"
        sources.mkdir()
        (tmp_path / "elections.csv").write_text(
            "name,year,election_date,category,summary_file\n"
            "2022 General Primary,2022,2022-06-28,General Primary,2022-general.csv\n"
            "2026 General Primary,2026,2026-04-07,General Primary,2026-general.csv\n"
        )
        _make_source_csv(sources, "2022-general.csv")
        _make_source_csv(sources, "2026-general.csv")

        db = _make_db()
        db.is_file_loaded.side_effect = lambda f: f == "2022-general.csv"

        result = LoadSummary(db).sync(
            sources_dir=sources,
            config_path=tmp_path / "elections.csv",
            dry_run=True,
        )

        assert "2022-general.csv" not in result
        assert "2026-general.csv" in result


# ---------------------------------------------------------------------------
# LoadSummary.sync dry_run=False (default must still write)
# ---------------------------------------------------------------------------


class TestLoadSummaryNormalSync:
    def test_default_still_inserts(self, tmp_path: Path) -> None:
        """Omitting dry_run defaults to False -- normal sync still calls
        insert_election_with_file."""
        sources = tmp_path / "sources"
        sources.mkdir()
        _make_config(tmp_path / "elections.csv")
        _make_source_csv(sources)

        db = _make_db()
        LoadSummary(db).sync(
            sources_dir=sources,
            config_path=tmp_path / "elections.csv",
        )

        db.insert_election_with_file.assert_called_once()

    def test_explicit_false_still_inserts(self, tmp_path: Path) -> None:
        """Passing dry_run=False explicitly still writes to the database."""
        sources = tmp_path / "sources"
        sources.mkdir()
        _make_config(tmp_path / "elections.csv")
        _make_source_csv(sources)

        db = _make_db()
        LoadSummary(db).sync(
            sources_dir=sources,
            config_path=tmp_path / "elections.csv",
            dry_run=False,
        )

        db.insert_election_with_file.assert_called_once()


# ---------------------------------------------------------------------------
# CLI --dry-run flag
# ---------------------------------------------------------------------------


class TestSyncSourcesCLIDryRun:
    def _make_loader_mock(
        self, results: dict
    ) -> MagicMock:
        mock = MagicMock()
        mock.sync.return_value = results
        return mock

    def test_prints_dry_run_header(self) -> None:
        """--dry-run prints a '[dry run]' prefix on the scanning line."""
        ctx, _ = _make_db_ctx()
        loader = self._make_loader_mock({"2026-general.csv": ("2026 General Primary", [])})

        out = io.StringIO()
        with (
            redirect_stdout(out),
            patch("election_analysis_generator.cli.ElectionDatabase", return_value=ctx),
            patch("election_analysis_generator.cli.LoadSummary", return_value=loader),
            patch("sys.argv", ["sync-sources", "--dry-run"]),
        ):
            cli.sync_sources()

        assert "[dry run]" in out.getvalue()

    def test_prints_no_changes_made_footer(self) -> None:
        """--dry-run always prints 'No changes made.' at the end."""
        ctx, _ = _make_db_ctx()
        loader = self._make_loader_mock({"2026-general.csv": ("2026 General Primary", [])})

        out = io.StringIO()
        with (
            redirect_stdout(out),
            patch("election_analysis_generator.cli.ElectionDatabase", return_value=ctx),
            patch("election_analysis_generator.cli.LoadSummary", return_value=loader),
            patch("sys.argv", ["sync-sources", "--dry-run"]),
        ):
            cli.sync_sources()

        assert "No changes made." in out.getvalue()

    def test_prints_would_load_line(self) -> None:
        """--dry-run prints a 'Would load' line for each pending election."""
        ctx, _ = _make_db_ctx()
        loader = self._make_loader_mock({"2026-general.csv": ("2026 General Primary", [])})

        out = io.StringIO()
        with (
            redirect_stdout(out),
            patch("election_analysis_generator.cli.ElectionDatabase", return_value=ctx),
            patch("election_analysis_generator.cli.LoadSummary", return_value=loader),
            patch("sys.argv", ["sync-sources", "--dry-run"]),
        ):
            cli.sync_sources()

        assert "Would load" in out.getvalue()

    def test_passes_dry_run_true_to_sync(self) -> None:
        """--dry-run must pass dry_run=True to LoadSummary.sync."""
        ctx, _ = _make_db_ctx()
        loader = self._make_loader_mock({})

        with (
            patch("election_analysis_generator.cli.ElectionDatabase", return_value=ctx),
            patch("election_analysis_generator.cli.LoadSummary", return_value=loader),
            patch("sys.argv", ["sync-sources", "--dry-run"]),
        ):
            cli.sync_sources()

        assert loader.sync.call_args.kwargs.get("dry_run") is True

    def test_no_changes_made_when_nothing_to_load(self) -> None:
        """--dry-run prints 'No changes made.' even when no elections are pending."""
        ctx, _ = _make_db_ctx()
        loader = self._make_loader_mock({})

        out = io.StringIO()
        with (
            redirect_stdout(out),
            patch("election_analysis_generator.cli.ElectionDatabase", return_value=ctx),
            patch("election_analysis_generator.cli.LoadSummary", return_value=loader),
            patch("sys.argv", ["sync-sources", "--dry-run"]),
        ):
            cli.sync_sources()

        assert "No changes made." in out.getvalue()

    def test_normal_run_does_not_print_dry_run(self) -> None:
        """Without --dry-run, output must not contain '[dry run]'."""
        ctx, _ = _make_db_ctx()
        loader = self._make_loader_mock({"2026-general.csv": ("2026 General Primary", [])})

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

    def test_normal_run_passes_dry_run_false(self) -> None:
        """Without --dry-run, dry_run=False must be passed to LoadSummary.sync."""
        ctx, _ = _make_db_ctx()
        loader = self._make_loader_mock({})

        with (
            patch("election_analysis_generator.cli.ElectionDatabase", return_value=ctx),
            patch("election_analysis_generator.cli.LoadSummary", return_value=loader),
            patch("sys.argv", ["sync-sources"]),
        ):
            cli.sync_sources()

        assert loader.sync.call_args.kwargs.get("dry_run") is False
