"""ICFQS 查询方法层（P2）测试：PostJSON 三入口 body 构造、request_icfqs_json
路由/轮换/解析、题材族与 hot cfg 族查询方法的参数与表解析。

全部 mock（FakeQueryClient / capturing urlopen），不连真机；列形态按
gotdx icfqs.go @c6958ea 规格构造。真机边界（波动/空行/503）由 smoke 记录，
不在此覆盖。
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from axdata_source_tdx import icfqs_queries as queries
from axdata_source_tdx import tqlex


def _table(columns: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    return {"ErrorCode": 0, "ResultSets": [{"ColName": columns, "Content": rows}]}


def _col_des_table(names: list[str], rows: list[list[Any]]) -> dict[str, Any]:
    return {"ResultSets": [{"ColDes": [{"Name": name} for name in names], "Content": rows}]}


class FakeQueryClient:
    """按入口路由的手造 ICFQS 客户端；记录 Params 与 JSON 两类调用。"""

    default_url = "http://119.3.157.89:7615"
    hot_url = "http://hot.icfqs.com:7615"

    def __init__(self, responses: dict[str, Any] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[tuple[str, list[Any]]] = []
        self.json_calls: list[tuple[str, Any]] = []

    def request_icfqs(self, entry: str, params: list[Any]) -> dict[str, Any]:
        self.calls.append((entry, list(params)))
        return self._response(entry)

    def request_icfqs_json(self, entry: str, body: Any) -> dict[str, Any]:
        self.json_calls.append((entry, body))
        return self._response(entry)

    def _response(self, entry: str) -> dict[str, Any]:
        if entry not in self.responses:
            raise AssertionError(f"unexpected entry {entry}")
        return self.responses[entry]

    def entry_params(self, entry: str) -> list[list[Any]]:
        return [params for name, params in self.calls if name == entry]


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc_info: Any) -> bool:
        return False

    def read(self) -> bytes:
        return self._body


# ---------------------------------------------------------------------------
# PostJSON 三入口 body 构造（gotdx icfqs.go 逐字段对照）
# ---------------------------------------------------------------------------


def test_topic_quotes_body_matches_gotdx() -> None:
    body = queries.topic_quotes_body([("2", "308742"), ("1", "600000")])
    assert body == [
        {
            "ReqId": "200800",
            "modname": "module_misc.dll",
            "Code": ["308742", "600000"],
            "PageSize": "2",
            "Page": "0",
            "Desc": "0",
            "Setcode": ["2", "1"],
            "Sort": "0",
        }
    ]


def test_topic_rotation_body_defaults_and_zero_coercion() -> None:
    defaults = queries.topic_rotation_body()
    assert defaults == [
        {
            "ReqId": "200773",
            "modname": "mod_copilot.dll",
            "dataDate": "2",
            "dataType": "1",
            "dataNum": "1",
            "themeType": "0",
        }
    ]
    # gotdx 语义：0 视为未设置回落默认；空 theme_type 回落 "0"。
    assert queries.topic_rotation_body(0, 0, 0, "") == defaults
    explicit = queries.topic_rotation_body(5, 3, 1, "1")
    assert explicit[0]["dataNum"] == "5"
    assert explicit[0]["dataType"] == "3"
    assert explicit[0]["dataDate"] == "1"
    assert explicit[0]["themeType"] == "1"


def test_quotes_batch_body_default_and_explicit_columns() -> None:
    codes = [("0", "000001"), ("1", "600000")]
    assert queries.quotes_batch_body(codes) == {
        "Setcode": ["0", "1"],
        "Head": {"Target": 0},
        "WantCol": ["CLOSE", "NOW"],
        "Code": ["000001", "600000"],
    }
    explicit = queries.quotes_batch_body(codes, ["CLOSE", "OPEN", "AMOUNT"])
    assert explicit["WantCol"] == ["CLOSE", "OPEN", "AMOUNT"]


# ---------------------------------------------------------------------------
# IcfqsClient.request_icfqs_json：路由 / body 原样 / 解析 / 轮换
# ---------------------------------------------------------------------------


def _capture_urlopen(captured: list[dict[str, Any]], body_for: Any) -> Any:
    """body_for: bytes，或 callable(url)->bytes。"""

    def urlopen(request: Any, timeout: float) -> _FakeResponse:
        captured.append(
            {
                "url": request.full_url,
                "content_type": request.get_header("Content-type"),
                "data": request.data,
            }
        )
        body = body_for(request.full_url) if callable(body_for) else body_for
        return _FakeResponse(body)

    return urlopen


def test_request_icfqs_json_routes_and_posts_body_verbatim(monkeypatch) -> None:
    captured: list[dict[str, Any]] = []
    body = [{"ReqId": "200800", "modname": "module_misc.dll"}]
    response = json.dumps({"ResultSets": []}).encode("utf-8")
    monkeypatch.setattr(tqlex, "urlopen", _capture_urlopen(captured, response))

    decoded = tqlex.IcfqsClient().request_icfqs_json("topic_quotes", body)

    assert captured[0]["url"] == "http://119.3.157.89:7615/TQLEX?Entry=HQServ.hq_nlp"
    assert captured[0]["content_type"] == "text/plain;charset=UTF-8"
    # body 原样 JSON POST：不包 Params/oauth_zzfw。
    assert json.loads(captured[0]["data"]) == body
    assert decoded == {"ResultSets": []}


def test_request_icfqs_json_unknown_entry_raises() -> None:
    with pytest.raises(ValueError, match="unknown icfqs entry"):
        tqlex.IcfqsClient().request_icfqs_json("nope", {})


def test_request_icfqs_json_plain_parse_and_junk_fallback(monkeypatch) -> None:
    captured: list[dict[str, Any]] = []
    # 网关偶发在 JSON 前吐垃圾字节（TQL 同源主机已观测）：回落 brace scanner。
    junk = b'junk<html>{"hq": [1, 2]} trailing'
    monkeypatch.setattr(tqlex, "urlopen", _capture_urlopen(captured, junk))
    decoded = tqlex.IcfqsClient().request_icfqs_json("topic_rotation", [{"ReqId": "200773"}])
    assert decoded == {"hq": [1, 2]}


def test_request_icfqs_json_non_dict_response_raises(monkeypatch) -> None:
    captured: list[dict[str, Any]] = []
    monkeypatch.setattr(tqlex, "urlopen", _capture_urlopen(captured, b"[1, 2]"))
    with pytest.raises(ValueError, match="must be a JSON object"):
        tqlex.IcfqsClient().request_icfqs_json("quotes_batch", {})


def test_request_icfqs_json_rotates_default_pool_on_failure(monkeypatch) -> None:
    captured: list[dict[str, Any]] = []

    def body_for(url: str) -> bytes:
        if "119.3.157.89" in url:
            raise OSError("gateway flap")
        return json.dumps({"ResultSets": [{"ColName": ["a"], "Content": [["v"]]}]}).encode()

    monkeypatch.setattr(tqlex, "urlopen", _capture_urlopen(captured, body_for))
    decoded = tqlex.IcfqsClient().request_icfqs_json("quotes_batch", {"Code": ["000001"]})
    assert [entry["url"].split("/TQLEX")[0] for entry in captured] == [
        "http://119.3.157.89:7615",
        "http://139.9.211.159:7615",
    ]
    assert decoded["ResultSets"][0]["ColName"] == ["a"]


# ---------------------------------------------------------------------------
# HQServ 三入口薄封装：入口名 + body 透传
# ---------------------------------------------------------------------------


def test_topic_quotes_wrapper(monkeypatch) -> None:
    fake = FakeQueryClient(responses={"topic_quotes": {"ResultSets": []}})
    monkeypatch.setattr(queries, "IcfqsClient", lambda: fake)
    result = queries.topic_quotes([("2", "308742")])
    assert result == {"ResultSets": []}
    entry, body = fake.json_calls[0]
    assert entry == "topic_quotes"
    assert body == queries.topic_quotes_body([("2", "308742")])


def test_topic_rotation_wrapper_defaults(monkeypatch) -> None:
    fake = FakeQueryClient(responses={"topic_rotation": {"ResultSets": []}})
    monkeypatch.setattr(queries, "IcfqsClient", lambda: fake)
    queries.topic_rotation()
    entry, body = fake.json_calls[0]
    assert entry == "topic_rotation"
    assert body == queries.topic_rotation_body()


def test_quotes_batch_wrapper(monkeypatch) -> None:
    fake = FakeQueryClient(responses={"quotes_batch": {"ListItem": []}})
    monkeypatch.setattr(queries, "IcfqsClient", lambda: fake)
    result = queries.quotes_batch([("0", "000001")], ["CLOSE"])
    assert result == {"ListItem": []}
    entry, body = fake.json_calls[0]
    assert entry == "quotes_batch"
    assert body == queries.quotes_batch_body([("0", "000001")], ["CLOSE"])


# ---------------------------------------------------------------------------
# 题材族明细/排行/搜索：Params 构造 + 表解析
# ---------------------------------------------------------------------------


def test_topic_detail_params_and_rows() -> None:
    payload = _table(["N001", "N002", "N003"], [["1", "880915", "昨日突涨"]])
    fake = FakeQueryClient(responses={"topic_detail": payload})

    tables = queries.topic_detail("880915", "2", client=fake)

    assert fake.entry_params("topic_detail") == [["00301", "880915", "2"]]
    assert tables[0].columns == ("N001", "N002", "N003")
    assert tables[0].rows[0]["N003"] == "昨日突涨"


def test_topic_kline_params_keep_gotdx_fixed_period() -> None:
    payload = _table(
        ["N001", "N002", "N003", "N004", "N005", "N006"],
        [["2026-08-15", "1000.1", "1010.5", "998.0", "1005.3", "12345"]],
    )
    fake = FakeQueryClient(responses={"topic_kline": payload})

    tables = queries.topic_kline("880915", "2", client=fake)

    # 第 3 参固定 3、第 4 参空串（gotdx ICFQSTopicKLineRaw 原样）。
    assert fake.entry_params("topic_kline") == [["00501", "880915", 3, "", "2"]]
    assert tables[0].rows[0]["N001"] == "2026-08-15"
    assert tables[0].rows[0]["N005"] == "1005.3"


def test_search_topics_params() -> None:
    payload = _table(["N001", "N002", "N003"], [["1", "1317", "世界杯概念"]])
    fake = FakeQueryClient(responses={"search_topics": payload})

    tables = queries.search_topics("世界杯", client=fake)

    assert fake.entry_params("search_topics") == [["00102", "世界杯", "0"]]
    assert tables[0].rows[0]["N003"] == "世界杯概念"


def test_hot_topics_params() -> None:
    payload = _table(["N001", "N002"], [["1", "880915"]])
    fake = FakeQueryClient(responses={"hot_topics": payload})

    tables = queries.hot_topics(client=fake)

    assert fake.entry_params("hot_topics") == [["00302", "", 1]]
    assert tables[0].rows[0]["N002"] == "880915"


def test_top_topics_default_and_zero_coercion() -> None:
    payload = _table(["N001", "N002"], [["1", "1317"]])
    fake = FakeQueryClient(responses={"top_topics": payload})

    queries.top_topics(client=fake)
    assert fake.entry_params("top_topics") == [["00101", "", 10]]

    queries.top_topics(5, client=fake)
    assert fake.entry_params("top_topics")[-1] == ["00101", "", 5]

    queries.top_topics(0, client=fake)  # gotdx：topN<=0 取 10
    assert fake.entry_params("top_topics")[-1] == ["00101", "", 10]


def test_new_topics_params() -> None:
    payload = _table(["N001", "N002", "N003"], [["1", "880001", "新增题材"]])
    fake = FakeQueryClient(responses={"new_topics": payload})

    tables = queries.new_topics(client=fake)

    assert fake.entry_params("new_topics") == [["01001", "", 1]]
    assert tables[0].rows[0]["N003"] == "新增题材"


# ---------------------------------------------------------------------------
# hot 网关 cfg 族：Params 构造 + 每方法 ≥1 个表解析测试
# ---------------------------------------------------------------------------


def test_lhb_detail_params_and_rows() -> None:
    # 空 symbol + 近期区间 = 全市场榜单口径（真机调参结论见 smoke 记录）。
    payload = _col_des_table(
        ["CODE", "NAME", "REASON", "NET_BUY"],
        [["000066", "中国联通", "日涨幅偏离值达7%", "120000000"]],
    )
    fake = FakeQueryClient(responses={"lhb_detail": payload})

    tables = queries.lhb_detail("", "2026-08-01", "2026-08-16", client=fake)

    assert fake.entry_params("lhb_detail") == [
        ["yybxq", "2026-08-01", "2026-08-16", "", "", 0, 2000]
    ]
    # ColDes.Name 列名兜底路径也要能出表。
    assert tables[0].columns == ("CODE", "NAME", "REASON", "NET_BUY")
    assert tables[0].rows[0]["NAME"] == "中国联通"
    assert tables[0].rows[0]["NET_BUY"] == "120000000"


def test_lhb_detail_symbol_scoped_params() -> None:
    payload = _table(["CODE"], [["000066"]])
    fake = FakeQueryClient(responses={"lhb_detail": payload})

    queries.lhb_detail("000066", "20260801", "20260816", client=fake)

    assert fake.entry_params("lhb_detail") == [
        ["yybxq", "20260801", "20260816", "000066", "", 0, 2000]
    ]


def test_yyb_detail_params_and_rows() -> None:
    payload = _table(
        ["YYB", "BUY_AMT", "SELL_AMT"],
        [["东方财富证券拉萨团结路第二证券营业部", "300000000", "280000000"]],
    )
    fake = FakeQueryClient(responses={"yyb_detail": payload})

    tables = queries.yyb_detail("东方财富证券拉萨团结路第二证券营业部", "", "", client=fake)

    # 空日期走服务端默认（webviewer 口径）。
    assert fake.entry_params("yyb_detail") == [
        ["tjyyb", "", "", "", "东方财富证券拉萨团结路第二证券营业部", 0, 2000]
    ]
    assert tables[0].rows[0]["BUY_AMT"] == "300000000"


def test_yz_detail_params_and_rows() -> None:
    payload = _table(["CODE", "NAME", "TOTAL_NET_BUY"], [["88800001", "知名游资", "980000000"]])
    fake = FakeQueryClient(responses={"yz_detail": payload})

    tables = queries.yz_detail("88800001", "2026-08-01", "2026-08-16", client=fake)

    assert fake.entry_params("yz_detail") == [
        ["yzxq", "2026-08-01", "2026-08-16", "88800001", "", 0, 2000]
    ]
    assert tables[0].rows[0]["NAME"] == "知名游资"


def test_mrfp_params_and_limit_default() -> None:
    payload = _table(["DATE", "TEXT"], [["20260814", "三大指数收涨"]])
    fake = FakeQueryClient(responses={"mrfp": payload})

    tables = queries.mrfp("20260814", "jrpm", client=fake)

    assert fake.entry_params("mrfp") == [["20260814", "jrpm", "", 0, 30]]
    assert tables[0].rows[0]["TEXT"] == "三大指数收涨"

    queries.mrfp("20260814", "ztfx", 0, client=fake)  # gotdx：limit<=0 取 30
    assert fake.entry_params("mrfp")[-1] == ["20260814", "ztfx", "", 0, 30]

    queries.mrfp("20260814", "rq", 50, client=fake)
    assert fake.entry_params("mrfp")[-1] == ["20260814", "rq", "", 0, 50]


def test_mrfp_latest_date_params_and_rows() -> None:
    payload = _table(["RQ"], [["2026-08-14"]])
    fake = FakeQueryClient(responses={"mrfp_latest_date": payload})

    tables = queries.mrfp_latest_date(client=fake)

    # date="0" + review_type="rq" 即最新可用日期口径。
    assert fake.entry_params("mrfp_latest_date") == [["0", "rq", "", 0, 30]]
    assert tables[0].rows[0]["RQ"] == "2026-08-14"
