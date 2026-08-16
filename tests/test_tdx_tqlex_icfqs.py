"""ICFQS（通达信题材/龙虎榜数据服务）入口族测试。

覆盖 axdata_source_tdx.tqlex 的 ICFQS 扩展：入口路由表、容错 JSON 解析、
ResultSets 表格化与 env 覆盖。规格来自 gotdx（icfqs.go / hosts.go）与真机抓包。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from axdata_source_tdx import tqlex

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "icfqs" / "topic_list_20260816.json"

DEFAULT_ENTRIES = {
    "topic_list",
    "search_topics",
    "new_topics",
    "hot_topics",
    "events",
    "top_topics",
    "topic_detail",
    "topic_kline",
    "topic_stocks",
    "topic_quotes",
    "topic_rotation",
    "quotes_batch",
}
HOT_ENTRIES = {"lhb_detail", "yyb_detail", "yz_detail", "mrfp", "mrfp_latest_date"}


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc_info: Any) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


def _capturing_urlopen(captured: dict[str, Any], body: bytes):
    def urlopen(request: Any, timeout: float) -> _FakeResponse:
        captured["url"] = request.full_url
        captured["content_type"] = request.get_header("Content-type")
        captured["data"] = request.data
        return _FakeResponse(body)

    return urlopen


def _load_fixture() -> dict[str, Any]:
    with FIXTURE_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def test_icfqs_topic_list_fixture_parses_20_rows() -> None:
    payload = _load_fixture()
    assert payload["ErrorCode"] == 0
    tables = tqlex.icfqs_tables(payload)
    assert len(tables) == 1
    table = tables[0]
    assert table.columns == ("N001", "N002", "N003", "N004", "N005", "N006")
    assert len(table.rows) == 20
    assert table.rows[0]["N003"] == "昨日突涨"


def test_icfqs_gateway_families() -> None:
    assert set(tqlex.ICFQS_ENTRIES) == DEFAULT_ENTRIES | HOT_ENTRIES
    for name in DEFAULT_ENTRIES:
        assert tqlex.ICFQS_ENTRIES[name].gateway == "default"
    for name in HOT_ENTRIES:
        assert tqlex.ICFQS_ENTRIES[name].gateway == "hot"


def test_icfqs_request_routes_to_default_pool(monkeypatch) -> None:
    captured: dict[str, Any] = {}
    body = json.dumps({"ErrorCode": 0, "ResultSets": []}).encode("utf-8")
    monkeypatch.setattr(tqlex, "urlopen", _capturing_urlopen(captured, body))
    client = tqlex.IcfqsClient()
    client.request_icfqs("topic_list", ["00601", "1|1", 1])
    assert captured["url"] == "http://119.3.157.89:7615/TQLEX?Entry=CWServ.ph_tdxdatacenter_zttz_zy"
    assert captured["content_type"] == "text/plain;charset=UTF-8"
    assert json.loads(captured["data"]) == {"Params": ["00601", "1|1", 1], "oauth_zzfw": "1"}


def test_icfqs_request_routes_to_hot_gateway(monkeypatch) -> None:
    captured: dict[str, Any] = {}
    body = json.dumps({"ErrorCode": 0, "ResultSets": []}).encode("utf-8")
    monkeypatch.setattr(tqlex, "urlopen", _capturing_urlopen(captured, body))
    client = tqlex.IcfqsClient()
    client.request_icfqs("lhb_detail", ["yybxq", "20260101", "20260816", "000001", "", 0, 2000])
    assert captured["url"] == "http://hot.icfqs.com:7615/TQLEX?Entry=CWServ.cfg_fx_yzlhb"
    assert json.loads(captured["data"]) == {
        "Params": ["yybxq", "20260101", "20260816", "000001", "", 0, 2000],
        "oauth_zzfw": "1",
    }


def test_icfqs_env_overrides_both_gateways(monkeypatch) -> None:
    monkeypatch.setenv("AXDATA_TDX_ICFQS_URL", "10.0.0.1:7615")
    monkeypatch.setenv("AXDATA_TDX_ICFQS_HOT_URL", "http://10.0.0.2:7615/")
    client = tqlex.IcfqsClient()
    assert client.default_url == "http://10.0.0.1:7615"
    assert client.hot_url == "http://10.0.0.2:7615"


def test_icfqs_unknown_entry_raises() -> None:
    with pytest.raises(ValueError, match="unknown icfqs entry"):
        tqlex.IcfqsClient().request_icfqs("nope", [])


def test_parse_icfqs_json_skips_prefix_junk() -> None:
    raw = b'<html>junk</html>{"ErrorCode": 0, "ResultSets": []} trailing'
    assert tqlex._parse_icfqs_json(raw) == {"ErrorCode": 0, "ResultSets": []}


def test_parse_icfqs_json_handles_braces_and_escapes_in_strings() -> None:
    # 字符串内 { } 不计深度；\" 不关字符串；\/ 是合法 JSON 转义。
    raw = b'{"a": "\\"}", "b": "{x}", "c": "http:\\/\\/example.com"}'
    parsed = tqlex._parse_icfqs_json(raw)
    assert parsed["a"] == '"' + "}"
    assert parsed["b"] == "{x}"
    assert parsed["c"] == "http://example.com"


def test_parse_icfqs_json_no_brace_reports_preview() -> None:
    with pytest.raises(ValueError) as excinfo:
        tqlex._parse_icfqs_json(b"no json here at all" * 100)
    message = str(excinfo.value)
    prefix = "cannot parse icfqs response: "
    assert message.startswith(prefix)
    assert len(message[len(prefix) :]) == 200


def test_icfqs_tables_colname_priority_and_padding() -> None:
    payload = {"ResultSets": [{"ColName": ["A", "B", "C"], "Content": [[1, 2], [3, 4, 5]]}]}
    tables = tqlex.icfqs_tables(payload)
    assert len(tables) == 1
    assert tables[0].columns == ("A", "B", "C")
    assert tables[0].rows == ({"A": 1, "B": 2, "C": None}, {"A": 3, "B": 4, "C": 5})


def test_icfqs_tables_falls_back_to_col_des_names() -> None:
    payload = {
        "ResultSets": [{"ColDes": [{"Name": "X"}, {"Name": "Y"}], "Content": [["v1", "v2"]]}]
    }
    tables = tqlex.icfqs_tables(payload)
    assert tables[0].columns == ("X", "Y")
    assert tables[0].rows == ({"X": "v1", "Y": "v2"},)
