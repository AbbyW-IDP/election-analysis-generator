"""
Tests for LoadPrecinctDetail.load_detail_excel format support.

Covers:
  - .xlsx accepted (regression: existing path still works)
  - XML SpreadsheetML .xls accepted (the format DuPage actually exports)
  - Unsupported extension raises ValueError
  - Missing file raises FileNotFoundError for both extensions
  - Election with no database id raises ValueError regardless of extension
  - Extension matching is case-insensitive (.XLS == .xls)
  - All format paths insert precinct rows correctly
  - Second load of the same file is a no-op (idempotency)
"""

from __future__ import annotations

from pathlib import Path

import openpyxl
import pytest

from src.election_analysis_generator.db import ElectionDatabase
from src.election_analysis_generator.loader import LoadSummary, LoadPrecinctDetail
from src.election_analysis_generator.models import Election


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

# Contest name and candidate used in all workbook helpers and the seeded election.
# Must survive normalize_contest_name() so _build_contest_id_map() finds a match.
_CONTEST_RAW = "FOR GOVERNOR (Vote For 1)"
_CANDIDATE    = "Jane Smith"
_SS_NS        = "urn:schemas-microsoft-com:office:spreadsheet"

CSV_HEADER = (
    "line number,contest name,choice name,party name,"
    "total votes,percent of votes,registered voters,ballots cast,"
    "num Precinct total,num Precinct rptg,over votes,under votes"
)


def _seed(db: ElectionDatabase, tmp_path: Path) -> Election:
    """Write a minimal summary CSV and load it, returning the inserted Election."""
    csv_path = tmp_path / "2026-general-primary.csv"
    csv_path.write_text(
        CSV_HEADER + "\n"
        f"1,{_CONTEST_RAW},{_CANDIDATE},D,5000,100.0,50000,10000,10,10,0,0\n"
    )
    config = {
        "name": "2026 General Primary",
        "year": 2026,
        "summary_file": csv_path.name,
        "election_date": "2026-04-07",
    }
    election, _ = LoadSummary(db).load_csv(csv_path, config)
    return election


# ---------------------------------------------------------------------------
# Workbook / file helpers (one per format)
# ---------------------------------------------------------------------------

def _make_xlsx(path: Path) -> None:
    """Write a minimal OOXML .xlsx matching the precinct detail sheet layout."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"  # type: ignore[union-attr]
    ws.append([_CONTEST_RAW])                    # row 0: contest  # type: ignore[union-attr]
    ws.append([None, None, _CANDIDATE])          # row 1: candidate header  # type: ignore[union-attr]
    ws.append([])                                # row 2: spacer  # type: ignore[union-attr]
    ws.append(["Addison 001", 1200, 50, 100, 300, 10, 460])  # row 3: precinct  # type: ignore[union-attr]
    wb.save(path)


def _make_spreadsheetml_xls(path: Path) -> None:
    """Write a minimal XML SpreadsheetML file with a .xls extension.

    This is the format DuPage County's export tool actually produces:
    a UTF-8 BOM followed by XML using the SpreadsheetML schema.
    """
    rows = [
        [_CONTEST_RAW],
        [None, None, _CANDIDATE],
        [],
        ["Addison 001", 1200, 50, 100, 300, 10, 460],
    ]
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<Workbook xmlns:ss="{_SS_NS}" xmlns="{_SS_NS}">',
        '  <Worksheet ss:Name="Sheet1">',
        '    <Table>',
    ]
    for row in rows:
        lines.append('      <Row>')
        for cell in row:
            if cell is None:
                lines.append('        <Cell><Data ss:Type="String"></Data></Cell>')
            elif isinstance(cell, (int, float)):
                lines.append(f'        <Cell><Data ss:Type="Number">{cell}</Data></Cell>')
            else:
                lines.append(f'        <Cell><Data ss:Type="String">{cell}</Data></Cell>')
        lines.append('      </Row>')
    lines += ['    </Table>', '  </Worksheet>', '</Workbook>']
    path.write_bytes(b'\xef\xbb\xbf' + '\n'.join(lines).encode('utf-8'))



# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestLoadDetailExcelFormat:

    # --- format acceptance ---

    def test_xlsx_accepted(self, db: ElectionDatabase, tmp_path: Path) -> None:
        election = _seed(db, tmp_path)
        xlsx_path = tmp_path / "detail.xlsx"
        _make_xlsx(xlsx_path)

        LoadPrecinctDetail(db).load_detail_excel(xlsx_path, election)

        assert db.is_file_loaded(xlsx_path.name)

    def test_spreadsheetml_xls_accepted(self, db: ElectionDatabase, tmp_path: Path) -> None:
        """The format DuPage actually exports: XML SpreadsheetML with a .xls extension."""
        election = _seed(db, tmp_path)
        xls_path = tmp_path / "detail.xls"
        _make_spreadsheetml_xls(xls_path)

        LoadPrecinctDetail(db).load_detail_excel(xls_path, election)

        assert db.is_file_loaded(xls_path.name)


    # --- data integrity ---

    def test_xlsx_inserts_precinct_rows(self, db: ElectionDatabase, tmp_path: Path) -> None:
        election = _seed(db, tmp_path)
        xlsx_path = tmp_path / "detail.xlsx"
        _make_xlsx(xlsx_path)

        LoadPrecinctDetail(db).load_detail_excel(xlsx_path, election)

        count = db.query(
            "SELECT COUNT(*) AS n FROM candidate_precinct_results WHERE election_id = ?",
            params=[election.id],
        ).iloc[0]["n"]
        assert count > 0

    def test_spreadsheetml_inserts_precinct_rows(self, db: ElectionDatabase, tmp_path: Path) -> None:
        election = _seed(db, tmp_path)
        xls_path = tmp_path / "detail.xls"
        _make_spreadsheetml_xls(xls_path)

        LoadPrecinctDetail(db).load_detail_excel(xls_path, election)

        count = db.query(
            "SELECT COUNT(*) AS n FROM candidate_precinct_results WHERE election_id = ?",
            params=[election.id],
        ).iloc[0]["n"]
        assert count > 0

    # --- error cases ---

    def test_unsupported_extension_raises_value_error(
        self, db: ElectionDatabase, tmp_path: Path
    ) -> None:
        election = _seed(db, tmp_path)
        bad_path = tmp_path / "detail.csv"
        bad_path.write_text("dummy")

        with pytest.raises(ValueError, match="Unsupported detail file format"):
            LoadPrecinctDetail(db).load_detail_excel(bad_path, election)

    def test_missing_xlsx_raises_file_not_found(
        self, db: ElectionDatabase, tmp_path: Path
    ) -> None:
        election = _seed(db, tmp_path)

        with pytest.raises(FileNotFoundError):
            LoadPrecinctDetail(db).load_detail_excel(tmp_path / "missing.xlsx", election)

    def test_missing_xls_raises_file_not_found(
        self, db: ElectionDatabase, tmp_path: Path
    ) -> None:
        election = _seed(db, tmp_path)

        with pytest.raises(FileNotFoundError):
            LoadPrecinctDetail(db).load_detail_excel(tmp_path / "missing.xls", election)

    def test_no_election_id_raises_value_error(
        self, db: ElectionDatabase, tmp_path: Path
    ) -> None:
        election = Election(
            id=None,
            name="2026 General Primary",
            year=2026,
            summary_file="2026-general-primary.csv",
        )
        xlsx_path = tmp_path / "detail.xlsx"
        xlsx_path.write_bytes(b"dummy")

        with pytest.raises(ValueError, match="no database id"):
            LoadPrecinctDetail(db).load_detail_excel(xlsx_path, election)

    def test_extension_matching_is_case_insensitive(
        self, db: ElectionDatabase, tmp_path: Path
    ) -> None:
        # .XLS uppercase should pass the extension guard and reach the existence check
        election = _seed(db, tmp_path)

        with pytest.raises(FileNotFoundError):
            LoadPrecinctDetail(db).load_detail_excel(tmp_path / "detail.XLS", election)

    # --- idempotency ---

    def test_load_is_idempotent(self, db: ElectionDatabase, tmp_path: Path) -> None:
        election = _seed(db, tmp_path)
        xlsx_path = tmp_path / "detail.xlsx"
        _make_xlsx(xlsx_path)
        loader = LoadPrecinctDetail(db)

        loader.load_detail_excel(xlsx_path, election)
        count_first = db.query(
            "SELECT COUNT(*) AS n FROM candidate_precinct_results WHERE election_id = ?",
            params=[election.id],
        ).iloc[0]["n"]

        loader.load_detail_excel(xlsx_path, election)
        count_second = db.query(
            "SELECT COUNT(*) AS n FROM candidate_precinct_results WHERE election_id = ?",
            params=[election.id],
        ).iloc[0]["n"]

        assert count_first == count_second
