import json
import os
import time
from datetime import datetime, timedelta

import akshare as ak
import pandas as pd
import requests

WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")

# ETF/股票 历史回取起点（保留主表自该日起的完整历史）
PRICE_START_DATE = "2026-01-22"
# 基金单位净值窗口（交易日数）
FUND_WINDOW_DAYS = 60

# ===== tab 1：ETF =====
ETF_ASSETS = [
    ("515220", "煤炭 ETF"),
    ("159715", "稀土ETF"),
    ("512000", "券商ETF"),
    ("159865", "养殖ETF"),
    ("513050", "中概互联"),
    ("560710", "富国中证智选船舶产业ETF"),
    ("159307", "博时中证红利低波100ETF"),
    ("159758", "华夏中证红利质量ETF"),
    ("159209", "招商中证全指红利质量ETF"),
    ("563020", "易方达红利低波ETF"),
    ("159566", "储能电池ETF易方达"),
    ("159611", "电力ETF广发"),
]

# ===== tab 2：股票 =====
STOCK_ASSETS = [
    ("600519", "贵州茅台"),
    ("600036", "招商银行"),
    ("600900", "长江电力"),
    ("002714", "牧原股份"),
    ("603298", "杭叉集团"),
    ("600585", "海螺水泥"),
    ("000858", "五粮液"),
]

# ===== tab 3：基金（候选/新增，单位净值）=====
# 来源：候选池「雪球推荐」6 只主动/QDII 基金（只取 A 类）
NEW_FUND_ASSETS = [
    ("270023", "广发全球精选股票(QDII)人民币A"),
    ("100055", "富国全球科技互联网股票(QDII)A"),
    ("008261", "招商研究优选股票A"),
    ("519702", "交银施罗德趋势优先混合A"),
    ("011371", "华商远见价值混合A"),
    ("003501", "宏利睿智稳健灵活配置混合"),
]

# ===== tab 4：买入标的（已持有）=====
# 口径规则（全表通用，避免同一 ETF 在不同 sheet 价格不一致）：
#   场内 ETF -> 二级市场收盘价；开放式/联接基金 -> 单位净值
HELD_FUND_ASSETS = [
    ("110020", None), ("005313", None), ("160225", None), ("015090", None),
    ("014987", None), ("110022", None), ("161725", None), ("012414", None),
    ("012348", None),
    ("513050", None), ("520920", None), ("515220", None), ("159307", None),
    ("515180", None), ("159263", None), ("021457", None), ("023389", None),
]

# 场内 ETF：始终用二级市场收盘价（与「ETF」sheet 同源同口径，保证跨 sheet 一致）
ETF_MARKET_CODES = {
    "513050", "520920", "515220", "159307", "515180", "159263",
}


def add_market_prefix(code: str) -> str:
    code = str(code).zfill(6)
    if code.startswith(("5", "6")):
        return f"sh{code}"
    return f"sz{code}"


def retry_call(func, *args, retries=3, sleep_seconds=2, **kwargs):
    last_err = None
    for i in range(retries):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            last_err = e
            print(f"[重试 {i + 1}/{retries}] {func.__name__} 失败: {e}")
            if i < retries - 1:
                time.sleep(sleep_seconds * (i + 1))
    raise last_err


def format_date_for_output(dt_value):
    dt = pd.to_datetime(dt_value)
    return f"{dt.year}/{dt.month}/{dt.day}"


def _fmt_price(v: float) -> str:
    return f"{float(v):.4f}".rstrip("0").rstrip(".")


def get_etf_history(code: str) -> pd.DataFrame:
    symbol = add_market_prefix(code)
    df = retry_call(ak.fund_etf_hist_sina, symbol=symbol, retries=3, sleep_seconds=2)
    if df.empty:
        raise ValueError("ETF 返回空数据")
    df = df.copy()
    date_col = "date" if "date" in df.columns else "日期"
    close_col = "close" if "close" in df.columns else "收盘"
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df[close_col] = pd.to_numeric(df[close_col], errors="coerce")
    df = df.dropna(subset=[date_col, close_col]).sort_values(date_col)
    df = df[df[date_col] >= pd.to_datetime(PRICE_START_DATE)]
    return pd.DataFrame({"日期": df[date_col], "代码": code, "价格": df[close_col]})


def get_stock_history(code: str) -> pd.DataFrame:
    symbol = add_market_prefix(code)
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = PRICE_START_DATE.replace("-", "")
    df = retry_call(
        ak.stock_zh_a_hist_tx,
        symbol=symbol, start_date=start_date, end_date=end_date, adjust="",
        retries=3, sleep_seconds=2,
    )
    if df.empty:
        raise ValueError("A股 返回空数据")
    df = df.copy()
    date_col = "日期" if "日期" in df.columns else "date"
    close_col = "收盘" if "收盘" in df.columns else "close"
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df[close_col] = pd.to_numeric(df[close_col], errors="coerce")
    df = df.dropna(subset=[date_col, close_col]).sort_values(date_col)
    df = df[df[date_col] >= pd.to_datetime(PRICE_START_DATE)]
    return pd.DataFrame({"日期": df[date_col], "代码": code, "价格": df[close_col]})


def get_fund_nav_history(code: str, days: int = FUND_WINDOW_DAYS) -> pd.DataFrame:
    df = retry_call(
        ak.fund_open_fund_info_em, symbol=code, indicator="单位净值走势",
        retries=3, sleep_seconds=2,
    )
    if df.empty:
        raise ValueError("基金 NAV 返回空数据")
    df = df.copy()
    df["净值日期"] = pd.to_datetime(df["净值日期"], errors="coerce")
    df["单位净值"] = pd.to_numeric(df["单位净值"], errors="coerce")
    df = df.dropna(subset=["净值日期", "单位净值"]).sort_values("净值日期").tail(days)
    return pd.DataFrame({"日期": df["净值日期"], "代码": code, "价格": df["单位净值"]})


def get_fund_name_map():
    df = retry_call(ak.fund_name_em, retries=3, sleep_seconds=2)
    df = df.copy()
    df["基金代码"] = df["基金代码"].astype(str).str.zfill(6)
    return dict(zip(df["基金代码"], df["基金简称"]))


def build_pivot(long_df: pd.DataFrame, codes) -> pd.DataFrame:
    pivot_df = long_df.pivot_table(index="日期", columns="代码", values="价格", aggfunc="last")
    for code in codes:
        if code not in pivot_df.columns:
            pivot_df[code] = pd.NA
    return pivot_df[codes].sort_index()


def build_summaries_for(pivot_df, codes, name_map, window_n, window_label):
    summaries = []
    for code in codes:
        if code not in pivot_df.columns:
            continue
        name = name_map.get(code, code)
        s = pivot_df[code].dropna().tail(window_n)
        if len(s) < 2:
            summaries.append([f"{name} ({code})", "数据不足"])
            continue
        start_price = float(s.iloc[0])
        end_price = float(s.iloc[-1])
        change_pct = (end_price / start_price - 1) * 100
        low = float(s.min())
        high = float(s.max())
        if high == low:
            position = "持平"
        else:
            ratio = (end_price - low) / (high - low)
            position = "上沿" if ratio >= 0.66 else ("下沿" if ratio <= 0.33 else "中段")
        last5 = s.tail(5).tolist()
        pct_5 = (last5[-1] / last5[0] - 1) * 100
        diffs = [last5[i + 1] - last5[i] for i in range(len(last5) - 1)]
        mono_up = all(d >= 0 for d in diffs)
        mono_down = all(d <= 0 for d in diffs)
        if pct_5 > 1:
            trend = "持续上涨" if mono_up else "震荡上行"
        elif pct_5 < -1:
            trend = "持续下跌" if mono_down else "震荡下行"
        else:
            trend = "震荡"
        sentence = (
            f"近{window_label}累计 {change_pct:+.2f}%"
            f"（{_fmt_price(start_price)}→{_fmt_price(end_price)}），"
            f"近5日{trend}，最新价处于区间 "
            f"[{_fmt_price(low)}, {_fmt_price(high)}] 的{position}。"
        )
        summaries.append([f"{name} ({code})", sentence])
    return summaries


def push_table_to_sheet(pivot_df, codes, name_map, sheet_name, window_n, window_label,
                        date_header="日期", note=None):
    if not WEBHOOK_URL:
        print(f"[Sheet 写入跳过] 未设置 WEBHOOK_URL (target={sheet_name})")
        return
    header_row_1 = [date_header] + [name_map.get(c, c) for c in codes]
    header_row_2 = [""] + list(codes)
    rows = []
    for dt, row in pivot_df.iterrows():
        out_row = [format_date_for_output(dt)]
        for code in codes:
            v = row[code] if code in pivot_df.columns else None
            out_row.append("" if v is None or pd.isna(v) else round(float(v), 4))
        rows.append(out_row)
    summaries = build_summaries_for(pivot_df, codes, name_map, window_n, window_label)
    if note:
        summaries = [["口径说明", note]] + summaries
    print(f"\n===== {sheet_name} 趋势总结 =====")
    for label, sentence in summaries:
        print(f"{label}: {sentence}")
    payload = {
        "headers": [header_row_1, header_row_2],
        "rows": rows,
        "summaries": summaries,
        "sheetName": sheet_name,
    }
    resp = requests.post(
        WEBHOOK_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        timeout=60,
    )
    resp.raise_for_status()
    print(f"[Sheet 写入响应 {sheet_name}] {resp.text}")


def run_price_tab(assets, sheet_name, fetch_fn):
    print(f"\n===== 抓取 {sheet_name} ({len(assets)} 个) =====")
    codes = [c for c, _ in assets]
    name_map = {c: n for c, n in assets}
    data = []
    for code, name in assets:
        try:
            df = fetch_fn(code)
            data.append(df)
            print(f"[成功] {code} {name} {len(df)} 条")
            time.sleep(0.8)
        except Exception as e:
            print(f"[失败] {code} {name}: {e}")
    if not data:
        print(f"{sheet_name} 全部抓取失败，跳过")
        return
    pivot_df = build_pivot(pd.concat(data, ignore_index=True), codes)
    try:
        push_table_to_sheet(pivot_df, codes, name_map, sheet_name, window_n=30, window_label="30交易日")
    except Exception as e:
        print(f"[{sheet_name} 写入失败] {e}")


def run_fund_tab(assets, sheet_name, market_codes=None):
    market_codes = market_codes or set()
    mixed = bool(market_codes & {c for c, _ in assets})
    kind = "单位净值 + 场内ETF二级市场价" if mixed else "单位净值"
    print(f"\n===== 抓取 {sheet_name} ({len(assets)} 个，{kind}) =====")
    codes = [c for c, _ in assets]
    try:
        em_names = get_fund_name_map()
    except Exception as e:
        print(f"[基金名称表获取失败] {e}")
        em_names = {}
    name_map = {}
    for c, n in assets:
        name_map[c] = n or em_names.get(c, c)
    data = []
    for code in codes:
        try:
            if code in market_codes:
                df = get_etf_history(code)  # 场内 ETF：二级市场收盘价
            else:
                df = get_fund_nav_history(code, days=FUND_WINDOW_DAYS)  # 基金：单位净值
            data.append(df)
            print(f"[成功] {code} {name_map.get(code)} {len(df)} 条")
            time.sleep(0.8)
        except Exception as e:
            print(f"[失败] {code} {name_map.get(code)}: {e}")
    if not data:
        print(f"{sheet_name} 全部抓取失败，跳过")
        return
    pivot_df = build_pivot(pd.concat(data, ignore_index=True), codes)
    used_etf = sorted(market_codes & set(codes))
    if mixed:
        date_header = "日期"
        note = ("本表口径：开放式/联接基金=单位净值；场内ETF（"
                + "、".join(used_etf) + "）=二级市场收盘价")
    else:
        date_header = "日期（单位净值）"
        note = "本表基金价格口径为单位净值（非累计净值）"
    try:
        push_table_to_sheet(
            pivot_df, codes, name_map, sheet_name,
            window_n=FUND_WINDOW_DAYS, window_label="60日",
            date_header=date_header, note=note,
        )
    except Exception as e:
        print(f"[{sheet_name} 写入失败] {e}")


def main():
    run_price_tab(ETF_ASSETS, "ETF", get_etf_history)
    run_price_tab(STOCK_ASSETS, "股票", get_stock_history)
    run_fund_tab(NEW_FUND_ASSETS, "基金")
    run_fund_tab(HELD_FUND_ASSETS, "买入标的", market_codes=ETF_MARKET_CODES)


if __name__ == "__main__":
    print("AKShare 版本:", ak.__version__)
    main()
