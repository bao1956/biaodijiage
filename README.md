# 每日投资标的价格

GitHub Actions 抓取股票、ETF 收盘价及开放式基金单位净值，经原有 Apps Script Web App 写入四个工作表。

股票/ETF 历史价每次用腾讯不复权日线短窗口校准最近 14 天，使用动态缓存参数；避免全历史接口缓存造成收盘后仍显示前一交易日。同一标的跨工作表复用同一份最新日线。北京时间 15 点前排除当日未收盘行情；基金继续使用原单位净值口径。

## 调度和维护

- 工作日北京时间 22:00、23:00、次日 00:00 调度，Google Sheet 按日期合并历史数据。
- 公开仓库连续 60 天无仓库活动时，GitHub 会停用 schedule，即使此前每日运行成功。
- 每次完整更新后保存 `update-status` 运行附件，保留 7 天；每隔至少 30 天把实际成功记录提交到 `.github/last-success.json`，记录各标的最新数据日期，不含价格或凭证，保持仓库活跃。
- 同一时间只允许一轮更新写表。抓取缺列时保留对应原表，其他表继续尝试；缺少 Webhook、HTTP 失败或 Web App 返回 `ok:false` 均使工作流失败。
- 运行失败先检查日志与各标的最新日期。基金净值可能晚于股票收盘价公布，QDII/FOF 尤其如此。
- 如 workflow 状态为 `disabled_inactivity`，用 `gh workflow enable daily.yml -R bao1956/biaodijiage` 恢复，再用 `gh workflow run daily.yml -R bao1956/biaodijiage` 补跑。补跑后仍须回读表格核验。

## 表格数字格式

Apps Script 每轮先清内容再重建；`clearContents()` 不会清除旧格式。数据增长覆盖此前的百分比统计行时，必须显式重设整个日期数据区的数字格式，再设置四个统计行。

2026-10-19 已修复 Web App：股票 `0.00`，ETF `0.000`，基金单位净值 `0.0000`；“买入标的”按场内 ETF 与基金分别处理。价差统计行 `0.0000`，回撤/涨幅统计行 `0.00%`。源代码改动后必须更新现有 Web App 的部署版本，才能让 Actions 调用生效。

本地检查：`python -m unittest discover -s tests -v`。
