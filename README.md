# Trading Engine — 全自動美股交易系統 <br><sub>v0.3.0</sub>

> **🇬🇧 English Version**: [github.com/ihsieh31/trading-engine-english-version-](https://github.com/ihsieh31/trading-engine-english-version-)  
> **中文版**：本倉庫 — [github.com/ihsieh31/trading-engine](https://github.com/ihsieh31/trading-engine)

基於 **技術指標篩選 → LLM 多 Agent 深度分析 → 多 Agent 風控與決策 → 盤中監控 → 自動下單 → 交易後反思學習** 的全自動 S&P 500 交易系統，搭載事件驅動架構、Plugin 外掛系統、MCP AI 整合介面與內建交易知識庫。

> **Paper Trading Only** — 使用 Alpaca Paper Trading API，100% 模擬資金，無真實風險。

> **安裝**：首次執行 `./run.sh` 可選中文/英文，依序引導填入 API Key（支援 OpenAI 格式之 LLM、Alpaca、新聞 API），自動安裝依賴並執行健康檢查。

---

## 系統架構

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        scheduler.py（守護行程主控）                          │
│  排程 4 階段依序執行 + EventBus 事件驅動                                    │
│                                                                          │
│  STAGE 1 ── screener.py        技術指標篩選（不下 LLM）                     │
│                │                                                         │
│                ├── universe.py          S&P 500 / NASDAQ 100 成分股       │
│                └── trading_calendar.py  NYSE 交易日曆                      │
│                                                                          │
│  STAGE 2 ── deep_analyzer.py    LLM 多 Agent 深度分析                     │
│                │                                                         │
│                ├── agents/             AnalystAgent（LLM 基本面/技術面分析）│
│                │                       ScreenerAgent（量化篩選）           │
│                ├── news_service.py     多供應商新聞                       │
│                ├── economics_kb.py     經濟學知識注入（1,457 來源）        │
│                └── knowledge_base.py   交易經驗/規則注入                   │
│                                                                          │
│  STAGE 3 ── monitor.py          盤中監控引擎（每 30 秒）                  │
│                │                                                         │
│                ├── container.py       DI 容器：注入所有相依                │
│                ├── agents/             RiskAgent（風控）                  │
│                │                       ChairmanAgent（聚合決策）           │
│                │                       ExecutionAgent（執行下單）          │
│                ├── portfolio_manager   資金管理 + 產業控管                 │
│                ├── order_manager       訂單生命週期                       │
│                ├── performance         績效追蹤                           │
│                ├── safety              熔斷保護                           │
│                └── strategy            止損/停利策略                      │
│                                                                          │
│  STAGE 4 ── reflection_agent.py 交易反思 + 規則萃取                       │
│                └── knowledge_base.py   chromadb 向量儲存                  │
│                                                                          │
│    dashboard.py（可選）— Web 監控面板（Flask, port 8899）                  │
│    mcp_server.py（可選）— MCP AI 整合伺服器（14 個工具）                  │
│    plugin_host.py（可選）— Plugin 動態載入系統                            │
└──────────────────────────────────────────────────────────────────────────┘
```

### Pipeline 流程

```
每週一盤前
  Universe (S&P 500)
    │
    ▼ STAGE 1
  Screener (MA20/50, RSI, MACD, 量比 → TOP 15)
    │
    ▼ STAGE 2
  Deep Analyzer (TradingAgents + 多 Agent → AgentProposal)
    │  └─ 注入經濟學知識 + 交易經驗 + 歷史規則
    │
    ▼ STAGE 3（每 30 秒，交易時段）
  Monitor (價格監控 → 風控檢查 → 主席決策聚合 → 自動下單)
    │
    ├── 進場條件：ChairmanAgent 決策 BUY + RiskAgent 核准 + 技術面確認
    ├── 出場條件：止損 -5% / 獲利 +15% / LLM 轉 SELL / 熔斷
    └── 熔斷條件：單日虧損 >3% 或 MDD >15%
    │
    ▼ 收盤後（STAGE 4）
  Reflection (分析平倉交易 → 萃取交易規則 → 存入知識庫)
```

---

## V2 多 Agent 架構

本專案在原有 V1 Pipeline 之上，新增了一套完整的多 Agent 協作架構：

```
  AnalystAgent ──┐
  ScreenerAgent ──┤
  ExecutionAgent ─┤
  (Plugin) ───────┤
                  │  AgentProposals
                  ▼
            RiskAgent ──── RiskAssessment
                  │
                  ▼
           ChairmanAgent ──── ChairmanDecision
                  │
                  ▼
           ExecutionAgent ──── Order Execution
                  │
                  ▼
           EventBus ──── 事件持久化 + WorkflowEngine 狀態推進
```

### Agent 說明

| Agent | 職責 | 輸入 | 輸出 |
|-------|------|------|------|
| **AnalystAgent** | LLM 基本面 + 技術面 + 情緒面分析 | `AnalysisContext`（技術指標、新聞、經濟知識） | `AgentProposal`（rating, confidence, price_target） |
| **ScreenerAgent** | 量化篩選（不下 LLM） | `PortfolioState` | `AgentProposal`（score >= 3 則 BUY） |
| **ExecutionAgent** | 執行下單 + 重試邏輯 | `ChairmanDecision` | — |
| **RiskAgent** | 風控：Regime 閘門、Kelly 部位、產業曝險、總曝險上限 | 市場資料 + 投資組合 | `RiskAssessment`（approved, position_pct, veto_reason） |
| **ChairmanAgent** | 聚合決策：加權投票 → 規則覆寫 → 風險否決 → LLM 仲裁（選） | Proposals + RiskAssessment | `ChairmanDecision`（final_action, position_pct, vote_breakdown） |

### ChairmanAgent 四步驟演算法

1. **信心校準**：根據 DB 滾動準確率調整各 Agent 權重
2. **加權投票**：weight = calibrated_confidence，求加權多數決
3. **規則覆寫**：查詢 MemoryService 中有無高信心規則覆寫
4. **風險否決**：RiskAgent 的 veto_reason 非 None 時強制 HOLD
5. **LLM 仲裁**（選）：若加權多數 <60%，由 LLM 仲裁

---

## 事件驅動架構（EventBus V2）

系統全面採用事件驅動設計，所有模組透過 `EventBus` 鬆耦合溝通。

| 事件類型 | 觸發時機 | 事件 Payload |
|---------|---------|-------------|
| `screener.candidates_ready` | 技術篩選完成 | `{count, tickers[]}` |
| `analyst.proposal_created` | 單一股分析完成 | `{ticker, rating, confidence}` |
| `analyst.batch_completed` | 整批分析完成 | `{count}` |
| `risk.assessment_created` | 風控評估完成 | `{ticker, approved}` |
| `chairman.decision_made` | 主席決策完成 | `{ticker, action}` |
| `order.submitted` | 訂單提交 | `{ticker, qty, order_id}` |
| `order.filled` | 訂單成交 | `{ticker, qty, price}` |
| `order.failed` | 訂單失敗 | `{ticker, error}` |
| `circuit_breaker.tripped` | 熔斷觸發 | `{reason}` |
| `position.closed` | 部位平倉 | `{ticker, pnl}` |
| `reflection.completed` | 反思完成 | `{rule_id}` |
| `memory.rule_added` | 新交易規則寫入 | `{rule_id}` |
| `memory.rule_conflict_detected` | 規則衝突 | `{existing_rule, new_rule}` |
| `workflow.state_changed` | 工作流狀態轉移 | `{from_state, to_state}` |
| `system.health_degraded` | 系統健康度下降 | `{metric, value}` |

所有事件皆持久化至 SQLite，支援按 `trace_id` / `workflow_id` 查詢稽核軌跡。

---

## Plugin 外掛系統

支援動態載入第三方 Plugin，透過 `plugin.json` manifest 宣告能力：

```json
{
  "id": "my_provider",
  "name": "My Custom News Provider",
  "version": "1.0.0",
  "entrypoint": "plugin.py:MyPlugin",
  "interfaces_implemented": ["INewsProvider"]
}
```

| 介面 | 說明 |
|------|------|
| `INewsProvider` | 新聞資料來源（search/search_market_news） |
| `INewsProviderPlugin` | Plugin 形式的新聞資料來源 |
| `IStrategyPlugin` | 自訂交易策略（evaluate） |

---

## MCP AI 整合（Model Context Protocol）

`mcp_server.py` 透過 stdio JSON-RPC 2.0 提供 14 個工具供 AI 助理（Claude 等）直接查詢系統狀態：

| 工具 | 說明 |
|------|------|
| `get_account` | 帳戶資訊（現金、權益、購買力） |
| `get_positions` | 目前持倉（數量、均價、未實現損益） |
| `get_regime` | 市場情境（bull/bear/ranging/high_vol） |
| `get_ratings` | LLM 評級列表 |
| `portfolio_stats` | 投資組合統計（Sharpe, MDD, 勝率） |
| `recent_trades` | 近期交易記錄 |
| `knowledge_stats` | 知識庫統計 |
| `query_rules` | 查詢交易規則 |
| `get_knowledge` | 語意搜尋知識庫 |
| `get_config` | 系統設定（隱藏敏感欄位） |
| `get_workflow_status` | 工作流狀態清單 |
| `get_decision_trail` | 決策軌跡（按 trace_id 或 ticker） |
| `get_agent_accuracy` | Agent 準確率統計 |

---

## 環境需求

- **OS**: macOS 或 Linux（Windows 未測試）
- **Python**: 3.11+
- **帳戶**: [Alpaca Paper Trading](https://alpaca.markets)（免費）
- **LLM API**: [Agnes AI](https://agnes-ai.com) 或任何 OpenAI-compatible API
- **新聞 API**: Tavily / Brave / SerpAPI（任一即可）

### 安裝

```bash
git clone https://github.com/ihsieh31/trading-engine.git ~/trading_engine
cd ~/trading_engine
./run.sh
```

首次執行 `./run.sh` 會啟動設定選單：

1. 選擇語言（中文 / English）
2. 輸入 LLM API Key、API Endpoint、模型 ID（相容任何 OpenAI-format）
3. 輸入 Alpaca API Key + Secret（免費 Paper Trading）
4. 輸入新聞 API Key（Tavily / Brave / SerpAPI，可選）
5. 輸入 Telegram Token + Chat ID（可選）

設定完成後自動安裝依賴、執行健康檢查，進入主選單。

若需重新設定：選單選 **5) Setup / Reconfigure** 或手動編輯 `.env`。

---

## 設定 (.env)

### 券商連線（必要）

| 參數 | 預設 | 說明 |
|------|------|------|
| `ALPACA_API_KEY` | — | Alpaca Paper Trading API Key |
| `ALPACA_API_SECRET` | — | Alpaca Paper Trading API Secret |
| `IS_PAPER` | `true` | 模擬交易開關（預設 paper，改 false 為實盤） |

### LLM（必要）

相容任何 OpenAI-format 的 LLM API（OpenAI、Anthropic、Groq、DeepSeek、Google AI、OpenRouter 等）。

| 參數 | 預設 | 說明 |
|------|------|------|
| `OPENAI_COMPATIBLE_API_KEY` | — | API Key |
| `LLM_BACKEND_URL` | — | API 端點，例如 `https://api.openai.com/v1` |
| `DEEP_THINK_MODEL` | `gpt-4o` | 深度分析模型 id |
| `QUICK_THINK_MODEL` | `gpt-4o-mini` | 快速分析模型 id |

### 新聞服務（至少一個）

| 參數 | 預設 | 說明 |
|------|------|------|
| `TAVILY_API_KEYS` | — | 逗號分隔，多 Key 自動輪換 |
| `BRAVE_API_KEYS` | — | 逗號分隔 |
| `SERPAPI_API_KEYS` | — | 逗號分隔 |
| `FMP_API_KEYS` | — | Financial Modeling Prep（可選，用於價格/新聞備援） |

### 篩選與排程

| 參數 | 預設 | 說明 |
|------|------|------|
| `UNIVERSE_SOURCE` | `sp500` | `sp500` 或 `nasdaq100` |
| `SCREENER_TOP_N` | `15` | 技術指標篩選取前 N 名 |
| `SCREENER_WORKERS` | `10` | 篩選並行數 |
| `MONITOR_INTERVAL_SECONDS` | `30` | 盤中價格檢查頻率 |
| `BUY_COOLDOWN_SECONDS` | `3600` | 賣出後冷卻時間（秒） |

### 資金管理與風控

| 參數 | 預設 | 說明 |
|------|------|------|
| `INITIAL_CAPITAL` | `100000` | 初始模擬資金 |
| `MAX_POSITION_PCT` | `0.10` | 單一部位上限（10%） |
| `MAX_TOTAL_EXPOSURE` | `0.50` | 總曝險上限（50%） |
| `MAX_SECTOR_PCT` | `0.25` | 單一產業曝險上限（25%） |
| `STOP_LOSS_PCT` | `0.05` | 止損 -5% |
| `TAKE_PROFIT_PCT` | `0.15` | 獲利 +15% |
| `KELLY_FRACTION` | `0.25` | Kelly 保守比率 |
| `MIN_POSITION_PCT` | `0.02` | 最小部位比例（2%） |
| `MAX_DAILY_LOSS_PCT` | `0.03` | 每日虧損 >3% 自動熔斷 |
| `MAX_DRAWDOWN_PCT` | `0.15` | 回撤 >15% 自動熔斷 |
| `GAP_ALERT_PCT` | `0.08` | 跳空幅度警報 |

### 訂單管理

| 參數 | 預設 | 說明 |
|------|------|------|
| `ORDER_MAX_RETRIES` | `3` | 未成交訂單最大重試次數 |
| `ORDER_RETRY_DELAY_SEC` | `10` | 重試間隔（秒） |
| `ORDER_FILL_TIMEOUT_SEC` | `300` | 訂單超時（秒） |

### Dashboard

| 參數 | 預設 | 說明 |
|------|------|------|
| `DASHBOARD_PORT` | `8899` | Web 面板連接埠 |
| `DASHBOARD_TOKEN` | — | 選填，設定後需帶入 Header 才可存取 |

### 通知

| 參數 | 預設 | 說明 |
|------|------|------|
| `HEALTHCHECK_URL` | — | healthchecks.io ping URL |
| `TELEGRAM_BOT_TOKEN` | — | Telegram Bot Token |
| `TELEGRAM_CHAT_ID` | — | Telegram 聊天室 ID |

### 知識庫

| 參數 | 預設 | 說明 |
|------|------|------|
| `OBSIDIAN_VAULT_PATH` | `./knowledge` | Obsidian vault 路徑。指向 `知識庫/` 目錄，系統啟動時自動掃描並建立 chromadb 索引。若目錄不存在則略過。 |
| `DATA_DIR` | `./data` | 資料與日誌儲存目錄 |

---

## 模組說明

### 核心 Pipeline

| 模組 | 說明 |
|------|------|
| `scheduler.py` | 守護行程主控。依序執行 STAGE 1-4 整條 pipeline：技術篩選 → LLM 分析 → 盤中監控 → 離線學習。使用 PID 檔案防止重複啟動。 |
| `screener.py` | 技術指標篩選器。用 yfinance 計算 MA20/50、RSI、MACD、量比共 5 項指標，從 universe 篩出 TOP N 標的。純 pandas 計算，不下 LLM。 |
| `deep_analyzer.py` | LLM 多 Agent 深度分析。使用 TradingAgents 框架對篩選結果進行基本面 + 技術面 + 情緒面多 Agent 辯論，產生 BUY/HOLD/SELL 評級及進場價格。分析前自動注入經濟學知識庫、交易經驗與歷史規則。 |
| `monitor.py` | 盤中監控引擎。交易時段內每 N 秒檢查持倉價格，自動觸發風控檢查、主席決策聚合、止損/獲利出場、新標的進場、熔斷檢查。 |
| `portfolio_manager.py` | 資金管理模組。Kelly Criterion 計算最適部位規模、投資組合再平衡、產業曝險控管、知識規則查詢調整部位乘數、技術面進場確認。 |
| `order_manager.py` | 訂單生命週期管理。提交確認、Partial Fill 處理、自動 Retry（最多 3 次）、Cancel-Replace、Bracket Order、EOD 清理。雙寫入 SQLite + JSONL。 |
| `performance.py` | 績效追蹤。計算 Sharpe Ratio、Sortino Ratio、Max Drawdown、勝率、Profit Factor、加權平均成本（WAC），每日自動快照。 |
| `regime.py` | 市場情境偵測。根據 SPY 價格 vs MA50/MA200 及 ATR 百分位判斷 bull / bear / ranging / high_vol，動態調整部位乘數。 |
| `safety.py` | 自動熔斷保護。單日虧損 >3% 且未實現損益為正時不熔斷（防誤判）；MDD >15% 強制熔斷。熔斷標記寫入 `.breaker` 檔。 |
| `strategy.py` | 策略層。`RatingStrategy`（基於 LLM 評級）、`StopLossTakeProfitStrategy`（OCO bracket）、`CompositeStrategy`（組合多策略）。 |
| `container.py` | DI 容器。所有模組在此單例註冊，避免重複建立 TradingClient。PriceMonitor / Scheduler / Dashboard 皆透過 container 取得相依。 |

### V2 多 Agent 系統

| 模組 | 說明 |
|------|------|
| `agents/base.py` | Agent 基底類別。`AnalystAgent`（LLM 金融分析）、`ScreenerAgent`（量化篩選）、`ExecutionAgent`（下單執行）、`ReflectionAgent`（交易反思）。 |
| `agents/risk_agent.py` | 風控 Agent。Regime 閘門、Kelly 部位計算、產業曝險限制、總曝險上限，輸出 `RiskAssessment`。 |
| `agents/chairman_agent.py` | 主席 Agent。加權投票聚合多 Agent 提案，信心校準、規則覆寫、風險否決、LLM 仲裁，輸出 `ChairmanDecision`。 |
| `core/workflow_engine.py` | 工作流引擎。12 種狀態的狀態機，事件驅動狀態轉移，支援 resume / circuit_breaker / retry。 |
| `memory/memory_service.py` | 記憶服務。三層記憶：working（記憶體）、episodic（交易歷史）、semantic（向量知識庫）。支援 decay、conflict detection、graph expansion。 |
| `event_bus.py` | 事件匯流排。Singleton pub/sub + SQLite 持久化。所有事件含 event_id / trace_id / workflow_id，支援稽核追溯。 |
| `interfaces_v2.py` | V2 抽象介面定義。`IAgent`、`IRiskAgent`、`IChairmanAgent`、`IWorkflowEngine`、`IMemoryService`、`IPlugin`、`INewsProvider`。 |
| `plugin_host.py` | Plugin 外掛系統。依 `plugin.json` 自動探索，動態載入，介面驗證，生命週期管理。 |
| `mcp_server.py` | MCP 伺服器。14 個工具透過 JSON-RPC 2.0 提供系統狀態查詢，供 AI 助理整合。 |

### 券商抽象層

| 模組 | 說明 |
|------|------|
| `interfaces.py` | V1 抽象介面：`IPriceProvider`、`IAccountProvider`、`IOrderExecutor`、`ITradeRecorder`。 |
| `adapters.py` | Alpaca 實作。價格查詢 3 層備援（Alpaca → FMP → yfinance），帳戶查詢與下單皆封裝 Alpaca REST API。 |

### 資料源

| 模組 | 說明 |
|------|------|
| `universe.py` | 股票宇宙定義。自動從 FMP/Wikipedia 取得 S&P 500 或 NASDAQ-100 成分股，內建靜態備援清單。 |
| `news_service.py` | 多供應商新聞服務。支援 Tavily / Brave / SerpAPI / FMP，多 API Key 自動輪換 + 使用次數追蹤。 |
| `fmp_client.py` | Financial Modeling Prep API 客戶端。多 Key 輪換、Rate Limit 退避、用量統計。 |
| `trading_calendar.py` | 美股交易日曆。使用 `exchange_calendars` 精確判斷 NYSE 交易日、盤前/盤中/盤後時段。 |
| `sector_map.py` | S&P 500 產業分類對應表（238 檔分類至 11 大產業），支援 FMP/yfinance 動態查詢。 |

### 學習系統

| 模組 | 說明 |
|------|------|
| `reflection_agent.py` | 交易後反思引擎。平倉時自動加入反思佇列，非交易時段由 LLM 分析盈虧原因，萃取交易規則。 |
| `knowledge_base.py` | Obsidian vault 知識庫 + chromadb 向量儲存。支援 wikilink 雙向鏈接圖譜、語意搜尋、標籤過濾。 |
| `economics_kb.py` | 經濟學知識庫載入器。從 `economics-knowledge.yaml`（1,457 個來源、100+ 經典著作）載入，按 regime + 產業篩選相關知識。 |

### 監控與通知

| 模組 | 說明 |
|------|------|
| `dashboard.py` | Web 監控面板。Flask REST API（8 個端點）+ HTML 前端，顯示持倉、現金、績效曲線、orders、ratings。 |
| `notifier.py` | Telegram 通知。熔斷觸發、每日收盤報表、緊急事件自動發送。 |
| `health.py` | 外部監控 ping。定期發送 HTTP GET 到 healthchecks.io。 |

### 工具

| 模組 | 說明 |
|------|------|
| `backtest.py` | 歷史回測。使用 yfinance 歷史數據與可插拔策略。**回測策略與實盤不同，僅供參考。** |
| `file_utils.py` | 原子檔案 I/O 工具。`atomic_write_json`、`atomic_write_text`、`read_json`。 |
| `db.py` | SQLite 持久層。WAL 模式 + thread-local 連線，儲存 orders / trades / ratings / 績效 / 事件 / 工作流 / Agent 信心。 |

---

## 使用方式

### 啟動系統

```bash
cd ~/trading_engine
source .venv/bin/activate

# 全自動排程（推薦）
python scheduler.py

# 或分開啟動監控面板（選配）
python dashboard.py

# 或啟動 MCP 伺服器（供 AI 助理整合）
python mcp_server.py
```

### 一鍵腳本

```bash
./run.sh    # 自動安裝 + 選單模式：回測 / 分析 / 監控 / 面板
```

### 監控面板

開啟瀏覽器：`http://localhost:8899`

面板功能：
- **系統狀態** — 守護行程狀態、運作時間、監控行程 PID
- **市場情境** — 目前 bull/bear/ranging/high_vol，含 SPY 價格 vs MA50/MA200
- **帳戶總覽** — 現金、權益、未實現損益、產業曝險分布
- **評級列表** — LLM 最新 BUY/HOLD/SELL 評級與價格目標
- **訂單記錄** — 歷史訂單時間軸
- **成交明細** — 逐筆交易記錄
- **績效曲線** — 權益曲線、Sharpe、Sortino、MDD、勝率
- **分析佇列** — 深度分析進度（pending / completed）

### Dashboard API 端點

| 端點 | 說明 |
|------|------|
| `GET /api/status` | 系統狀態（state、pid、uptime） |
| `GET /api/regime` | 市場情境（regime、SPY MA 位置、ATR 百分位） |
| `GET /api/account` | 帳戶資訊（現金、權益、未實現損益、產業分布、持倉） |
| `GET /api/ratings` | LLM 評級列表（含 analyze_at 時效） |
| `GET /api/orders` | 歷史訂單 |
| `GET /api/trades` | 成交明細 |
| `GET /api/performance` | 績效指標（Sharpe、Sortino、MDD、勝率、Profit Factor） |
| `GET /api/analysis-queue` | 深度分析佇列狀態 |

### 開機自啟（macOS launchd）

```bash
# 一鍵安裝（自動替換路徑、載入 launchd）
./scripts/setup_launchd.sh

# 手動控制
launchctl stop com.tradingengine.scheduler
launchctl start com.tradingengine.scheduler
launchctl unload ~/Library/LaunchAgents/com.tradingengine.scheduler.plist
```

### 回測

```bash
source .venv/bin/activate
python backtest.py
```

---

## 安全機制

| 機制 | 說明 |
|------|------|
| **Circuit Breaker 熔斷** | 單日虧損 >3% **且** 未實現損益為正時不熔斷（防誤判）；MDD >15% 時強制熔斷。熔斷標記寫入 `data/.breaker`，重啟不消失。 |
| **Kill Switch 緊急暫停** | `touch data/.kill` 立即停止所有交易行為。刪除 `.kill` 恢復。 |
| **防重複啟動** | PID 檔案檢查，防止多個 scheduler 同時執行。 |
| **重複下單防護** | `has_open_order` 快取 + buy cooldown（預設 3600 秒）+ 訂單簿去重。 |
| **產業曝險控管** | 單一產業部位總和不得超過 `MAX_SECTOR_PCT`（預設 25%），由 RiskAgent 執行。 |
| **Stop-Loss / Take-Profit** | 每檔股票自動掛 OCO bracket order（止損 -5% / 獲利 +15%）。加碼時自動重建保護單。 |
| **Partial Fill 處理** | 未完全成交的訂單自動進入 retry 循環，最多 3 次。 |
| **Rating Freshness** | 評級超過 7 天自動降權重，要求重新分析。 |
| **技術面進場確認** | 即使 LLM 評級 BUY，仍需 MA 趨勢向上 + RSI 不超買才進場。 |
| **Gap & Tradability** | 開盤跳空 >8% 或盤中流動性不足時跳過該標的。 |
| **Agent 信心校準** | ChairmanAgent 根據歷史準確率動態調整各 Agent 投票權重。 |
| **風險否決權** | RiskAgent 可基於 Regime / 曝險 / Kelly 結果一票否決任何交易。 |
| **外部監控** | Healthchecks.io 定期 ping，scheduler 停止時即時警報。 |

### 緊急操作速查

```bash
# 檢查系統狀態
tail -f data/scheduler.log

# 緊急停止交易（不需重啟程式）
touch data/.kill

# 還原 kill switch
rm data/.kill

# 熔斷後恢復交易（確認風險可控後）
rm data/.breaker
```

---

## 學習系統

### 交易後反思（Reflection Agent）

每筆平倉交易（止損/停利）自動加入反思佇列。非交易時段（STAGE 4），LLM 分析：
- 交易為何虧損/獲利（Outcome Analysis）
- 學到什麼教訓（Lesson Extracted）
- 萃取成可重複使用的交易規則（Trading Rule）
- 規則存入 chromadb `trading_rules` collection

### 記憶服務（MemoryService）

三層記憶架構，支援交易規則的生命週期管理：

| 層級 | 儲存位置 | 用途 | 特性 |
|------|---------|------|------|
| **Working** | 記憶體 dict | 當前工作流程上下文 | 依 workflow_id，階段結束即清除 |
| **Episodic** | SQLite trades table | 歷史交易記錄 | 查詢過往盈虧模式 |
| **Semantic** | chromadb + SQLite rules | 向量化知識 + 交易規則 | 語意搜尋、decay 衰減、關聯圖譜 |

- `decay_score`：未 reinforce 的規則隨時間指數衰減（lambda = 0.01）
- `detect_conflict`：新規則與既有規則標籤重疊時告警
- `expand_graph`：透過 wikilink 雙向鏈接展開關聯規則
- `reinforce`：規則被驗證正確時增加信心值

### 知識庫（Knowledge Base）

系統內建 Obsidian vault 格式的 markdown 交易知識庫，供 LLM 分析時注入相關交易經驗與規則。

#### 資料來源（vault 現有 60 個 `.md` 檔）

| 來源 | 數量 | 說明 |
|------|------|------|
| **Project Gutenberg 經典** | 48 本 | 經濟學與金融經典（李嘉圖、米爾、凱因斯等），純文字版，已移除版權宣告與前言 |
| **交易指南** | 4 本 | `trading_rules_cheatsheet.md`、`options_trading_guide.md`、`learning_path.md`、`sec_edgar_guide.md` |
| **經典交易書籍精華** | 8 本 | Wyckoff、Gann、Loeb、Thorp、Hamilton、Nelson、NYSE 歷史 — 濃縮為核心規則與原則 |

#### 使用方式

1. **設定 vault 路徑**：在 `.env` 中指定 `OBSIDIAN_VAULT_PATH`（預設 `./knowledge`）
2. **自動載入**：`knowledge_base.py` 啟動時自動掃描目錄，解析 wikilink 雙向鏈接，sentence-transformers 向量化後存入 chromadb
3. **查詢注入**：`deep_analyzer.py` 與 `portfolio_manager.py` 自動查詢相關知識並注入 LLM prompt

vault 已內建於 repo 的 `knowledge/` 目錄，clone 後即可使用。若想使用自己的 Obsidian vault，將 `.env` 中的 `OBSIDIAN_VAULT_PATH` 指向你的 vault 路徑即可。

#### 重新下載 / 重建知識庫

```bash
# 從 Archive.org 下載 8 本經典交易書（需可連線 Archive.org）
python scripts/convert_books_to_kb.py

# 清理 vault 中所有 .md 檔的 frontmatter/header/intro（保留純內容）
python scripts/clean_and_rebuild_kb.py

# 完整重建 chromadb 索引（刪除舊 collection 後重新建立）
python -c "from knowledge_base import KnowledgeBase; kb=KnowledgeBase(); kb.rebuild_all()"
```

### 經濟學知識庫（Economics Knowledge Base）

內建 `economics-knowledge.yaml`（1,457 個來源）：
- 100+ 經典經濟學著作（馬克思、凱因斯、利弗莫爾、葛拉漢等）
- IMF 工作論文（金融加速器、貿易碎片化、財政理論）
- 學術期刊（Real-World Economics Review）
- 按 ticker 產業 + 市場 regime 自動篩選相關知識注入分析

---

## 資料檔案

所有資料儲存在 `DATA_DIR`（預設 `./data/`）：

| 檔案 | 說明 |
|------|------|
| `trading.db` | SQLite 資料庫（orders、trades、ratings、events、workflows、rules） |
| `trades.jsonl` | 成交明細（雙寫入備援） |
| `ratings.json` | LLM 深度分析評級結果 |
| `performance.json` | 最新績效指標快照 |
| `performance_history.json` | 績效歷史曲線 |
| `portfolio_snapshot.json` | 即時投資組合快照 |
| `recap_YYYY-MM-DD.json` | 每日收盤報表 |
| `.breaker` | 熔斷標記檔 |
| `.kill` | Kill switch 標記檔 |
| `.shortlist.json` | 目前篩選清單 |
| `.scheduler_status.json` | 排程器狀態 |
| `fmp_api_usage.json` | FMP API 使用統計 |
| `scheduler.log` | 排程器日誌 |
| `monitor.log` | 盤中監控日誌 |
| `deep_analyzer.log` | 深度分析日誌 |
| `dashboard.log` | Web 面板日誌 |

日誌使用 `RotatingFileHandler`（10MB 自動輪替，保留 5 份）。

---

## 首次執行流程

1. **STAGE 1：Screener** — 掃描 S&P 500 全成分股，運算 5 項技術指標，約 15-30 分鐘
2. **STAGE 2：Deep Analysis** — 對篩選出的 TOP N 標的進行 LLM 多 Agent 深度分析，約 30-60 分鐘
3. **STAGE 3：Monitor** — 進入盤中監控循環，每 30 秒檢查價格，觸發 RiskAgent → ChairmanAgent → ExecutionAgent 流程
4. **STAGE 4：Offline Learning** — 收盤後每 6 小時執行：知識庫同步 + 反思佇列處理

---

## 技術棧

- **語言**: Python 3.11+
- **交易介面**: Alpaca Trading API（`alpaca-py`）
- **LLM 框架**: [TradingAgents](https://github.com/TauricResearch/TradingAgents) 多 Agent 分析
- **LLM Provider**: Agnes AI（OpenAI-compatible）
- **資料源**: yfinance / Financial Modeling Prep / Tavily / Brave / SerpAPI
- **向量資料庫**: chromadb + sentence-transformers
- **行事曆**: exchange-calendars
- **Web 面板**: Flask
- **持久化**: SQLite（WAL mode）+ JSONL 雙寫入
- **外掛系統**: Plugin manifest + importlib 動態載入
- **AI 整合**: MCP（Model Context Protocol）JSON-RPC 2.0

---

## 知識庫資料來源

知識庫中的書籍來自以下公開資源：

- **Project Gutenberg**（48 本）：[gutenberg.org](https://www.gutenberg.org) — 公共領域經濟學與金融經典
- **Archive.org**（8 本經典交易書精華）：[archive.org](https://archive.org) — Cornell University Library 等機構掃描之公共領域藏書
- **自行編寫**（4 本交易指南）：濃縮常見交易規則、選擇權策略、SEC 申報查詢、自學路徑

因 Archive.org 對部分館藏限制純文字下載，8 本經典交易書以精華摘要形式收錄，非 OCR 全文。

## 致謝

- [daily_stock_analysis](https://github.com/ZhuLinsen/daily_stock_analysis) — 股票分析流程參考
- [TradingAgents](https://github.com/TauricResearch/TradingAgents) — LLM 多 Agent 交易分析框架
- [AI Berkshire](https://github.com/xbtlin/ai-berkshire) — 價值投資研究框架啟發，本專案之 `lib/financial_rigor.py`（精確十進位計算/市值驗證/Benford 檢測）、screener 第二層價值評分、Mirror Test（5 句買入理由）、Thesis Tracker（投資論點偏移檢測）均借鑒其方法與實作
- `economics-knowledge.yaml` — 整合 100+ 經典著作、IMF 論文、學術期刊共 1,457 個來源

## 免責聲明

This is an experimental automated trading system operating in **Paper Trading** mode only. No real capital is at risk. The authors assume no responsibility for any financial losses incurred from using this software in live trading.
