"""ICFQS 查询方法层（P2）：题材明细/排行/搜索、HQServ 行情三入口、hot 网关龙虎榜与每日复盘。

规格来自 gotdx icfqs.go（@c6958ea）的 ICFQS*Raw 方法：本模块只做
"参数构造 → IcfqsClient 请求 → icfqs_tables 表化"，不做采集任务/落表
（collector 注册属 P2 后续单独立项）。所有方法 best-effort：网关波动、
空行、503 直接向上抛（客户端层已做 default 池轮换），不在此重试。

入口 → 方法对照（Params/body 形态照抄 gotdx）：

- topic_detail        ["00301", code, setcode]                CWServ.ph_tdxdatacenter_zttz_xqy
- topic_kline         ["00501", code, 3, "", setcode]         CWServ...zttz_xqy_v2_qsid
- search_topics       ["00102", keyword, "0"]                 CWServ.ph_tdxdatacenter_zttz_zy
- hot_topics          ["00302", "", 1]                        同上
- top_topics          ["00101", "", top_n]                    同上
- new_topics          ["01001", "", 1]                        DataAggregation.zttz_xzgn2
- topic_quotes        PostJSON [ {ReqId 200800, module_misc.dll, …} ]   HQServ.hq_nlp
- topic_rotation      PostJSON [ {ReqId 200773, mod_copilot.dll, …} ]   HQServ.hq_nlp_copilot
- quotes_batch        PostJSON { Setcode/Head/WantCol/Code }             HQServ.PBCombHQ
- lhb_detail          ["yybxq", start, end, symbol, "", 0, 2000]  hot: CWServ.cfg_fx_yzlhb
- yyb_detail          ["tjyyb", start, end, "", yyb, 0, 2000]     hot: 同上
- yz_detail           ["yzxq", start, end, code, "", 0, 2000]     hot: 同上
- mrfp                [date, review_type, "", 0, limit]            hot: CWServ.cfg_tk_mrfp
- mrfp_latest_date    ["0", "rq", "", 0, 30]                       hot: 同上
  （date="0" + review_type="rq" 即"最新可用日期"口径，gotdx ICFQSMRFPLatestDateRaw）

hot 族 start/end/date 口径（gotdx webviewer 帮助文本）：YYYY-MM-DD 或
YYYYMMDD，空串走服务端默认。codes 形态统一 (setcode, code) 二元组序列，
与 gotdx ICFQSCode 对齐。

真机结论（2026-08-16，hot.icfqs.com + default 池，逐入口 1 次 smoke）：

- 题材族全通：topic_detail 返回 9 列详情（动态题材 880915 已下架→0 行，
  1317/1 与 880652/2 正常）；topic_kline 56 行日线；search/hot/top/new
  均返回行数据。
- topic_quotes / topic_rotation 返回标准 ResultSets（多表）；quotes_batch
  返回 Ans/SBTSize/ListHead/ListItem 形态（无 ResultSets，ListItem 每项
  为代码+行情数组）。
- lhb_detail：**空 symbol 不返回全市场榜单**（双日期格式/单日/区间/历史
  区间均 0 行）；传真实 6 位代码 + 命中区间返回该股上榜史（000066 +
  2025 全年 → 50 行营业部明细 + 4 行上榜汇总，mrje/mcje 为数值）。
- yyb_detail：需营业部**完整精确名**（从 lhb 行反查"东方财富证券股份有限
  公司拉萨东环路第二证券营业部"→3138 行）；传入日期区间疑似不生效
  （2025 区间返回 2026-08-14 数据），best-effort 保留原样传参。
- yz_detail：真机未取得非空数据（空 code / 游资名 / 空区间均 0 行），
  三表结构（主表 + yzmc/description + yzmc/yyb）稳定返回；code 语义
  （疑似内部游资 ID）待后续从其它入口反查。
- mrfp："0"/"rq" 口径返回 20 个可用日期（首行即最新 20260814）；
  mrfp(20260814, "jrpm") 返回 7 张表（涨跌统计 242 行、63 列市场总表、
  龙虎榜数/涨停家数等日序列）。
- hot 网关无 503；default 池轮换下无整族失败。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .tqlex import IcfqsClient, IcfqsTable, icfqs_tables

# gotdx 固定值：topic_kline 第 3 参（周期/口径语义未公开，照抄规格不得改动）。
_TOPIC_KLINE_FIXED_PERIOD = 3
# hot 族 cfg_fx_yzlhb 固定分页：第 6/7 参 (0, 2000)（gotdx 原样）。
_LHB_PAGE_PARAMS = [0, 2000]
# mrfp limit 默认值（gotdx：limit<=0 时取 30）。
_MRFP_DEFAULT_LIMIT = 30
# top_topics 默认 top_n（gotdx：topN<=0 时取 10）。
_TOP_TOPICS_DEFAULT_N = 10
# quotes_batch 默认列（gotdx：wantColumns 为空时取 CLOSE/NOW）。
_QUOTES_BATCH_DEFAULT_COLUMNS = ("CLOSE", "NOW")


# ---------------------------------------------------------------------------
# HQServ PostJSON 三入口：body 构造（纯函数，供测试与调用方检查）
# ---------------------------------------------------------------------------


def topic_quotes_body(codes: Sequence[tuple[str, str]]) -> list[dict[str, Any]]:
    """gotdx ICFQSTopicQuotesRaw body：ReqId 200800 / module_misc.dll。

    codes 为 (setcode, code) 二元组序列；PageSize 跟随代码数（字符串形态）。
    """

    code_values = [code for _setcode, code in codes]
    setcode_values = [setcode for setcode, _code in codes]
    return [
        {
            "ReqId": "200800",
            "modname": "module_misc.dll",
            "Code": code_values,
            "PageSize": f"{len(code_values)}",
            "Page": "0",
            "Desc": "0",
            "Setcode": setcode_values,
            "Sort": "0",
        }
    ]


def topic_rotation_body(
    data_num: int = 1,
    data_type: int = 1,
    data_date: int = 2,
    theme_type: str = "0",
) -> list[dict[str, Any]]:
    """gotdx ICFQSTopicRotationRaw body：ReqId 200773 / mod_copilot.dll。

    gotdx 语义：data_num/data_type/data_date 传 0 视为未设置，回落
    1/1/2；theme_type 空串回落 "0"。数值一律转字符串形态。
    """

    if data_num == 0:
        data_num = 1
    if data_type == 0:
        data_type = 1
    if data_date == 0:
        data_date = 2
    if not theme_type:
        theme_type = "0"
    return [
        {
            "ReqId": "200773",
            "modname": "mod_copilot.dll",
            "dataDate": f"{data_date}",
            "dataType": f"{data_type}",
            "dataNum": f"{data_num}",
            "themeType": theme_type,
        }
    ]


def quotes_batch_body(
    codes: Sequence[tuple[str, str]],
    want_columns: Sequence[str] | None = None,
) -> dict[str, Any]:
    """gotdx ICFQSQuotesBatchRaw body：HQServ.PBCombHQ 批量行情。

    want_columns 为空时取默认 ("CLOSE", "NOW")；Head.Target 固定 0。
    """

    columns = list(want_columns) if want_columns else list(_QUOTES_BATCH_DEFAULT_COLUMNS)
    return {
        "Setcode": [setcode for setcode, _code in codes],
        "Head": {"Target": 0},
        "WantCol": columns,
        "Code": [code for _setcode, code in codes],
    }


def topic_quotes(
    codes: Sequence[tuple[str, str]], *, client: IcfqsClient | None = None
) -> dict[str, Any]:
    """题材/个股行情快照（hq_nlp）。响应含多张 ResultSets 表（gotdx webviewer
    取 table_index=1 展示），P2 原样返回解码 dict，表选择留给调用方。"""

    icfqs = client if client is not None else IcfqsClient()
    return icfqs.request_icfqs_json("topic_quotes", topic_quotes_body(codes))


def topic_rotation(
    *,
    data_num: int = 1,
    data_type: int = 1,
    data_date: int = 2,
    theme_type: str = "0",
    client: IcfqsClient | None = None,
) -> dict[str, Any]:
    """题材轮动（hq_nlp_copilot）。响应含多张表（webviewer 取 table_index=2），
    P2 原样返回解码 dict。"""

    icfqs = client if client is not None else IcfqsClient()
    body = topic_rotation_body(data_num, data_type, data_date, theme_type)
    return icfqs.request_icfqs_json("topic_rotation", body)


def quotes_batch(
    codes: Sequence[tuple[str, str]],
    want_columns: Sequence[str] | None = None,
    *,
    client: IcfqsClient | None = None,
) -> dict[str, Any]:
    """批量行情快照（PBCombHQ）。响应是 ListItem 形态（无 ResultSets，
    gotdx webviewer 走 payloadFromICFQSListItems），原样返回解码 dict。"""

    icfqs = client if client is not None else IcfqsClient()
    return icfqs.request_icfqs_json("quotes_batch", quotes_batch_body(codes, want_columns))


# ---------------------------------------------------------------------------
# 题材族明细/排行/搜索（default 池，Params 形态）
# ---------------------------------------------------------------------------


def _tables(entry: str, params: list[Any], client: IcfqsClient | None) -> list[IcfqsTable]:
    icfqs = client if client is not None else IcfqsClient()
    return icfqs_tables(icfqs.request_icfqs(entry, params))


def topic_detail(code: str, setcode: str, *, client: IcfqsClient | None = None) -> list[IcfqsTable]:
    """题材详情（CWServ...zttz_xqy）：["00301", code, setcode]。"""

    return _tables("topic_detail", ["00301", code, setcode], client)


def topic_kline(code: str, setcode: str, *, client: IcfqsClient | None = None) -> list[IcfqsTable]:
    """题材K线/走势（CWServ...zttz_xqy_v2_qsid）：["00501", code, 3, "", setcode]。

    P2 只实现查询方法，不做采集任务（K线落库属后续立项）。
    """

    return _tables("topic_kline", ["00501", code, _TOPIC_KLINE_FIXED_PERIOD, "", setcode], client)


def search_topics(keyword: str, *, client: IcfqsClient | None = None) -> list[IcfqsTable]:
    """题材搜索（CWServ...zttz_zy）：["00102", keyword, "0"]。"""

    return _tables("search_topics", ["00102", keyword, "0"], client)


def hot_topics(*, client: IcfqsClient | None = None) -> list[IcfqsTable]:
    """热门题材（CWServ...zttz_zy）：["00302", "", 1]。"""

    return _tables("hot_topics", ["00302", "", 1], client)


def top_topics(
    top_n: int = _TOP_TOPICS_DEFAULT_N, *, client: IcfqsClient | None = None
) -> list[IcfqsTable]:
    """领涨题材（CWServ...zttz_zy）：["00101", "", top_n]；top_n<=0 取 10（gotdx）。"""

    if top_n <= 0:
        top_n = _TOP_TOPICS_DEFAULT_N
    return _tables("top_topics", ["00101", "", top_n], client)


def new_topics(*, client: IcfqsClient | None = None) -> list[IcfqsTable]:
    """新增题材（DataAggregation.zttz_xzgn2）：["01001", "", 1]。"""

    return _tables("new_topics", ["01001", "", 1], client)


# ---------------------------------------------------------------------------
# hot 网关 cfg 族：龙虎榜 / 每日复盘（只做查询方法，不做 collector/落表）
# ---------------------------------------------------------------------------


def lhb_detail(
    symbol: str, start: str, end: str, *, client: IcfqsClient | None = None
) -> list[IcfqsTable]:
    """个股龙虎榜（hot: CWServ.cfg_fx_yzlhb）：["yybxq", start, end, symbol, "", 0, 2000]。

    真机：空 symbol 不返回全市场榜单（恒 0 行）；需真实 6 位代码 + 命中
    区间才返回该股上榜史（见模块 docstring 真机结论）。
    """

    return _tables("lhb_detail", ["yybxq", start, end, symbol, "", *_LHB_PAGE_PARAMS], client)


def yyb_detail(
    yyb: str, start: str, end: str, *, client: IcfqsClient | None = None
) -> list[IcfqsTable]:
    """营业部龙虎榜（hot: CWServ.cfg_fx_yzlhb）：["tjyyb", start, end, "", yyb, 0, 2000]。

    真机：yyb 需营业部完整精确名（模糊名恒 0 行）；start/end 疑似不生效
    （2025 区间返回 2026-08-14 数据），按 gotdx 原样传参、best-effort。
    """

    return _tables("yyb_detail", ["tjyyb", start, end, "", yyb, *_LHB_PAGE_PARAMS], client)


def yz_detail(
    code: str, start: str, end: str, *, client: IcfqsClient | None = None
) -> list[IcfqsTable]:
    """游资席位详情（hot: CWServ.cfg_fx_yzlhb）：["yzxq", start, end, code, "", 0, 2000]。

    真机：code 语义未验证（空串/游资名均 0 行），三表结构稳定返回；
    code 疑似内部游资 ID，待从其它入口反查（见模块 docstring）。
    """

    return _tables("yz_detail", ["yzxq", start, end, code, "", *_LHB_PAGE_PARAMS], client)


def mrfp(
    date: str,
    review_type: str,
    limit: int = _MRFP_DEFAULT_LIMIT,
    *,
    client: IcfqsClient | None = None,
) -> list[IcfqsTable]:
    """每日复盘（hot: CWServ.cfg_tk_mrfp）：[date, review_type, "", 0, limit]。

    review_type 常用值（gotdx webviewer）：base / jrpm / ztfx / rdgl / rq；
    date 空串走服务端默认；limit<=0 取 30（gotdx）。
    """

    if limit <= 0:
        limit = _MRFP_DEFAULT_LIMIT
    return _tables("mrfp", [date, review_type, "", 0, limit], client)


def mrfp_latest_date(*, client: IcfqsClient | None = None) -> list[IcfqsTable]:
    """每日复盘最新可用日期（hot: CWServ.cfg_tk_mrfp）：["0", "rq", "", 0, 30]。

    date="0" + review_type="rq" 即最新日期口径（gotdx ICFQSMRFPLatestDateRaw）。
    """

    return _tables("mrfp_latest_date", ["0", "rq", "", 0, _MRFP_DEFAULT_LIMIT], client)
