"""Minimal AxData tool entry point (placeholder, AXI-060).

Declares the package's tool to AxData tool registries via the
``axdata.tools`` entry point group. V1 only carries identity metadata —
exporting is driven by :func:`axdata_qlib.export_qlib_provider`; no
collector / scheduler logic lives here (that belongs to AXI-080).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from importlib import metadata


@dataclass(frozen=True, slots=True)
class QlibExportTool:
    """Identity of the qlib-export tool as seen by an AxData registry."""

    tool_id: str
    name: str
    description: str
    version: str
    entrypoint_group: str


TOOL_ENTRY_POINT_GROUP = "axdata.tools"


qlib_export_tool = QlibExportTool(
    tool_id="axdata.tools.qlib_export",
    name="axdata-qlib-export",
    description=(
        "Materialize AxData catalog datasets into a Qlib 0.9.7 provider "
        "directory (AXI-060). V1 exposes identity only; invocation goes "
        "through axdata_qlib.export_qlib_provider."
    ),
    version="0.1.0",
    entrypoint_group=TOOL_ENTRY_POINT_GROUP,
)


def discover_tools() -> Sequence[QlibExportTool]:
    """Load every tool registered under the ``axdata.tools`` entry point group.

    A tool object is accepted when it exposes ``tool_id``; missing or broken
    entry points are skipped rather than failing discovery.
    """
    discovered: list[QlibExportTool] = []
    for entry in metadata.entry_points().select(group=TOOL_ENTRY_POINT_GROUP):
        try:
            tool = entry.load()
        except Exception:
            continue
        tool_id = getattr(tool, "tool_id", None)
        if tool_id:
            discovered.append(tool)
    return discovered
