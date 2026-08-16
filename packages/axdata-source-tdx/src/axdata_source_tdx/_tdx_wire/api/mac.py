"""MAC channel API."""

from __future__ import annotations

from collections.abc import Sequence

from .base import ApiBase


class MacApi(ApiBase):
    """gotdx client_mac.go 的 MAC 通道命令（单次请求语义，分页由调用方驱动）。"""

    def capital_flow(self, code: str, *, include_raw: bool = False):
        return self._execute("mac_capital_flow", code=code, include_raw=include_raw)

    def server_info(self, *, include_raw: bool = False):
        return self._execute("mac_server_info", include_raw=include_raw)

    def quotes(self, code: str, *, query_date: int = 0, include_raw: bool = False):
        # with_date 变体同码同帧：query_date 填入 Zero1/Zero2 字段。
        return self._execute(
            "mac_quotes", code=code, query_date=query_date, include_raw=include_raw
        )

    def symbol_quotes(
        self,
        securities: Sequence[str],
        *,
        field_bitmap: bytes | None = None,
        include_raw: bool = False,
    ):
        return self._execute(
            "mac_symbol_quotes",
            securities=list(securities),
            field_bitmap=field_bitmap,
            include_raw=include_raw,
        )

    def symbol_bars(
        self,
        code: str,
        *,
        period: int = 4,
        times: int = 1,
        start: int = 0,
        count: int = 800,
        adjust: int = 0,
        include_raw: bool = False,
    ):
        return self._execute(
            "mac_symbol_bars",
            code=code,
            period=period,
            times=times,
            start=start,
            count=count,
            adjust=adjust,
            include_raw=include_raw,
        )

    def symbol_info(self, code: str, *, include_raw: bool = False):
        return self._execute("mac_symbol_info", code=code, include_raw=include_raw)

    def symbol_belong_board(self, code: str, *, include_raw: bool = False):
        # 0x1218 同码双语义：query 常量路由到 Stock_GLHQ（head=0x01）。
        return self._execute(
            "mac_symbol_belong_board", code=code, query="Stock_GLHQ", include_raw=include_raw
        )

    def board_count(self, board_type: int = 0):
        # board_count/board_list 同码同请求字节；count_only 只取 4 字节头。
        return self._execute("mac_board_list", board_type=board_type, count_only=True)

    def board_list(
        self,
        board_type: int = 0,
        *,
        start: int = 0,
        page_size: int = 150,
        include_raw: bool = False,
    ):
        return self._execute(
            "mac_board_list",
            board_type=board_type,
            start=start,
            page_size=page_size,
            include_raw=include_raw,
        )

    def board_members(
        self,
        board_symbol: str,
        *,
        sort_type: int = 14,
        start: int = 0,
        page_size: int = 80,
        sort_order: int = 1,
        include_raw: bool = False,
    ):
        return self._execute(
            "mac_board_members",
            board_symbol=board_symbol,
            sort_type=sort_type,
            start=start,
            page_size=page_size,
            sort_order=sort_order,
            include_raw=include_raw,
        )

    def board_members_quotes(
        self,
        board_symbol: str,
        *,
        sort_type: int = 14,
        start: int = 0,
        page_size: int = 80,
        sort_order: int = 1,
        include_raw: bool = False,
    ):
        return self._execute(
            "mac_board_members",
            board_symbol=board_symbol,
            sort_type=sort_type,
            start=start,
            page_size=page_size,
            sort_order=sort_order,
            include_quotes=True,
            include_raw=include_raw,
        )

    def board_members_quotes_dynamic(
        self,
        board_symbol: str,
        *,
        sort_type: int = 14,
        start: int = 0,
        page_size: int = 80,
        sort_order: int = 1,
        field_bitmap: bytes | None = None,
        filter: int = 0,  # noqa: A002 - gotdx MACBoardMembersQuotesDynamicRequest.Filter
        include_raw: bool = False,
    ):
        return self._execute(
            "mac_board_members",
            board_symbol=board_symbol,
            sort_type=sort_type,
            start=start,
            page_size=page_size,
            sort_order=sort_order,
            field_bitmap=field_bitmap,
            filter=filter,
            include_raw=include_raw,
        )

    def transactions(
        self,
        code: str,
        *,
        start: int = 0,
        count: int = 1000,
        query_date: int = 0,
        include_raw: bool = False,
    ):
        # with_date 变体同码同帧：QueryDate 是基础请求结构的显式字段。
        return self._execute(
            "mac_transactions",
            code=code,
            start=start,
            count=count,
            query_date=query_date,
            include_raw=include_raw,
        )

    def tick_charts(
        self,
        code: str,
        *,
        query_date: int = 0,
        days: int = 5,
        include_raw: bool = False,
    ):
        return self._execute(
            "mac_tick_charts",
            code=code,
            query_date=query_date,
            days=days,
            include_raw=include_raw,
        )

    def auction(
        self,
        code: str,
        *,
        start: int = 0,
        count: int = 500,
        include_raw: bool = False,
    ):
        return self._execute(
            "mac_auction", code=code, start=start, count=count, include_raw=include_raw
        )

    def market_monitor(
        self,
        market,
        *,
        start: int = 0,
        count: int = 600,
        include_raw: bool = False,
    ):
        return self._execute(
            "mac_market_monitor",
            market=market,
            start=start,
            count=count,
            include_raw=include_raw,
        )

    def kline_offset(self, *, offset: int = 0, count: int = 128000):
        return self._execute("mac_kline_offset", offset=offset, count=count)

    def file_list(self, filename: str, *, offset: int = 0):
        return self._execute("mac_file_list", filename=filename, offset=offset)

    def file_download(
        self,
        filename: str,
        *,
        index: int = 1,
        offset: int = 0,
        size: int = 30000,
    ):
        return self._execute(
            "mac_file_download", filename=filename, index=index, offset=offset, size=size
        )
