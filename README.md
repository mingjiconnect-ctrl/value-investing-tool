# S&P 500 Value/Growth Monitor MVP

这个项目是一个可复现的股票监控网站 MVP：用 Python 抓取 S&P 500 成分股、市场价格和 SEC EDGAR 财务数据，计算价值股与成长股的透明评分，然后由静态网页展示前十名。

## 数据原则

- 财务数据优先来自 SEC EDGAR `companyfacts` 和 SEC CIK 映射。
- S&P 500 成分股 MVP 使用 Wikipedia 成分股表作为免费可访问来源；生产版建议换成授权的指数成分/ETF 持仓数据。
- 市场价格 MVP 使用 Yahoo chart 单票接口；生产版建议换成授权行情源。
- 估值、评分、筛选全部由 Python 生成，不在前端伪造或临时计算投资结论。
- 如果关键数据缺失，公司会被标记为 `insufficient_data`，不会进入榜单。

## 快速运行

```bash
python scripts/run_pipeline.py --limit 40
python -m http.server 8000
```

然后打开：

```text
http://localhost:8000/web/
```

全量 S&P 500 运行：

```bash
python scripts/update_full.py
```

第一次全量运行会比较慢，因为需要逐家公司访问 SEC 与行情接口；后续会使用 `data/cache/` 缓存。

## 云端自动部署

GitHub Pages 部署使用 `.github/workflows/deploy-pages.yml`，每天按 UTC `21:30` 的美股交易日自动运行。工作流调用自包含脚本 `cloud_pages_monitor.py`，在 GitHub Actions 内生成完整 S&P 500 排名和 `dist/` 静态网站，然后发布到 GitHub Pages。

## SEC User-Agent

SEC 要求自动访问带上明确的 User-Agent。可以设置：

```bash
export SEC_USER_AGENT="sp500-monitor/0.1 your-email@example.com"
```

如果没有设置，MVP 会使用内置默认值，但正式使用建议改成你自己的联系信息。

## 当前评分框架

价值股排名：

```text
35% 加权公允价值折价
35% Buffett 质量/安全边际代理评分
20% 护城河代理评分
10% 数据完整度
```

成长股排名：

```text
25% 加权公允价值折价
40% Peter Lynch 成长合理性评分
30% Fisher 长期成长质量代理评分
 5% 数据完整度
```

价值榜和成长榜使用不同的风格准入门槛：

- 价值榜要求正向公允价值折价、足够的 Owner Earnings 收益率、Buffett 质量分和护城河代理分，并排除已满足成长风格的公司。
- 成长榜要求 3 年收入 CAGR、Lynch 分和 Fisher 分达到门槛，同时要求经营利润和自由现金流为正。
- 两张核心榜单在 MVP 中刻意保持风格互斥；同时满足价值和成长条件的公司，后续适合放入单独的“价值成长复合榜”。
- 多股权类别公司按发行人 CIK 去重，避免 `FOXA/FOX`、`GOOG/GOOGL` 这类重复占据榜单。
- 每股公允价值优先使用稀释加权平均股数；明显异常的 SEC 股数字段会被忽略。
- 金融、房地产、公用事业暂不进入通用 DCF 榜单，等后续加入行业专用估值模块。

加权公允价值：

```text
Base Case × 55% + Bull Case × 20% + Black Swan Case × 25%
```

这不是投资建议。它是一个可审计、可迭代的监控系统骨架。
