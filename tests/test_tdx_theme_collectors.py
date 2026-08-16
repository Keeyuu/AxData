"""ICFQS 题材族采集器测试：题材成分（PIT）与题材事件日历。

全部 mock IcfqsClient，不连真机：
- topic_list 用 tests/fixtures/icfqs/topic_list_20260816.json 的真实形态；
- topic_stocks / events 用手造响应 dict（列序按 2026-08-16 真机实测口径）。
覆盖翻页完整性、setcode 推断、instrument_id 转换、as_of_date 覆盖、
列位置无关防御、以及注册表（collectors / dispatch / provider.json）断言。
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from axdata_source_tdx import icfqs_theme_fetch
from axdata_source_tdx.icfqs_theme_fetch import (
    ThemeColumnError,
    stock_theme_events_request_result,
    stock_theme_members_request_result,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "icfqs" / "topic_list_20260816.json"
TODAY = date(2026, 8, 16)


def _table(columns: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    return {"ErrorCode": 0, "ResultSets": [{"ColName": columns, "Content": rows}]}


class FakeIcfqsClient:
    """按入口路由的手造 ICFQS 客户端；记录全部调用供断言。"""

    default_url = "http://119.3.157.89:7615"

    def __init__(
        self,
        *,
        topic_list_pages: list[list[list[Any]]] | None = None,
        stocks_pages: dict[tuple[str, str], list[list[list[Any]]]] | None = None,
        events_payload: dict[str, Any] | None = None,
    ) -> None:
        self.topic_list_pages = topic_list_pages or []
        self.stocks_pages = stocks_pages or {}
        self.events_payload = events_payload
        self.calls: list[tuple[str, list[Any]]] = []

    def request_icfqs(self, entry: str, params: list[Any]) -> dict[str, Any]:
        self.calls.append((entry, list(params)))
        if entry == "topic_list":
            page = int(params[2])
            rows = self.topic_list_pages[page - 1] if page <= len(self.topic_list_pages) else []
            return _table(["N001", "N002", "N003", "N004", "N005", "N006"], rows)
        if entry == "topic_stocks":
            key = (str(params[1]), str(params[2]))
            page = int(params[6])
            pages = self.stocks_pages.get(key) or []
            rows = pages[page - 1] if page <= len(pages) else []
            columns = [f"N{index:03d}" for index in range(1, 10)]
            return _table(columns, rows)
        if entry == "events":
            assert self.events_payload is not None
            return self.events_payload
        raise AssertionError(f"unexpected entry {entry}")

    def entry_calls(self, entry: str) -> list[list[Any]]:
        return [params for name, params in self.calls if name == entry]


def _member_row(
    seq: Any,
    theme_code: str,
    inner_id: str,
    stock: str,
    name: str,
    reason: str,
    join_date: str,
) -> list[Any]:
    return [seq, theme_code, inner_id, stock, name, "0", "0", reason, join_date]


def _client_with_three_themes(*, big_theme_pages: bool = False) -> FakeIcfqsClient:
    """三题材场景：N005 带 setcode JSON、纯数字缺省、880 缺省。"""

    with FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        fixture_rows = json.load(handle)["ResultSets"][0]["Content"]
    row_json_setcode = list(fixture_rows[0])  # 880915，N005 JSON setcode="1"
    row_plain_digits = ["1", "1317", "世界杯概念", "综合", None, "2026-07-23 09:52:38"]
    row_880 = ["1", "880666", "次新股", "综合", None, "2026-08-01 10:00:00"]

    stocks_pages: dict[tuple[str, str], list[list[list[Any]]]] = {}
    stocks_pages[("880915", "2")] = [
        [
            _member_row(
                1, "880915", "1001", "1_688598", "华兴源创", "半导体检测设备放量", "2026-08-15"
            ),
            _member_row(2, "880915", "1002", "0_300243", "初灵信息", "昨日20cm涨停", "2026-08-14"),
        ],
        [],
    ]
    if big_theme_pages:
        page1 = [
            _member_row(
                index,
                "1317",
                str(2000 + index),
                "600519",
                f"股票{index:03d}",
                "白酒示范",
                "2026-08-01",
            )
            for index in range(1, 101)
        ]
        page2 = [
            _member_row(1, "1317", "2101", "920099", "天龙集团", "北交所题材", "2026-08-02"),
            _member_row(2, "1317", "2102", "430047", "诺思兰德", "北交所题材", "2026-08-03"),
        ]
        stocks_pages[("1317", "1")] = [page1, page2, []]
    else:
        stocks_pages[("1317", "1")] = [
            [_member_row(1, "1317", "2001", "600519", "贵州茅台", "白酒示范", "2026-08-01")],
            [],
        ]
    stocks_pages[("880666", "2")] = [
        [_member_row(1, "880666", "3001", "2_430047", "诺思兰德", "北交所题材", "2026-08-10")],
        [],
    ]
    return FakeIcfqsClient(
        topic_list_pages=[[row_json_setcode, row_plain_digits, row_880], []],
        stocks_pages=stocks_pages,
    )


def test_theme_members_paginate_until_empty_page() -> None:
    client = _client_with_three_themes(big_theme_pages=True)
    result = stock_theme_members_request_result({}, client=client, today=TODAY)

    # topic_list 翻到第 2 页（空页）即止，没有第 3 页请求。
    assert client.entry_calls("topic_list") == [["00601", "|", 1], ["00601", "|", 2]]
    # 1317 成分 100+2 行跨 3 页（第 3 页为空）；其余题材各 1 页 + 空页。
    stocks_calls = client.entry_calls("topic_stocks")
    assert ["00901", "1317", "1", 1, 100, 0, 3] in stocks_calls
    assert not any(params[6] == 4 for params in stocks_calls)
    assert len(result.rows) == 2 + 102 + 1
    assert result.meta["tdx_theme_count"] == 3
    assert result.meta["tdx_theme_list_pages"] == 1
    assert result.meta["tdx_theme_member_count"] == len(result.rows)
    assert result.meta["tdx_icfqs_host"] == "http://119.3.157.89:7615"


def test_theme_members_setcode_inference() -> None:
    client = _client_with_three_themes()
    result = stock_theme_members_request_result({}, client=client, today=TODAY)

    setcodes = {(row["theme_code"], row["setcode"]) for row in result.rows}
    # N005 JSON 的 setcode="1" 优先；纯数字缺省 "1"；880 缺省 "2"。
    assert setcodes == {("880915", "2"), ("1317", "1"), ("880666", "2")}
    # topic_stocks 按推断后的 (code, setcode) 请求。
    assert ["00901", "880666", "2", 1, 100, 0, 1] in client.entry_calls("topic_stocks")


def test_theme_members_instrument_conversion() -> None:
    client = _client_with_three_themes(big_theme_pages=True)
    result = stock_theme_members_request_result({}, client=client, today=TODAY)
    by_symbol = {row["symbol"]: row for row in result.rows}

    # "0_300243"→SZ、"1_688598"→SH、"2_430047"→BJ（网关市场位权威）。
    assert by_symbol["300243"]["instrument_id"] == "300243.SZ"
    assert by_symbol["300243"]["exchange"] == "SZSE"
    assert by_symbol["688598"]["instrument_id"] == "688598.SH"
    assert by_symbol["430047"]["instrument_id"] == "430047.BJ"
    # 裸 6 位代码按前缀推断：6→SH，92/43→BJ。
    assert by_symbol["600519"]["instrument_id"] == "600519.SH"
    assert by_symbol["920099"]["instrument_id"] == "920099.BJ"
    # 文本与日期字段。
    first = by_symbol["688598"]
    assert first["instrument_name"] == "华兴源创"
    assert first["join_reason"] == "半导体检测设备放量"
    assert first["join_date"] == "20260815"


def test_theme_members_as_of_date_default_and_override() -> None:
    client = _client_with_three_themes()
    default = stock_theme_members_request_result({}, client=client, today=TODAY)
    assert {row["as_of_date"] for row in default.rows} == {"20260816"}
    assert default.meta["as_of_date"] == "20260816"
    assert default.meta["data_date"] == "20260816"

    overridden = stock_theme_members_request_result(
        {"as_of_date": "2026-08-01"}, client=client, today=TODAY
    )
    assert {row["as_of_date"] for row in overridden.rows} == {"20260801"}

    with pytest.raises(ValueError, match="as_of_date"):
        stock_theme_members_request_result({"as_of_date": "2026/8/1"}, client=client, today=TODAY)


def test_theme_members_column_shift_still_parses() -> None:
    # 列整体漂移（N010..）：值特征扫描兜底仍应解析成功。
    shifted = {
        "N010": "1",
        "N011": "1317",
        "N012": "777",
        "N013": "600519",
        "N014": "贵州茅台",
        "N015": "白酒龙头",
        "N016": "2026-08-01",
    }
    row = icfqs_theme_fetch._theme_member_row(
        shifted, theme_code="1317", setcode="1", as_of_date="20260816"
    )
    assert row["instrument_id"] == "600519.SH"
    assert row["instrument_name"] == "贵州茅台"
    # join_reason 是位置列（N008）：列漂移时按防御规则置 None，不扫描错列。
    assert row["join_reason"] is None
    assert row["join_date"] == "20260801"
    assert row["as_of_date"] == "20260816"


def test_theme_members_garbage_row_raises_with_preview() -> None:
    garbage = {"N001": "x", "N002": "y"}
    with pytest.raises(ThemeColumnError, match="无法定位股票代码"):
        icfqs_theme_fetch._theme_member_row(
            garbage, theme_code="1317", setcode="1", as_of_date="20260816"
        )
    with pytest.raises(ThemeColumnError) as excinfo:
        icfqs_theme_fetch._member_instrument(
            {"N001": "1", "N002": "2"}, theme_code="1317", setcode="1"
        )
    assert "N001" in str(excinfo.value)  # 行预览必须带出


def _events_client() -> FakeIcfqsClient:
    payload = _table(
        ["N001", "N002", "N003", "N004", "N005", "N006", "N007", "N008"],
        [
            [
                "1",
                "2026-08-16",
                "1317",
                "世界杯概念",
                "2026-06-15",
                "2026美加墨世界杯开幕",
                "0_300243,1_688598",
                "3.45",
            ],
            [
                "2",
                "2026-08-16",
                "880915",
                "昨日突涨",
                "2026-08-15",
                "前日突涨成分回顾",
                "0_300243",
                "-2.1%",
            ],
        ],
    )
    return FakeIcfqsClient(events_payload=payload)


def test_theme_events_rows_and_defaults() -> None:
    client = _events_client()
    result = stock_theme_events_request_result({}, client=client, today=TODAY)

    assert client.entry_calls("events") == [["00401", "", 100]]
    assert len(result.rows) == 2
    first, second = result.rows
    assert first == {
        "theme_code": "1317",
        "theme_name": "世界杯概念",
        "event_date": "20260615",
        "event_text": "2026美加墨世界杯开幕",
        "member_codes": "0_300243,1_688598",
        "change_pct": 3.45,
        "as_of_date": "20260816",
    }
    # member_codes 原样保留；百分比串转 float；负值不丢。
    assert second["member_codes"] == "0_300243"
    assert second["change_pct"] == -2.1
    assert {row["as_of_date"] for row in result.rows} == {"20260816"}
    assert result.meta["tdx_theme_event_count"] == 2
    assert result.meta["tdx_theme_event_limit"] == 100


def test_theme_events_count_param_and_as_of_override() -> None:
    client = _events_client()
    result = stock_theme_events_request_result(
        {"count": 5, "as_of_date": "20260801"}, client=client, today=TODAY
    )
    assert client.entry_calls("events") == [["00401", "", 5]]
    assert result.meta["tdx_theme_event_limit"] == 5
    assert result.meta["as_of_date"] == "20260801"


def test_theme_events_missing_theme_code_raises() -> None:
    payload = _table(
        ["N001", "N002", "N003", "N004", "N005", "N006", "N007"],
        [["1", "2026-08-16", "", "题材", "2026-06-15", "无题材代码事件", "0_300243"]],
    )
    client = FakeIcfqsClient(events_payload=payload)
    with pytest.raises(ThemeColumnError, match="theme_code"):
        stock_theme_events_request_result({}, client=client, today=TODAY)


def test_theme_interfaces_registered_in_adapter_dispatch() -> None:
    from axdata_source_tdx.interface_sets import SUPPORTED_INTERFACES
    from axdata_source_tdx.request_adapter import TdxRequestAdapter
    from axdata_source_tdx.request_dispatch import TDX_ICFQS_INTERFACES

    assert {"stock_theme_members_tdx", "stock_theme_events_tdx"} <= SUPPORTED_INTERFACES
    assert TDX_ICFQS_INTERFACES == {
        "stock_theme_members_tdx": "_request_stock_theme_members",
        "stock_theme_events_tdx": "_request_stock_theme_events",
    }
    for method in TDX_ICFQS_INTERFACES.values():
        assert callable(getattr(TdxRequestAdapter, method))


def test_theme_collectors_declared_in_collector_specs() -> None:
    from axdata_source_tdx.collectors import (
        TDX_INDEPENDENT_COLLECTOR_INTERFACES,
        tdx_collector_specs,
    )

    assert {"stock_theme_members_tdx", "stock_theme_events_tdx"} <= set(
        TDX_INDEPENDENT_COLLECTOR_INTERFACES
    )
    specs = {spec.name: spec for spec in tdx_collector_specs()}
    members = specs["tdx.stock_theme_members_tdx.snapshot"]
    events = specs["tdx.stock_theme_events_tdx.snapshot"]

    assert members.dataset_id == "tdx.stock_theme_members"
    assert members.category == "theme"
    assert members.output["layer"] == "core"
    assert members.output["primary_key"] == ["theme_code", "setcode", "instrument_id", "as_of_date"]
    assert members.output["partition_by"] == ["as_of_date"]
    assert members.output["date_field"] == "as_of_date"
    assert members.output["write_mode"] == "snapshot"
    assert members.output["default_output_path_parts"] == ["core", "table=theme_members"]
    # 确定性 stem：只含 snapshot_date（=as_of_date），当日重跑幂等覆盖。
    assert members.output["file_name_template"] == "{interface_name}_{snapshot_date}"
    assert members.output["datasets"][0]["table"] == "theme_members"

    assert events.dataset_id == "tdx.stock_theme_events"
    assert events.output["primary_key"] == ["theme_code", "event_date", "as_of_date"]
    assert events.output["partition_by"] == ["as_of_date"]
    assert events.output["default_output_path_parts"] == ["core", "table=theme_events"]
    assert events.output["file_name_template"] == "{interface_name}_{snapshot_date}"


def test_theme_entries_in_provider_manifest() -> None:
    from axdata_core.plugins import ProviderManifest

    package_root = Path(__file__).resolve().parents[1] / "packages" / "axdata-source-tdx"
    manifest_path = package_root / "src" / "axdata_source_tdx" / "axdata-provider.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = ProviderManifest.from_dict(payload)

    interfaces = {interface.name: interface for interface in manifest.interfaces}
    assert interfaces["stock_theme_members_tdx"].collection.supported is True
    assert interfaces["stock_theme_members_tdx"].collection.default_profile == (
        "stock_theme_members_tdx.snapshot"
    )
    assert interfaces["stock_theme_events_tdx"].collection.default_profile == (
        "stock_theme_events_tdx.snapshot"
    )

    downloaders = {downloader.interface_name: downloader for downloader in manifest.downloaders}
    members_output = downloaders["stock_theme_members_tdx"].output
    assert members_output["output_layer"] == "core"
    assert members_output["write_mode"] == "snapshot"
    assert members_output["partition_by"] == ["as_of_date"]
    assert members_output["date_field"] == "as_of_date"
    assert members_output["primary_key"] == ["theme_code", "setcode", "instrument_id", "as_of_date"]
    assert members_output["file_name_template"] == "{interface_name}_{snapshot_date}"
    assert members_output["snapshot_date_meta_keys"][0] == "as_of_date"
    events_output = downloaders["stock_theme_events_tdx"].output
    assert events_output["primary_key"] == ["theme_code", "event_date", "as_of_date"]


def test_theme_runtime_profiles_match_manifest_shape() -> None:
    from axdata_core.downloaders import ConcurrencyProfile, DownloaderProfile
    from axdata_source_tdx.downloader_profiles import tdx_downloader_profiles

    profiles = tdx_downloader_profiles(ConcurrencyProfile, DownloaderProfile)
    members = profiles["stock_theme_members_tdx"]
    events = profiles["stock_theme_events_tdx"]

    assert members.primary_key == ("theme_code", "setcode", "instrument_id", "as_of_date")
    assert members.write_mode == "snapshot"
    assert members.partition_by == ["as_of_date"]
    assert members.date_field == "as_of_date"
    assert members.output_layer == "core"
    assert members.file_stem_template == "{interface_name}_{snapshot_date}"
    assert members.snapshot_date_meta_keys == ["as_of_date", "data_date", "trade_date", "date"]
    assert members.default_output_path_parts == ["core", "table=theme_members"]
    assert events.primary_key == ("theme_code", "event_date", "as_of_date")
    assert events.default_params == {"count": 100}


def _reload_tdx_modules() -> None:
    """Drop cached axdata_source_tdx modules and re-import the fetch module.

    test_tdx_provider_package installs the package into a temp dir and leaves
    sys.path polluted, so a later import of the collector entry can bind to a
    *copy* module while this test patches the original - the mock never takes
    effect and the run silently hits the live gateway. Forcing one identity
    before patching keeps the functional run-tests hermetic.
    """

    for name in [m for m in sys.modules if m.startswith("axdata_source_tdx")]:
        del sys.modules[name]
    globals()["icfqs_theme_fetch"] = __import__(
        "axdata_source_tdx.icfqs_theme_fetch", fromlist=["*"]
    )


def test_run_tdx_collector_theme_members_without_wire_client(monkeypatch, tmp_path) -> None:
    _reload_tdx_modules()
    fake = _client_with_three_themes()
    monkeypatch.setattr(icfqs_theme_fetch, "IcfqsClient", lambda: fake)

    from axdata_source_tdx import request_adapter
    from axdata_source_tdx.collectors import run_tdx_collector

    def _no_wire(**_kwargs: Any) -> None:
        raise AssertionError("ICFQS 题材族接口不应创建 TDX 行情 wire client")

    monkeypatch.setattr(request_adapter, "create_tdx_client", _no_wire)

    result = run_tdx_collector(
        collector={"collector_id": "tdx.stock_theme_members_tdx.snapshot"},
        params={"as_of_date": "20260816"},
        data_root=str(tmp_path),
    )

    assert result["meta"]["interface_name"] == "stock_theme_members_tdx"
    assert result["meta"]["dataset_id"] == "tdx.stock_theme_members"
    assert result["meta"]["data_date"] == "20260816"
    assert result["meta"]["tdx_theme_count"] == 3
    assert {row["as_of_date"] for row in result["records"]} == {"20260816"}
    assert len(result["records"]) == 4


def test_run_tdx_collector_theme_events(monkeypatch, tmp_path) -> None:
    _reload_tdx_modules()
    fake = _events_client()
    monkeypatch.setattr(icfqs_theme_fetch, "IcfqsClient", lambda: fake)

    from axdata_source_tdx.collectors import run_tdx_collector

    result = run_tdx_collector(
        collector={"collector_id": "tdx.stock_theme_events_tdx.snapshot"},
        params={},
        data_root=str(tmp_path),
    )

    assert result["meta"]["dataset_id"] == "tdx.stock_theme_events"
    assert result["meta"]["data_date"] == date.today().strftime("%Y%m%d")
    assert [row["theme_code"] for row in result["records"]] == ["1317", "880915"]


def test_theme_events_dedupes_identical_and_merges_distinct_texts(monkeypatch):
    from axdata_source_tdx import icfqs_theme_fetch as fetch

    class FlapClient:
        default_url = "test"

        def request_icfqs(self, entry, params):
            assert entry == "events"
            return {
                "ResultSets": [
                    {
                        "ColName": ["N001", "N003", "N004", "N005", "N006", "N007", "N008"],
                        "Content": [
                            [
                                1,
                                "880948",
                                "人工智能",
                                "20260826",
                                " 同一事件A",
                                "0_300017",
                                "0.10%",
                            ],
                            [
                                2,
                                "880948",
                                "人工智能",
                                "20260826",
                                " 同一事件A",
                                "0_300017",
                                "0.10%",
                            ],
                            [3, "880948", "人工智能", "20260826", "另一事件B", "1_600000", None],
                            [4, "880742", "固态电池", "20260817", "大会事件", "0_300243", "-1.0%"],
                        ],
                    }
                ]
            }

    result = fetch.stock_theme_events_request_result(
        {"as_of_date": "20260814"}, client=FlapClient()
    )

    assert len(result.rows) == 2
    ai = next(r for r in result.rows if r["theme_code"] == "880948")
    assert "同一事件A" in ai["event_text"] and "另一事件B" in ai["event_text"]
    assert set(ai["member_codes"].split(",")) == {"0_300017", "1_600000"}
    assert result.meta["tdx_theme_event_source_count"] == 4


def test_theme_members_empty_catalog_fails_loudly(monkeypatch):
    import pytest as _pytest
    from axdata_source_tdx import icfqs_theme_fetch as fetch

    class EmptyClient:
        default_url = "test"

        def request_icfqs(self, entry, params):
            return {"ResultSets": [{"ColName": ["N001"], "Content": []}]}

    with _pytest.raises(ValueError, match="empty catalog"):
        fetch.stock_theme_members_request_result({"as_of_date": "20260814"}, client=EmptyClient())


def test_topic_setcode_880_forced_to_2_even_when_json_says_1():
    from axdata_source_tdx.icfqs_theme_fetch import _topic_setcode

    # Live: "880915" carries setcode "1" in N005 but its constituents only
    # answer on setcode=2 (880652/s2 -> 100 rows, verified 2026-08-16).
    row = {"N005": '[{"code":"880915","name":"昨日突涨","setcode":"1"}]'}
    assert _topic_setcode(row, "880915") == "2"
    assert _topic_setcode({}, "880652") == "2"
    assert _topic_setcode({"N005": None}, "1317") == "1"
