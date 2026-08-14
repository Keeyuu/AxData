# axdata-integration-qlib

AxData → Qlib materialized provider exporter (AXI-060).

Reads catalogued AxData datasets (bars / calendar / instruments / adj-factor)
through `axdata_core.query_dataset` and writes a Qlib 0.9.7 readable
provider directory:

```text
qlib/
├── calendars/day.txt
├── instruments/all.txt
└── features/<normalized_instrument>/<field>.day.bin
```

plus `instrument_map.json` (reversible `000001.SZ <-> SZ000001` mapping) and
`qlib_export.json` (price basis, adjustment, fields, provenance, content
hash). Design contract: `docs/plan/axdata-integration/06-qlib-bridge.md` in
the parent Skynet repository.

## Usage

```python
from axdata_qlib import QlibExportSpec, export_qlib_provider

spec = QlibExportSpec(
    instruments_dataset="market.instruments",
    calendar_dataset="market.calendar",
    bars_dataset="market.bars",
    adj_factor_dataset="market.adj_factor",
    start_date="2026-01-05",
    end_date="2026-01-09",
)
result = export_qlib_provider(spec, data_root=".../axdata_data", output_dir=".../qlib")
print(result.provider_uri, result.content_hash)
```

Key semantics:

- the exported calendar always extends at least one trading day past
  `end_date` (taken from the calendar dataset; the export fails if none
  exists) — Qlib's backtest reads `calendar[end + 1]` (ADR-0001);
- V1 records adjustment metadata only and never recomputes prices:
  `price_basis=adjusted/adjustment=backward` when the adj-factor dataset has
  rows, otherwise `raw/none`;
- an existing non-empty `output_dir` is refused: qlib directories are
  rebuild-only artifacts, never incrementally modified;
- the content hash is a stable SHA-256 over every exported file except
  `qlib_export.json` itself (which embeds the hash and a generation
  timestamp), so identical inputs produce identical hashes.

`pyqlib==0.9.7` is a test-only dependency; installing this package never
forces Qlib.

## Tests

```bash
.venv/Scripts/python.exe -m pytest tests -q            # non-framework
.venv/Scripts/python.exe -m pytest tests -m framework -q  # qlib-backed
```
