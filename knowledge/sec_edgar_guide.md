---
title: "sec_edgar_guide"
tags:
  - trading
  - strategy
  - reference
source: "sec_edgar_guide.md"
---

# sec_edgar_guide

> 來源：sec_edgar_guide.md

---

# SEC EDGAR 完整使用指南

## 什麼是 EDGAR

EDGAR = Electronic Data Gathering, Analysis, and Retrieval System
- SEC 的官方 filings 資料庫
- 網址：https://www.sec.gov/edgar/searchedgar/companysearch.html
- 所有上市公司必須向 SEC 提交 filings
- 免費公開查詢

## 主要表單類型

### 定期報告
- **10-K**：年度報告（每年一次，最完整）
  - 包含：完整財報、管理層討論、風險因素、公司治理
  - 發布時間：財年後 60 天（大型企業）/ 75 天（小型企業）
  
- **10-Q**：季度報告（每季度一次）
  - 包含：未經審計的財報、管理層討論
  - 發布時間：季後 40 天（大型企業）/ 45 天（小型企業）
  
- **8-K**：重大事件報告（即時）
  - 包含：CEO 變更、併購、破產、重大合約
  - 發布時間：5 個工作日內

### 發行與募資
- **S-1**：首次公開發行註冊聲明
- **424B4**：招股說明書
- **F-1**：外國公司 IPO

### 其他重要表單
- **DEF 14A**：委託書（Proxy Statement）- 股東大會資訊
- **13F**：機構投資者持倉報告（每季度）
- **3, 4, 5**：內部人持倉變動報告
- **SC 13D/G**：持股超過 5% 的投資人報告

## 如何使用 EDGAR

### 搜尋方式
1. **公司名稱搜尋**：輸入公司全名或部分名稱
2. **代碼搜尋（Ticker）**：輸入股票代碼如 AAPL、MSFT
3. **CIK 號碼搜尋**：Central Index Key 號碼
4. **關鍵字全文搜尋**：搜尋 filings 中的特定字詞

### 篩選條件
- **表單類型**：選擇 10-K、10-Q、8-K 等
- **日期範圍**：設定起止日期
- **公司狀態**：活躍、註銷、暫停
- **產業類別**：SIC Code 篩選

### 實用連結
- EDGAR 搜尋：https://www.sec.gov/edgar/searchedgar/companysearch.html
- CIK 查詢：https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=
- SIC Codes：https://www.sec.gov/edgar/searchedgar/standard-industrial-classification-sic-code-list
- EDGAR Full Text Search：https://www.sec.gov/edgar/search/
- EDGAR API：https://www.sec.gov/edgar/searchedgar/companysearch.html

## 財報解讀指南

### 損益表（Income Statement）
- **營收（Revenue）**：公司銷售產品或服務的總收入
- **營業成本（COGS）**：生產產品或服務的 Direct Cost
- **毛利（Gross Profit）**：營收 - COGS
- **營業費用（Operating Expenses）**：SG&A、研發、折舊攤提
- **營業利益（Operating Income）**：毛利 - 營業費用
- **稅前利益（Pre-tax Income）**：營業利益 +/- 利息和其他收支
- **淨利（Net Income）**：稅前利益 - 所得稅

### 資產負債表（Balance Sheet）
- **資產（Assets）**：
  - 流動資產：現金、應收帳款、存貨
  - 非流動資產：廠房設備、無形資產、商譽
- **負債（Liabilities）**：
  - 流動負債：應付帳款、短期借款
  - 非流動負債：長期債務、債券
- **股東權益（Shareholders' Equity）**：資產 - 負債

### 現金流量表（Cash Flow Statement）
- **營業活動現金流**：日常業務產生的現金
- **投資活動現金流**：資本支出、投資收益
- **融資活動現金流**：發行股票、償還債務、發放股利

### 附註說明（Notes）
- 會計政策說明
- 或有事項（Contingencies）
- 部門資訊（Segment Reporting）
- 關聯方交易

## 重要指標計算

### 估值指標
- **P/E Ratio** = 股價 / EPS
- **P/B Ratio** = 股價 / 每股帳面價值
- **P/S Ratio** = 市值 / 營收
- **EV/EBITDA** = 企業價值 / 稅息折舊及攤銷前利潤
- **PEG Ratio** = P/E / 盈利增長率

### 獲利能力
- **ROE** = 淨利 / 股東權益
- **ROA** = 淨利 / 總資產
- **ROIC** = NOPAT / 投入資本
- **Gross Margin** = 毛利 / 營收
- **Operating Margin** = 營業利益 / 營收
- **Net Margin** = 淨利 / 營收

### 財務健康
- **Debt/Equity** = 總負債 / 股東權益
- **Current Ratio** = 流動資產 / 流動負債
- **Quick Ratio** = (流動資產 - 存貨) / 流動負債
- **Interest Coverage** = EBIT / 利息費用
- **Free Cash Flow** = 營業現金流 - 資本支出

## 實用技巧

### 快速篩選好公司
1. ROE > 15% 連續 5 年
2. Debt/Equity < 0.5
3. 營收和淨利年均增長 > 10%
4. Free Cash Flow 持續為正
5. P/E 低於產業平均

### 發現問題公司
1. 營收增長放緩但 EPS 增长（可能透過回購）
2. 應收帳款增長快於營收增長
3. 存貨積壓
4. 一次性收益佔比過高
5. 經營現金流低於淨利

### 關注重大事件
1. 8-K 中的 CEO 變更
2. 併購公告
3. 破產申請
4. 重大合約簽訂
5. 監管調查

## 學習資源

- **SEC Investor Education**：https://www.sec.gov/investor
- **Investopedia**：https://www.investopedia.com/
- **EDGAR Search Tutorial**：https://www.sec.gov/edgar/searchedgar/searchtutorial.htm
- **Financial Statement Analysis**：https://www.sec.gov/investor/advisorycompilation/financialstatements.htm

