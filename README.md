# Election Analysis Generator

A tool for loading, normalising, and analysing partisan primary election results across multiple election cycles.

Current data covers DuPage County, Illinois (2014, 2018, 2022, 2026), sourced from [DuPage County Election Results](https://www.dupageresults.gov/IL/DuPage/).

---

## Repository structure

```
.
├── README.md
├── pyproject.toml
├── elections.toml              # Election metadata: names, dates, turnout figures, source files
├── elections.db                # SQLite database (generated locally, not committed)
├── sources/                    # Drop election source files here to load them
│   ├── 2022-general-primary-2022-07-19.csv
│   ├── 2026-general-primary-2026-04-07.csv
│   └── 2026-general-primary-detail.xlsx   # Precinct-level detail (optional)
├── src/
│   └── election_analysis_generator/       # Package — all logic lives here
│       ├── models.py               # Dataclasses: Election, Contest, Candidate
│       ├── db.py                   # ElectionDatabase: all SQLite operations
│       ├── loader.py               # ElectionLoader: reads config + source files into DB
│       ├── analysis.py             # ElectionAnalyzer: analysis methods → DataFrames
│       ├── normalize.py            # Pure functions: contest name + party normalization
│       ├── flags.py                # export_flags(), import_flags(), review_flags()
│       └── cli.py                  # Entry points wired to [project.scripts]
└── tests/
    ├── conftest.py             # Fixtures and helpers: db, sample_election, seed_election()
    ├── test_db.py
    ├── test_loader.py
    ├── test_analysis.py
    └── test_normalize.py
```

> `elections.db` is generated locally and is not committed to the repository.

---

## Getting started

### Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) for dependency management

### Install

```bash
uv sync
```

### First-time setup

Add your election CSVs to `sources/` and define them in `elections.toml`, then run:

```bash
uv run sync-sources
```

This loads all elections defined in `elections.toml` that haven't been loaded yet and creates `elections.db`.

---

## Adding new elections

1. Place the raw CSV in the `sources/` directory.
2. Add an entry to `elections.toml` (see [Election config](#election-config) below).
3. Run:

```bash
uv run sync-sources
```

`sync-sources` checks `elections.toml` for any elections whose `source_file` hasn't been loaded yet and loads them. Already-loaded elections are skipped. **Database entries are never removed** even if a source file is later deleted.

If any contest names in the new file don't match the registry, they are flagged for review. See [Reviewing flagged contest names](#reviewing-flagged-contest-names) below.

---

## Election config

All elections are defined in `elections.toml`. Each entry uses a `[elections.<key>]` section:

```toml
[elections.2026-general-primary]
name              = "2026 General Primary"
year              = 2026
election_date     = "2026-04-07"
category          = "General Primary"
election_type     = "midterm"
source_file       = "2026-general-primary-2026-04-07.csv"
detail_file       = "2026-general-primary-detail.xlsx"   # optional
registered_voters = 636822
ballots_cast      = 161738
```

| Field | Required | Description |
|---|---|---|
| `name` | Yes | Display name used throughout the codebase |
| `source_file` | Yes | CSV filename in `sources/` (basename only, no path prefix) |
| `detail_file` | No | Excel filename in `sources/` containing precinct-level results |
| `year` | No | Inferred from filename if omitted |
| `election_date` | No | ISO 8601 date (`YYYY-MM-DD`) |
| `category` | No | One of: `Consolidated`, `Consolidated Primary`, `General`, `General Primary` |
| `election_type` | No | One of: `presidential`, `midterm` |
| `registered_voters` | No | County-wide registered voter count |
| `ballots_cast` | No | County-wide ballots cast; if absent, derived as the max across all contest rows in the CSV |

---

## Generating analysis output

```bash
uv run generate-analysis
```

This writes `election_analysis.xlsx` with sheets for turnout, party vote-share, and percent change across elections. All comparisons are filtered to **comparable contests** — contests where both DEM and REP had votes in every election being compared.

---

## Contest name normalization

Raw contest names vary across years. The following transformations are applied automatically on load:

| Rule | Example input | Normalized output |
|---|---|---|
| Uppercase | `United States Senator` | `UNITED STATES SENATOR` |
| Strip party suffixes | `FOR SENATOR - D*` | `FOR SENATOR` |
| Strip parentheticals | `FOR SENATOR (Vote For 1)` | `FOR SENATOR` |
| Strip term-length suffixes | `District 1, 4 Year Term - R` | `DISTRICT 1` |
| Gender-neutral titles | `FOR PRECINCT COMMITTEEWOMAN YORK 050` | `FOR PRECINCT COMMITTEEPERSON YORK 050` |
| Spell out ordinals | `81ST REPRESENTATIVE DISTRICT` | `EIGHTY-FIRST REPRESENTATIVE DISTRICT` |

Plain integers (e.g. `District 1`) are preserved. Original raw contest names are always stored alongside normalized names for reference.

---

## Candidate name corrections

Known misspellings in candidate names are corrected on load via `CANDIDATE_NAME_CORRECTIONS` in `normalize.py`. Each entry is a 2-tuple:

```python
(wrong_name, correct_name)
```

Matching is case-insensitive exact string matching. The corrected value is returned exactly as written in the tuple.

Current corrections:

| Wrong name | Correct name |
|---|---|
| `JB PRITZER` | `JB PRITZKER` |

To add a new correction, add an entry to `CANDIDATE_NAME_CORRECTIONS` in `normalize.py`. Keys must be casefolded (lowercase):

```python
CANDIDATE_NAME_CORRECTIONS: dict[str, str] = {
    "jb pritzer": "JB PRITZKER",
    "wrong name": "CORRECT NAME",  # new
}
```

---

## Reviewing flagged contest names

After loading a new election, any normalized contest name that doesn't match the registry is flagged. There are two ways to resolve flags.

### Option A — Spreadsheet review (recommended for large batches)

```bash
uv run export-flags        # writes flags_review.xlsx
# ... edit the spreadsheet ...
uv run import-flags        # applies your decisions to the DB
```

`flags_review.xlsx` has two tabs:

- **`flags`** — one row per unresolved flag with columns: Flag ID, Year, Raw Name, Normalized Suggestion, Status, Override Target, Notes
- **`known_contests`** — all normalized contest names currently in the registry

Set the **Status** column for each flag row:

| Status | Meaning |
|---|---|
| `unreviewed` | Default — skipped on import |
| `accepted` | Accept the Normalized Suggestion as a new contest name |
| `mapped` | Map to an existing contest — fill in **Override Target** with a name from `known_contests` |
| `ignored` | Acknowledge without registering (e.g. ballot measures you don't want to track) |

You can import partially and re-export to continue — `unreviewed` rows are always skipped.

### Option B — Interactive terminal review

```bash
uv run review-flags
```

For each flag you can accept it as a new contest, map it to an existing one, or skip for later.

### How overrides work

When a flag is marked `mapped`, an entry is added to `contest_name_overrides` linking the raw name to its canonical normalized name. On all future loads that raw name is mapped directly, bypassing normalization — so a renamed contest can be mapped once and handled correctly forever after.

---

## Architecture

**`models.py`** defines the core dataclasses: `Election`, `Contest`, `Candidate`.

**`db.py` — `ElectionDatabase`** owns all database state: the SQLite connection, schema, contest name registry, flags, overrides, and source file registry. All other classes go through this interface.

**`loader.py` — `ElectionLoader`** reads `elections.toml` and source files, then loads them into an `ElectionDatabase`. `sync()` loads only elections not already registered. Handles both CSV sources and the historical Excel workbook.

**`analysis.py` — `ElectionAnalyzer`** reads from an `ElectionDatabase` and produces analysis DataFrames. Elections can be specified by name, database id, or `Election` object. Methods: `list_elections()`, `pct_change_by_party()`, `party_share()`, `turnout()`.

**`normalize.py`** contains pure functions for contest name, party, and candidate name normalization — no state, no I/O, fully unit-tested independently.

**`flags.py`** contains `export_flags()`, `import_flags()`, and `review_flags()` — all flag-management logic in one place.

**`cli.py`** contains the entry points registered in `[project.scripts]`: `sync-sources`, `generate-analysis`, `export-flags`, `import-flags`, `review-flags`.

---

## Database schema

**`elections`** — one row per election event

| Column | Description |
|---|---|
| `id` | Primary key |
| `name` | Display name (e.g. `"2026 General Primary"`) |
| `year` | Election year |
| `election_date` | Date of the election |
| `results_last_updated` | Date results were last updated |
| `source_file` | Unique key for the source this election was loaded from |
| `category` | Election category (`General Primary`, etc.) |
| `election_type` | `presidential` or `midterm` |
| `registered_voters` | County-wide registered voter count |
| `ballots_cast` | County-wide ballots cast |

**`contests`** — one row per unique normalized contest name

| Column | Description |
|---|---|
| `contest_name` | Normalized name (primary key) |
| `is_legislation` | `1` if this is a ballot measure, `0` if partisan |

**`candidates`** — one row per candidate per contest per election

| Column | Description |
|---|---|
| `contest_id` | FK → `contests` |
| `election_id` | FK → `elections` |
| `contest_name_raw` | Original contest name from the source file |
| `choice_name` | Candidate name |
| `party` | Normalized party code (`DEM`, `REP`, `GP`, `WC`, etc.) |
| `total_votes` | Votes received |
| `percent_of_votes` | Candidate's share within their party primary |

**`contest_names`** — registry of known normalized contest names

**`contest_name_flags`** — names from new sources that didn't match any known name

**`contest_name_overrides`** — manual mappings: raw name → canonical normalized name

**`loaded_sources`** — registry of source keys that have been loaded (prevents re-loading)

**`candidate_precinct_results`** — precinct-level vote breakdown from detail Excel files

| Column | Description |
|---|---|
| `id` | Primary key |
| `election_id` | FK → `elections` |
| `contest_id` | FK → `contests` |
| `contest_name_raw` | Original contest name from the detail file |
| `choice_name` | Candidate name |
| `precinct` | Precinct name (e.g. `"Addison 001"`) |
| `registered_voters` | Registered voters in this precinct for this contest |
| `early_votes` | Early votes received |
| `vote_by_mail` | Vote-by-mail votes received |
| `polling` | Election day polling votes received |
| `provisional` | Provisional votes received |
| `total_votes` | Total votes received (sum of all vote methods) |

Unique on `(election_id, contest_id, choice_name, precinct)` — re-loading the same detail file is safe. Precinct totals summed by candidate should equal the corresponding `total_votes` in `candidates`, which provides a built-in cross-check against the summary CSV.

---

## Running tests

```bash
uv run pytest
```

---

## Data notes

- Results cover DuPage County primary elections only
- Only DEM and REP contests are used in partisan comparisons; other parties are stored but excluded from analysis
- 2026 results are official as of April 7, 2026
- `category` and `election_type` are defined in `elections.toml` and stored on the `elections` table; valid values are enforced at load time
