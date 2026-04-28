import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import akshare as ak
import pandas as pd
import requests

WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")

ASSETS = [
    ("515220", "煤炭 ETF", "ETF"),
    ("159715", "稀土ETF", "ETF"),
    ("512000", "券商ETF", "ETF"),
    ("159865", "养殖ETF", "ETF"),
    ("513050", "中概互联", "ETF"),
    ("560710", "富国中证智选船舶产业ETF", "ETF"),
    ("159307", "博时中证红利低波100ETF", "ETF"),
    ("159758", "华夏中证红利质量ETF", "ETF"),
    ("159209", "招商中证全指红利质量ETF", "ETF"),
    ("563020", "易方达红利低波ETF", "ETF"),
    ("600519", "贵州茅台", "A股"),
    ("600036", "招商银行", "A股"),
    ("600900", "长江电力", "A股"),
    ("002714", "牧原股份", "A股"),
]

CODES = [x[0] for x in ASSETS]

FUND_CODES = [
    "110020", "005313", "160225", "163406", "161005",
    "270002", "015090", "014987", "110022", "161725",
    "012414", "012348", "513050", "520920", "515220",
    "159307",
]


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


def format_number(x):
    if pd.isna(x):
        return ""
    return f"{float(x):.4f}".rstrip("0").rstrip(".")


def format_date_for_output(dt_value):
    dt = pd.to_datetime(dt_value)
    return f"{dt.year}/{dt.month}/{dt.day}"


def get_latest_30_etf(code: str) -> pd.DataFrame:
    symbol = add_market_prefix(code)
    df = retry_call(ak.fund_etf_hist_sina, symbol=symbol, retries=3, sleep_seconds=2)

    if df.empty:
        raise ValueError("ETF 返回空数据")

    df = df.copy()
    date_col = "date" if "date" in df.columns else "日期"
    close_col = "close" if "close" in df.columns else "收盘"

    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df[close_col] = pd.to_numeric(df[close_col], errors="coerce")
    df = df.dropna(subset=[date_col, close_col]).sort_values(date_col).tail(30)

    return pd.DataFrame({
        "日期": df[date_col],
        "代码": code,
        "价格": df[close_col],
    })


def get_latest_30_stock(code: str) -> pd.DataFrame:
    symbol = add_market_prefix(code)
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=120)).strftime("%Y%m%d")

    df = retry_call(
        ak.stock_zh_a_hist_tx,
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        adjust="",
        retries=3,
        sleep_seconds=2,
    )

    if df.empty:
        raise ValueError("A股 返回空数据")

    df = df.copy()
    date_col = "日期" if "日期" in df.columns else "date"
    close_col = "收盘" if "收盘" in df.columns else "close"

    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df[close_col] = pd.to_numeric(df[close_col], errors="coerce")
    df = df.dropna(subset=[date_col, close_col]).sort_values(date_col).tail(30)

    return pd.DataFrame({
        "日期": df[date_col],
        "代码": code,
        "价格": df[close_col],
    })


def build_pivot(long_df: pd.DataFrame) -> pd.DataFrame:
    pivot_df = long_df.pivot_table(
        index="日期",
        columns="代码",
        values="价格",
        aggfunc="last",
    )
    for code in CODES:
        if code not in pivot_df.columns:
            pivot_df[code] = pd.NA
    return pivot_df[CODES].sort_index()


def build_wide_table(pivot_df: pd.DataFrame) -> str:
    header_row_1 = ["日期"] + [name for code, name, _ in ASSETS]
    header_row_2 = [""] + [code for code, name, _ in ASSETS]

    lines = [
        "\t".join(header_row_1),
        "\t".join(header_row_2),
    ]

    for dt, row in pivot_df.iterrows():
        line = [format_date_for_output(dt)]
        for code in CODES:
            line.append(format_number(row[code]))
        lines.append("\t".join(line))

    return "\n".join(lines)


def _fmt_price(v: float) -> str:
    return f"{float(v):.4f}".rstrip("0").rstrip(".")


def build_summaries_for(pivot_df: pd.DataFrame, codes, name_map, window_label="30交易日"):
    summaries = []
    for code in codes:
        if code not in pivot_df.columns:
            continue
        name = name_map.get(code, code)
        s = pivot_df[code].dropna()
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
            if ratio >= 0.66:
                position = "上沿"
            elif ratio <= 0.33:
                position = "下沿"
            else:
                position = "中段"

        last5 = s.tail(5).tolist()
        if len(last5) >= 2:
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
        else:
            trend = "数据不足"

        sentence = (
            f"近{window_label}累计 {change_pct:+.2f}%"
            f"（{_fmt_price(start_price)}→{_fmt_price(end_price)}），"
            f"近5日{trend}，最新价处于区间 "
            f"[{_fmt_price(low)}, {_fmt_price(high)}] 的{position}。"
        )
        summaries.append([f"{name} ({code})", sentence])
    return summaries


def build_summaries(pivot_df: pd.DataFrame):
    name_map = {code: name for code, name, _ in ASSETS}
    return build_summaries_for(pivot_df, CODES, name_map, window_label="30交易日")


def push_table_to_sheet(pivot_df, codes, name_map, sheet_name=None, window_label="30交易日"):
    if not WEBHOOK_URL:
        print(f"[Sheet 写入跳过] 未设置 WEBHOOK_URL 环境变量 (target={sheet_name or '主表'})")
        return

    header_row_1 = ["日期"] + [name_map.get(c, c) for c in codes]
    header_row_2 = [""] + list(codes)

    rows = []
    for dt, row in pivot_df.iterrows():
        out_row = [format_date_for_output(dt)]
        for code in codes:
            v = row[code] if code in pivot_df.columns else None
            if v is None or pd.isna(v):
                out_row.append("")
            else:
                out_row.append(round(float(v), 4))
        rows.append(out_row)

    summaries = build_summaries_for(pivot_df, codes, name_map, window_label=window_label)
    print(f"\n===== {sheet_name or '主表'} 趋势总结 =====")
    for label, sentence in summaries:
        print(f"{label}: {sentence}")

    payload = {
        "headers": [header_row_1, header_row_2],
        "rows": rows,
        "summaries": summaries,
    }
    if sheet_name:
        payload["sheetName"] = sheet_name

    resp = requests.post(
        WEBHOOK_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        timeout=60,
    )
    resp.raise_for_status()
    print(f"[Sheet 写入响应 {sheet_name or '主表'}] {resp.text}")


def push_to_google_sheet(pivot_df: pd.DataFrame) -> None:
    name_map = {code: name for code, name, _ in ASSETS}
    push_table_to_sheet(pivot_df, CODES, name_map, sheet_name=None, window_label="30交易日")


def get_fund_name_map():
    df = retry_call(ak.fund_name_em, retries=3, sleep_seconds=2)
    df = df.copy()
    df["基金代码"] = df["基金代码"].astype(str).str.zfill(6)
    return dict(zip(df["基金代码"], df["基金简称"]))


def get_fund_nav_history(code: str, days: int = 60) -> pd.DataFrame:
    df = retry_call(
        ak.fund_open_fund_info_em,
        symbol=code,
        indicator="单位净值走势",
        retries=3,
        sleep_seconds=2,
    )
    if df.empty:
        raise ValueError("基金 NAV 返回空数据")
    df = df.copy()
    df["净值日期"] = pd.to_datetime(df["净值日期"], errors="coerce")
    df["单位净值"] = pd.to_numeric(df["单位净值"], errors="coerce")
    df = df.dropna(subset=["净值日期", "单位净值"]).sort_values("净值日期").tail(days)
    return pd.DataFrame({
        "日期": df["净值日期"],
        "代码": code,
        "价格": df["单位净值"],
    })


def fetch_and_push_funds():
    print("\n===== 开始抓取基金净值 =====")
    try:
        name_map = get_fund_name_map()
    except Exception as e:
        print(f"[基金名称表获取失败，将使用代码作名称] {e}")
        name_map = {}

    fund_data = []
    for code in FUND_CODES:
        try:
            df = get_fund_nav_history(code, days=60)
            fund_data.append(df)
            print(f"[成功] {code} {name_map.get(code, '(未知)')} 抓取到 {len(df)} 条净值")
            time.sleep(0.8)
        except Exception as e:
            print(f"[失败] 基金 {code}: {e}")

    if not fund_data:
        print("所有基金都抓取失败")
        return

    long_df = pd.concat(fund_data, ignore_index=True)
    pivot_df = long_df.pivot_table(
        index="日期", columns="代码", values="价格", aggfunc="last"
    )
    for c in FUND_CODES:
        if c not in pivot_df.columns:
            pivot_df[c] = pd.NA
    pivot_df = pivot_df[FUND_CODES].sort_index()

    try:
        push_table_to_sheet(pivot_df, FUND_CODES, name_map, sheet_name="买入标的", window_label="60日")
    except Exception as e:
        print(f"[基金 Sheet 写入失败] {e}")


def main():
    all_data = []

    for code, name, asset_type in ASSETS:
        try:
            if asset_type == "ETF":
                df = get_latest_30_etf(code)
            else:
                df = get_latest_30_stock(code)

            all_data.append(df)
            print(f"[成功] {code} {name} 抓取到 {len(df)} 条数据")
            time.sleep(0.8)
        except Exception as e:
            print(f"[失败] {code} {name}: {e}")

    if not all_data:
        print("所有代码都抓取失败")
        return

    long_df = pd.concat(all_data, ignore_index=True)
    pivot_df = build_pivot(long_df)
    table_text = build_wide_table(pivot_df)

    print("\n===== 可直接复制到表格的软件内容 =====\n")
    print(table_text)

    desktop = Path.home() / "Desktop"
    output_file = (desktop if desktop.exists() else Path(".")) / "latest_30_trading_days_wide.tsv"
    with open(output_file, "w", encoding="utf-8-sig") as f:
        f.write(table_text)
    print(f"\n已保存到: {output_file}")

    try:
        push_to_google_sheet(pivot_df)
    except Exception as e:
        print(f"[Sheet 写入失败] {e}")

    try:
        fetch_and_push_funds()
    except Exception as e:
        print(f"[基金流程失败] {e}")


if __name__ == "__main__":
    print("AKShare 版本:", ak.__version__)
    main()
