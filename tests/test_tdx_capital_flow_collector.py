"""stock_capital_flow_tdx collector wiring (MAC 0x1218) — no live hosts."""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from axdata_core.source_errors import SourceUnavailableError
from axdata_source_tdx import request_methods
from axdata_source_tdx._tdx_wire.models.mac_capital_flow import CapitalFlowSnapshot
from axdata_source_tdx.host_config import DEFAULT_TDX_MAC_HOSTS, configured_tdx_mac_hosts
from axdata_source_tdx.request_adapter import TdxRequestAdapter

from tests.test_tdx_source_request_adapter import FakeTdxClient

REPO_ROOT = Path(__file__).resolve().parents[1]
PROVIDER_JSON = (
    REPO_ROOT
    / "packages"
    / "axdata-source-tdx"
    / "src"
    / "axdata_source_tdx"
    / "axdata-provider.json"
)


def _snapshot(full_code: str, market: int) -> CapitalFlowSnapshot:
    return CapitalFlowSnapshot(
        full_code=full_code,
        market=market,
        query_info="Stock_ZJLX",
        ext="",
        today_main_in=320706176.0,
        today_main_out=373999296.0,
        today_retail_in=608355072.0,
        today_retail_out=555062016.0,
        today_main_net=-53293120.0,
        today_retail_net=53293056.0,
        five_day_main_buy=1986570752.0,
        five_day_main_sell=2257087744.0,
        five_day_super_net=31367040.0,
        five_day_large_net=-91887392.0,
        five_day_medium_net=97695472.0,
        five_day_small_net=-37175104.0,
        five_day_main_net=-270516992.0,
    )


class FakeMacClient:
    """Stands in for the MAC-host TdxClient; records codes requested via .mac."""

    def __init__(self, snapshots_by_code, fail_codes=()):
        self.snapshots_by_code = dict(snapshots_by_code)
        self.fail_codes = set(fail_codes)
        self.requested_codes: list[str] = []
        self.connected = False
        self.closed = False
        self.mac = SimpleNamespace(capital_flow=self._capital_flow)

    def connect(self) -> None:
        self.connected = True

    def close(self) -> None:
        self.closed = True

    def _capital_flow(self, code: str):
        self.requested_codes.append(code)
        if code in self.fail_codes:
            raise RuntimeError(f"mac unavailable for {code}")
        if code in self.snapshots_by_code:
            return self.snapshots_by_code[code]
        market = 1 if code.startswith("sh") else 0
        return _snapshot(code, market)


def _install_mac_client(monkeypatch, mac_client: FakeMacClient) -> list[dict]:
    created: list[dict] = []

    def fake_create_tdx_client(**kwargs):
        created.append(kwargs)
        return mac_client

    monkeypatch.setattr(request_methods, "create_tdx_client", fake_create_tdx_client)
    return created


def _adapter(quote_client=None, options=None) -> TdxRequestAdapter:
    return TdxRequestAdapter(
        client=quote_client or FakeTdxClient(include_extra_stocks=True), options=options
    )


def test_capital_flow_rows_map_snapshot_fields_verbatim(monkeypatch):
    mac_client = FakeMacClient(
        {
            "sz000001": _snapshot("sz000001", 0),
            "sh600717": _snapshot("sh600717", 1),
        }
    )
    created = _install_mac_client(monkeypatch, mac_client)
    quote_client = FakeTdxClient(include_extra_stocks=True)
    adapter = TdxRequestAdapter(client=quote_client)

    rows = adapter.request("stock_capital_flow_tdx", {"scope": "all", "trade_date": "2026-08-16"})

    # Stock universe came from the suspension-style code scan on the quote client.
    assert quote_client.calls
    assert "sz000001" in mac_client.requested_codes
    assert "sh600717" in mac_client.requested_codes
    assert "sh000001" not in mac_client.requested_codes  # index
    assert "sh510050" not in mac_client.requested_codes  # etf
    assert mac_client.connected and mac_client.closed

    by_instrument = {row["instrument_id"]: row for row in rows}
    assert by_instrument["000001.SZ"] == {
        "instrument_id": "000001.SZ",
        "trade_date": "20260816",
        "full_code": "sz000001",
        "market": 0,
        "today_main_in": 320706176.0,
        "today_main_out": 373999296.0,
        "today_retail_in": 608355072.0,
        "today_retail_out": 555062016.0,
        "today_main_net": -53293120.0,
        "today_retail_net": 53293056.0,
        "five_day_main_buy": 1986570752.0,
        "five_day_main_sell": 2257087744.0,
        "five_day_super_net": 31367040.0,
        "five_day_large_net": -91887392.0,
        "five_day_medium_net": 97695472.0,
        "five_day_small_net": -37175104.0,
        "five_day_main_net": -270516992.0,
    }
    assert by_instrument["600717.SH"]["full_code"] == "sh600717"
    assert by_instrument["600717.SH"]["market"] == 1
    for row in rows:
        assert set(row) == {"instrument_id", "trade_date", *request_methods.CAPITAL_FLOW_ROW_FIELDS}
        assert re.fullmatch(r"\d{6}\.(SZ|SH|BJ)", row["instrument_id"])

    meta = adapter.last_meta
    assert meta["tdx_capital_flow_source"] == "tdx_0x1218"
    assert meta["tdx_capital_flow_count"] == len(rows)
    assert meta["tdx_capital_flow_failed_count"] == 0
    assert meta["tdx_scanned_count"] == len(mac_client.requested_codes)
    assert meta["trade_date"] == "20260816"
    assert created == [{"hosts": list(DEFAULT_TDX_MAC_HOSTS), "pool_size": 1}]


def test_capital_flow_code_param_limits_mac_requests(monkeypatch):
    mac_client = FakeMacClient({"sz000001": _snapshot("sz000001", 0)})
    _install_mac_client(monkeypatch, mac_client)
    adapter = _adapter()

    rows = adapter.request(
        "stock_capital_flow_tdx", {"code": ["000001.SZ"], "trade_date": "20260816"}
    )

    assert mac_client.requested_codes == ["sz000001"]
    assert [row["instrument_id"] for row in rows] == ["000001.SZ"]


def test_capital_flow_defaults_trade_date_to_today(monkeypatch):
    mac_client = FakeMacClient({"sz000001": _snapshot("sz000001", 0)})
    _install_mac_client(monkeypatch, mac_client)
    adapter = _adapter()

    rows = adapter.request("stock_capital_flow_tdx", {"code": ["000001.SZ"]})

    assert re.fullmatch(r"\d{8}", rows[0]["trade_date"])
    assert adapter.last_meta["trade_date"] == rows[0]["trade_date"]


def test_capital_flow_tolerates_per_code_failure_but_not_total_failure(monkeypatch):
    snapshots = {
        "sz000001": _snapshot("sz000001", 0),
        "sz000004": _snapshot("sz000004", 0),
    }
    mac_client = FakeMacClient(snapshots, fail_codes=["sz000004"])
    _install_mac_client(monkeypatch, mac_client)
    adapter = _adapter()

    rows = adapter.request("stock_capital_flow_tdx", {"code": ["000001.SZ", "000004.SZ"]})

    assert [row["instrument_id"] for row in rows] == ["000001.SZ"]
    assert adapter.last_meta["tdx_capital_flow_failed_count"] == 1

    dead_client = FakeMacClient(snapshots, fail_codes=["sz000001", "sz000004"])
    _install_mac_client(monkeypatch, dead_client)
    with pytest.raises(SourceUnavailableError, match="failed for all"):
        adapter.request("stock_capital_flow_tdx", {"code": ["000001.SZ", "000004.SZ"]})


def test_capital_flow_uses_mac_host_group_with_env_override(monkeypatch):
    mac_client = FakeMacClient({"sz000001": _snapshot("sz000001", 0)})
    created = _install_mac_client(monkeypatch, mac_client)
    monkeypatch.setenv("AXDATA_TDX_MAC_HOSTS", "1.2.3.4:7709, 5.6.7.8:7709")

    _adapter().request("stock_capital_flow_tdx", {"code": ["000001.SZ"]})

    assert created[0]["hosts"] == ["1.2.3.4:7709", "5.6.7.8:7709"]
    assert configured_tdx_mac_hosts() == ["1.2.3.4:7709", "5.6.7.8:7709"]


def test_capital_flow_execution_options_slice_hosts_and_pool(monkeypatch):
    mac_client = FakeMacClient({"sz000001": _snapshot("sz000001", 0)})
    created = _install_mac_client(monkeypatch, mac_client)
    adapter = _adapter(options={"source_server_count": 1, "connections_per_server": 2})

    adapter.request("stock_capital_flow_tdx", {"code": ["000001.SZ"]})

    assert created == [{"hosts": [DEFAULT_TDX_MAC_HOSTS[0]], "pool_size": 2}]


def test_capital_flow_trade_date_param_normalization():
    assert request_methods.capital_flow_trade_date({"trade_date": "2026-08-16"}) == "20260816"
    assert request_methods.capital_flow_trade_date({"trade_date": "20260816"}) == "20260816"
    assert request_methods.capital_flow_trade_date({"data_date": "20260816"}) == "20260816"
    assert re.fullmatch(r"\d{8}", request_methods.capital_flow_trade_date({}))


def test_capital_flow_collector_registration_tables():
    from axdata_source_tdx.collectors import (
        _TDX_CATEGORIES,
        _TDX_DATASET_IDS,
        _TDX_DESCRIPTIONS,
        _TDX_EXECUTION_OPTIONS,
        _TDX_LOGICAL_TABLES,
        _TDX_OUTPUT_PATH_PARTS,
        TDX_COLLECTOR_INTERFACES,
        tdx_collector_specs,
    )

    name = "stock_capital_flow_tdx"
    assert name in TDX_COLLECTOR_INTERFACES
    assert _TDX_DATASET_IDS[name] == "tdx.stock_capital_flow"
    assert _TDX_CATEGORIES[name] == "capital_flow"
    assert "0x1218" in _TDX_DESCRIPTIONS[name]
    assert _TDX_EXECUTION_OPTIONS[name] == {"source_server_count": 1, "connections_per_server": 2}
    assert _TDX_OUTPUT_PATH_PARTS[name] == ["core", "table=capital_flow"]
    assert _TDX_LOGICAL_TABLES[name] == "capital_flow"

    specs = {spec.name: spec for spec in tdx_collector_specs()}
    spec = specs["tdx.stock_capital_flow_tdx.snapshot"]
    assert spec.dataset_id == "tdx.stock_capital_flow"
    assert spec.category == "capital_flow"
    assert spec.resource_group == "tdx.quote"
    assert spec.output["layer"] == "core"
    assert spec.output["write_mode"] == "snapshot"
    assert spec.output["partition_by"] == ["trade_date"]
    assert spec.output["primary_key"] == ["instrument_id", "trade_date"]
    assert spec.output["date_field"] == "trade_date"
    assert spec.output["default_output_path_parts"] == ["core", "table=capital_flow"]
    dataset = spec.output["datasets"][0]
    assert dataset["table"] == "capital_flow"
    assert dataset["write_mode"] == "snapshot"
    assert spec.config_schema["execution"]["defaults"] == {
        "source_server_count": 1,
        "connections_per_server": 2,
        "max_concurrent_tasks": 2,
    }


def test_capital_flow_dispatch_and_downloader_profile_registration():
    from axdata_core.downloaders import ConcurrencyProfile, DownloaderProfile
    from axdata_source_tdx.downloader_profiles import tdx_downloader_profiles
    from axdata_source_tdx.interface_sets import SUPPORTED_INTERFACES
    from axdata_source_tdx.request_dispatch import TDX_EXACT_REQUEST_METHODS

    assert TDX_EXACT_REQUEST_METHODS["stock_capital_flow_tdx"] == "_request_stock_capital_flow"
    assert "stock_capital_flow_tdx" in SUPPORTED_INTERFACES
    assert TdxRequestAdapter().supports("stock_capital_flow_tdx")

    profiles = tdx_downloader_profiles(ConcurrencyProfile, DownloaderProfile)
    profile = profiles["stock_capital_flow_tdx"]
    assert profile.output_layer == "core"
    assert profile.write_mode == "snapshot"
    assert list(profile.partition_by) == ["trade_date"]
    assert tuple(profile.primary_key) == ("instrument_id", "trade_date")
    assert profile.date_field == "trade_date"
    assert profile.file_stem_template == "{interface_name}_{snapshot_date}"
    assert profile.default_output_path_parts == ["core", "table=capital_flow"]
    assert profile.default_fields == [
        "instrument_id",
        "trade_date",
        *request_methods.CAPITAL_FLOW_ROW_FIELDS,
    ]
    assert len(request_methods.CAPITAL_FLOW_ROW_FIELDS) == 15


def test_capital_flow_provider_json_entries_parse():
    payload = json.loads(PROVIDER_JSON.read_text(encoding="utf-8"))

    interfaces = {entry["name"]: entry for entry in payload["interfaces"]}
    entry = interfaces["stock_capital_flow_tdx"]
    assert entry["collection"] == {
        "supported": True,
        "default_profile": "stock_capital_flow_tdx.snapshot",
    }
    assert entry["request_mode"] == "source_request"
    field_names = [field["name"] for field in entry["fields"]]
    assert field_names == ["instrument_id", "trade_date", *request_methods.CAPITAL_FLOW_ROW_FIELDS]

    downloaders = {item["name"]: item for item in payload["downloaders"]}
    downloader = downloaders["stock_capital_flow_tdx.snapshot"]
    assert downloader["interface_name"] == "stock_capital_flow_tdx"
    assert downloader["mode"] == "snapshot"
    assert downloader["default_options"]["source_server_count"] == 1
    assert downloader["default_options"]["connections_per_server"] == 2
    assert downloader["default_options"]["fields"] == field_names
    output = downloader["output"]
    assert output["output_layer"] == "core"
    assert output["write_mode"] == "snapshot"
    assert output["partition_by"] == ["trade_date"]
    assert output["primary_key"] == ["instrument_id", "trade_date"]
    assert output["date_field"] == "trade_date"
    assert payload["collectors"] == []
