"""AxData → Qlib materialized provider exporter (AXI-060).

Exports AxData catalog datasets (bars / calendar / instruments / adj-factor)
into a Qlib 0.9.7 readable provider directory:

    qlib/
    ├── calendars/day.txt
    ├── instruments/all.txt
    └── features/<normalized_instrument>/<field>.day.bin

plus ``instrument_map.json`` (reversible instrument mapping) and
``qlib_export.json`` (price basis, adjustment, fields, provenance).

Public API: :class:`QlibExportSpec`, :func:`export_qlib_provider`,
:class:`QlibExportResult`, :class:`QlibExportError`.
"""

from .exporter import QlibExportError, QlibExportResult, QlibExportSpec, export_qlib_provider

__all__ = [
    "QlibExportError",
    "QlibExportResult",
    "QlibExportSpec",
    "export_qlib_provider",
]
