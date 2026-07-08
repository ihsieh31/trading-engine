# Trading Engine — 專案目標與系統功能詳解

> 全自動美股交易系統 Paper Trading Only

---

## 一、全自動交易 Pipeline

| # | 目標 | 對應模組 | 狀態 |
|---|------|----------|------|
| 1 | **S&P 500 掃描** — 自動從 FMP/Wikipedia 取得成分股清單 | `universe.py` | ✅ |
| 2 | **技術指標篩選** — MA20/50、RSI、MACD、量比 5 項指標，純 pandas 計算，不下 LLM | `screener.py` | ✅ |
| 3 | **LLM 多 Agent 深度分析** — TradingAgents 框架，基本面 + 技術面 + 情緒面多 Agent 辯論，產出 BUY/HOLD/SELL 評級 | `deep_analyzer.py` | ✅ |
| 4 | **盤中價格監控** — 交易時段每 30 秒檢查持倉價格，觸發進出場邏輯 | `monitor.py` | ✅ |
| 5 | **自動下單** — 支援 Market Order、Bracket Order（止損 + 獲利同時掛單）、Partial Fill 處理、自動 Retry | `order_manager.py` | ✅ |
| 6 | **EOD 每日收盤報表** — 收盤後自動產生日報表（`recap_YYYY-MM-DD.json`） | `monitor.py._daily_recap()` | ✅ |
| 7 | **macOS launchd 開機自啟** — `scripts/setup_launchd.sh` 一鍵安裝守護行程 | `scripts/` | ✅ |

## 二、資金管理與風控

| # | 目標 | 對應模組 | 狀態 |
|---|------|----------|------|
| 8 | **Kelly Criterion 部位計算** — 根據勝率/平均盈虧計算最適部位，並以 Kelly Fraction 保守化（0.25） | `portfolio_manager.py` | ✅ |
| 9 | **產業曝險控管** — 11 大產業分類（238 檔），單一產業不得超過 MAX_SECTOR_PCT（25%） | `sector_map.py` + `portfolio_manager.py` | ✅ |
| 10 | **市場情境感知** — 根據 SPY 價格 vs MA50/MA200 判斷 bull/bear/ranging/high_vol，動態調整部位乘數（1.0/0.5/0.75/0.5） | `regime.py` | ✅ |
| 11 | **Circuit Breaker 自動熔斷** — 單日虧損 >3% 或 MDD >15% 自動熔斷，熔斷標記寫入 `.breaker` 檔持久化，重啟不消失 | `safety.py` | ✅ |
| 12 | **Kill Switch 緊急暫停** — `touch data/.kill` 立即停止所有交易行為 | `safety.py` + `monitor.py` | ✅ |
| 13 | **止損 -5% / 獲利 +15%** — 每筆進場自動掛 Bracket Order | `order_manager.py` | ✅ |
| 14 | **防重複下單** — `has_open_order` 快取 + buy cooldown 3600 秒 + 訂單簿去重 | `order_manager.py` + `monitor.py` | ✅ |
| 15 | **防重複啟動** — PID 檔案檢查 | `scheduler.py` | ✅ |
| 16 | **Rating Freshness 檢查** — 評級超過一定時效自動降權重，要求重新分析 | `portfolio_manager.py` | ✅ |
| 17 | **技術面進場確認** — 即使 LLM 評級 BUY，仍需技術指標確認（MA 趨勢、RSI 不超買）才進場 | `portfolio_manager.py._technical_confirms_entry()` | ✅ |
| 18 | **Gap & Tradability 檢查** — 開盤跳空太大或流動性不足時跳過 | `monitor.py._check_gap_and_tradability()` | ✅ |

## 三、監控與通知

| # | 目標 | 對應模組 | 狀態 |
|---|------|----------|------|
| 19 | **Telegram 通知** — 熔斷觸發、每日收盤報表、緊急事件自動發送 | `notifier.py` | ✅ |
| 20 | **Healthchecks.io 外部監控** — 定期 ping 確保系統活著，若 scheduler 停止會收到警報 | `health.py` | ✅ |
| 21 | **Web Dashboard** — Flask REST API + HTML 儀表板（port 8899），顯示持倉、現金、績效曲線、orders、ratings | `dashboard.py` + `dashboard.html` | ✅ |
| 22 | **績效追蹤** — Sharpe Ratio、Sortino Ratio、MDD、勝率、Profit Factor、權益曲線 | `performance.py` | ✅ |
| 23 | **日誌自動輪替** — 每支 log 10MB 自動輪替，保留 5 份 | 各模組 `RotatingFileHandler` | ✅ |
| 24 | **多 API Key 輪換 + 使用次數追蹤** — FMP 與 Tavily 皆支援多 Key 自動輪換 | `fmp_client.py` + `news_service.py` | ✅ |

## 四、交易日曆與排程

| # | 目標 | 對應模組 | 狀態 |
|---|------|----------|------|
| 25 | **NYSE 精確交易日曆** — 使用 `exchange_calendars` 精確判斷交易日、盤前/盤中/盤後時段 | `trading_calendar.py` | ✅ |
| 26 | **動態 Rebalancing** — 根據 ratings 變化與 regime 定期再平衡投資組合 | `portfolio_manager.py.rebalance_targets()` | ✅ |
| 27 | **Midweek Reanalysis** — 週中重新分析持有部位，根據新聞/評級變化決定是否減倉 | `scheduler.py._check_midweek_reanalysis()` | ✅ |
| 28 | **Priority Reanalysis** — 特定 ticker 因新聞/異常波動觸發優先重新分析 | `scheduler.py._check_priority_reanalysis()` | ✅ |
| 29 | **STAGE 排程架構** — 4 階段依序執行：STAGE 1 Screener → STAGE 2 Deep Analysis → STAGE 3 Monitor → STAGE 4 Offline Learning | `scheduler.py` | ✅ |

## 五、學習系統（V0.4.0 新增）

| # | 目標 | 對應模組 | 狀態 |
|---|------|----------|------|
| 30 | **Obsidian 知識庫** — 從 Obsidian vault 讀取 wikilink 格式的 markdown 交易筆記，透過 sentence-transformers 向量化存入 chromadb | `knowledge_base.py` | ✅ |
| 31 | **語意搜尋** — 根據文字查詢最相關的知識條目（top-k semantic search） | `knowledge_base.py.query()` | ✅ |
| 32 | **標籤過濾查詢** — 根據 tags 過濾知識條目 | `knowledge_base.py.query_by_tags()` | ✅ |
| 33 | **Wikilink 圖譜** — 解析 `[[...]]` 雙向鏈接，支援正向/反向查詢 | `knowledge_base.py.get_linked()` / `get_backlinks()` | ✅ |
| 34 | **交易規則儲存** — 從反思產生的交易規則存入獨立的 chromadb `trading_rules` collection | `knowledge_base.py.add_reflection()` / `query_rules()` | ✅ |
| 35 | **交易後反思** — 平倉時自動將該筆交易加入反思佇列，非交易時段由 LLM 分析盈虧原因，萃取交易規則 | `reflection_agent.py` | ✅ |
| 36 | **知識注入分析** — deep_analyzer 執行前自動查詢 KB 相關經驗與規則，注入 TradingAgents 新聞 context | `deep_analyzer.py._inject_knowledge_to_config()` | ✅ |
| 37 | **規則影響部位** — portfolio_manager 計算部位大小時查詢 KB 規則，根據規則內容調整乘數（0.0~1.5x） | `portfolio_manager.py._consult_knowledge_rules()` | ✅ |
| 38 | **離線學習循環** — STAGE 4：收盤後每 6 小時自動 sync vault + batch 處理反思佇列 | `scheduler.py._offline_learning_cycle()` | ✅ |
| 39 | **優雅降級** — 知識庫為空時所有功能正常運作，不拋錯 | 全部 KB 整合點 | ✅ |

## 六、券商抽象層

| # | 目標 | 對應模組 | 狀態 |
|---|------|----------|------|
| 40 | **PriceProvider 抽象** — 價格查詢介面，目前實作 Alpaca | `interfaces.py` + `adapters.py` | ✅ |
| 41 | **AccountProvider 抽象** — 帳戶資訊查詢介面 | `interfaces.py` + `adapters.py` | ✅ |
| 42 | **OrderExecutor 抽象** — 下單執行介面 | `interfaces.py` + `adapters.py` | ✅ |
| 43 | **TradeRecorder 抽象** — 交易記錄介面 | `interfaces.py` | ✅ |

## 七、尚未實作／待強化的目標

| # | 目標 | 說明 |
|---|------|------|
| 44 | **多券商支援** — 目前只有 Alpaca adapter，Future: IBKR, Tradier 等 | 抽象層已就緒，缺實作 |
| 45 | **知識庫內容填充** — `knowledge/` vault 為空，需使用者放入經濟學書籍、交易筆記 | 系統已就緒，等待內容 |
| 46 | **反思 LLM 端到端測試** — Reflection Agent 需要真實 trades.jsonl + Agnes API 才能完整測試 LLM 回饋迴圈 | 下單產生 trade record 後可驗證 |
| 47 | **Backtest 策略與實盤一致** — 目前 backtest 使用 MA20 金叉（與實盤 LLM 策略不同），回測參考價值有限 | 待改造 |
| 48 | **Dashboard 認證** — 目前 dashboard 無登入保護 | 可加 DASHBOARD_TOKEN |
| 49 | **更精細的止損邏輯** — 目前固定 -5%，未來可依波動率動態調整（ATR-based stop） | 待強化 |
| 50 | **再平衡時機優化** — 目前是固定週期 + midweek check，可改為 event-driven | 待強化 |

---

> 核心 pipeline（screener → LLM分析 → monitor → 下單 → 風控 → 學習）已完整閉環。
> 全系統 43 項目標已完成，7 項待強化。
