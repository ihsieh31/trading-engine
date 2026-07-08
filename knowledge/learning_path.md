---
title: "learning_path"
tags:
  - trading
  - strategy
  - reference
source: "learning_path.md"
---

# learning_path

> 來源：learning_path.md

---

# 美股完整學習路徑

## 階段1：基礎知識（已完成 ✓）

- **22本經典書籍已下載至** `~/Downloads/股票2/`
- **涵蓋領域：**
  - 華爾街歷史
  - 交易心理學
  - 道氏理論
  - 選擇權基礎
  - 投資哲學
  - 市場內幕故事

- **重點閱讀順序和摘要：**

  1. *Reminiscences of a Stock Operator* — Edwin Lefèvre
     傑西·利弗摩傳記，理解市場心理與投機本質

  2. *The Battle for Investment Survival* — Gerald T. Loeb
     防禦型投資策略，如何在熊市中保護資本

  3. *How I Trade and Invest* — Richard D. Wyckoff
     威科夫方法論，量價關係與市場循環

  4. *45 Years in Wall Street* — Charles Dow / William Delbert Gann
     道氏理論源頭與甘氏技術分析精華

  5. *Beat the Market* — Edward O. Thorp
     量化思維的開創，期權定價與套利策略

---

## 階段2：技術分析（已完成 ✓）

- **10支股票10年K線數據**：AAPL, MSFT, NVDA, AMZN, TSLA, JPM, JNJ, XOM, KO, NFLX
- **11,000+ 蠟燭圖形態分析**：單根K線 + 多根K線組合形態識別
- **50次回測結果**：5種策略 × 10支股票
- **最佳回測結果**：
  - MultiTimeframe 策略在 NVDA 上實現 **2944% 總回報**
  - 夏普比率、最大回撤、勝率等關鍵指標已記錄
- **使用工具：** backtrader, yfinance, pandas, matplotlib

---

## 階段3：基本面分析（已完成 ✓）

### SEC EDGAR 使用指南

- **查詢網址：** https://www.sec.gov/cgi-bin/browse-edgar
- **重要文件類型：**
  - **10-K**：年度報告，包含完整財務報表与管理層討論（MD&A）
  - **10-Q**：季度報告，未審計財務數據
  - **8-K**：重大事件即時披露（併購、高管變更、破產等）
  - **13F**：機構機構持倉報告（季報，追蹤聰明錢）
  - **S-1 / F-1**：IPO 招股說明書

- **解讀步驟：**
  1. 從 EDGAR 獲取最新 10-K
  2. 查看「Business」了解公司業務模式
  3. 閱讀「Risk Factors」評估風險
  4. 分析「MD&A」理解管理層觀點
  5. 深入財務報表附註

### 財報解讀方法

- **損益表（Income Statement）：**
  - 營收成長率（YoY, QoQ）
  - 毛利率趨勢
  - 營業利潤率 vs 淨利率
  - EPS（基本 & 稀釋）

- **資產負債表（Balance Sheet）：**
  - 流動比率（Current Ratio > 1.5 為佳）
  - 負債權益比（Debt/Equity < 0.5 為佳）
  - 現金及等價物變化
  - 商譽與無形資產比例

- **現金流量表（Cash Flow Statement）：**
  - 營運現金流是否為正且增長
  - 自由現金流（FCF = OCf - CapEx）
  - 股權回報（ROE = 淨利 / 股東權益）
  - 資產回報（ROA = 淨利 / 總資產）

### 重要指標計算

| 指標 | 公式 | 健康標準 |
|------|------|----------|
| P/E（本益比） | 股價 / EPS | 低於同業平均 |
| P/B（市淨比） | 股價 / 每股帳面價值 | < 3 |
| PEG（本益成長比） | P/E / 預期盈餘成長率 | < 1 為低估 |
| EV/EBITDA | 企業價值 / EBITDA | 低於同業 |
| 毛利率 | 毛利 / 營收 | > 40% 為優 |
| ROE | 淨利 / 股東權益 | > 15% 為佳 |
| 自由現金流收益率 | FCF / 市值 | > 5% |

### 推薦資源
- sec.gov/edgar（官方 filings）
- investopedia.com（指標教學）
- macrotrends.net（歷史財報數據）

---

## 階段4：量化交易（框架已建立 ✓）

- **Python + Backtrader 回測框架**
- **5種策略測試完成：**
  1. SimpleMovingAverage — 雙均線交叉策略
  2. RSIReversal — RSI 超買超賣反轉策略
  3. BollingerBreakout — 布林通道突破策略
  4. MACDStrategy — MACD 金叉死叉策略
  5. MultiTimeframe — 多時間週期確認策略（最佳）

- **增強版回測功能：**
  - 止損機制（固定百分比止損）
  - 倉位管理（凱利公式 / 固定比例）
  - 多時間週期確認（日線 + 週線）
  - 交易成本模擬（手續費 + 滑價）

- **最佳策略結果：**
  - MultiTimeframe 在 NVDA 上獲得 **2944% 回報**
  - 在 AAPL 上獲得約 200%+ 回報
  - 整體勝率約 55%-65%

- **進階方向：**
  - 機器學習應用（隨機森林 / LSTM 預測）
  - 高頻交易（訂單簿分析）
  - 算法執行（TWAP / VWAP）
  - 多因子模型（價值、動能、質量、低波）

---

## 階段5：進階策略（待學習）

### 期權交易完整指南

- **基本概念：**
  - Call Option（看漲期權）：賦予買方在到期日前以特定價格購買股票的權利
  - Put Option（看跌期權）：賦予買方在到期日前以特定價格出售股票的權利
  - 權利金（Premium）：期權买方支付給卖方的費用
  - 履約價（Strike Price）：期權合約中约定的買賣價格
  - 到期日（Expiration Date）：期權失效的最後日期

- **四大基本操作：**
  1. 買入 Call（Long Call）— 看漲，損失有限、獲利潛力大
  2. 買入 Put（Long Put）— 看跌，損失有限、獲利潛力大
  3. 賣出 Call（Short Call）— 看空或中性，收取權利金
  4. 賣出 Put（Short Put）— 看漲或中性，收取權利金

- **常見期權策略：**
  - **Covered Call（備兌看漲期權）**：持有正股 + 賣出 Call，產生租金收入
  - **Protective Put（保護性看跌期權）**：持有正股 + 買入 Put，保險功能
  - **Bull Call Spread（看漲價差）**：買入低履約 Call + 賣出高履約 Call
  - **Bear Put Spread（看跌價差）**：買入高履約 Put + 賣出低履約 Put
  - **Iron Condor（鐵鷹）**：同時賣出 OTM Call Spread + OTM Put Spread，區間震盪策略
  - **Straddle / Strangle（跨式 / 寬跨式）**：同時買入 Call + Put，波動率策略

- **希臘字母（Greeks）：**
  - Delta（Δ）：價格敏感度，Call: 0~1, Put: -1~0
  - Gamma（Γ）：Delta 的變化率
  - Theta（Θ）：時間衰減，每天損失
  - Vega（ν）：波動率敏感度
  - Rho（ρ）：利率敏感度

### 期貨與指數交易

- **主要期貨合約：**
  - E-mini S&P 500（ES）
  - Nasdaq-100（NQ）
  - Dow Jones（YM）
  - Crude Oil（CL）
  - Gold（GC）

- **期貨特點：**
  - 槓桿交易（保證金制度）
  - 雙向交易（做多 / 做空）
  - 每日結算（Mark-to-Market）
  - 到期月份交割

- **指數期貨交易注意事項：**
  - 理解基差（Basis = 期貨價格 - 指數現貨）
  - 關注展期收益（Roll Yield）
  - 注意保證金追繳風險

### 市場微結構知識

- **訂單簿（Order Book）：**
  - 買方掛單（Bid Side）vs 賣方掛單（Ask Side）
  - 買賣價差（Bid-Ask Spread）
  - 深度（Market Depth）

- **交易機制：**
  - 市價單（Market Order）vs 限價單（Limit Order）
  - 停止單（Stop Order）vs 停止限價單（Stop-Limit Order）
  - IOC（Immediate-or-Cancel）vs FOK（Fill-or-Kill）

- **流動性與滑價：**
  - 流動性提供者（Maker）vs 流動性消耗者（Taker）
  - 滑價（Slippage）對頻繁交易策略的影響
  - 成交量加權平均價（VWAP）作為執行基準

- **高級主題：**
  - 統計套利（Statistical Arbitrage）
  - 配對交易（Pairs Trading）
  - 市場做市（Market Making）
  - 訂單流分析（Order Flow Analysis）

---

## 推薦學習資源

| 資源 | 網址 | 說明 |
|------|------|------|
| CBOE Options Institute | https://www.cboe.com/optionsinstitute/ | 免費期權課程與教材 |
| QuantStart | https://www.quantstart.com/articles/ | 量化交易策略文章 |
| SEC Investor Education | https://www.sec.gov/investor | 官方投資者教育 |
| Investopedia | https://www.investopedia.com/ | 金融詞典與教學 |
| TradingView | https://www.tradingview.com/ | 免費K線圖和篩選器 |
| Alpha Architect | https://alphaarchitect.com/blog/ | 因子投資與量化研究 |
| Ernie Chan (Book Author) | https://epchan.com/ | 量化交易書籍作者 |
| Khan Academy Finance | https://www.khanacademy.org/economics-finance-domain/core-finance | 免費金融基礎課程 |

---

## 學習進度總覽

| 階段 | 主題 | 狀態 | 完成度 |
|------|------|------|--------|
| 1 | 基礎知識 | ✓ 完成 | 100% |
| 2 | 技術分析 | ✓ 完成 | 100% |
| 3 | 基本面分析 | ✓ 完成 | 100% |
| 4 | 量化交易 | ✓ 框架建立 | 80% |
| 5 | 進階策略 | ○ 待學習 | 0% |

> **下一步建議：** 從階段5開始，先學習期權基礎（CBOE Options Institute 免費課程），然後實踐 Covered Call 策略於現有持股。

