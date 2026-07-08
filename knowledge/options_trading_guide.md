---
title: "options_trading_guide"
tags:
  - trading
  - strategy
  - reference
source: "options_trading_guide.md"
---

# options_trading_guide

> 來源：options_trading_guide.md

---

# 期權交易完整指南

## 什麼是期權

期權（Options）是一種衍生性金融商品，賦予持有者在特定時間以特定價格買入或賣出標的資產的「權利」而非「義務」。

### 基本要素
- **Call Option（買權）**：賦予買入標的資產的權利
- **Put Option（賣權）**：賦予賣出標的資產的權利
- **Strike Price（履約價格）**：期權合約規定的買入/賣出價格
- **Expiration Date（到期日）**：期權生效的最後日期
- **Premium（權利金）**：購買期權支付的價格
- **Contract Size**：通常 1 張合約 = 100 股

### 期權鏈（Option Chain）
- 顯示所有可用履約價格和到期日的期權價格
- 包含 Bid、Ask、Last、Volume、Open Interest
- 顯示各期權的 Greeks 值

## 基本策略

### 買方策略（Long Positions）

#### Long Call（做多買權）
- **情境**：強烈看好標的資產上漲
- **最大損失**：權利金
- **最大獲利**：理論上無限
- **適用時機**：預期大幅上漲

#### Long Put（做多賣權）
- **情境**：強烈看跌標的資產
- **最大損失**：權利金
- **最大獲利**：標的跌至 0（極端情況）
- **適用時機**：預期大幅下跌

### 卖方策略（Short Positions）

#### Covered Call（備兌賣權）
- **操作**：持有股票 + 賣出 Call
- **優點**：增加收益、降低持股成本
- **缺點**：限制上漲獲利空間
- **適用時機**：溫和看好或持平

#### Cash-Secured Put（現金擔保賣權）
- **操作**：賣出 Put + 準備現金買入股票
- **優點**：以更低價格買入股票、賺取權利金
- **缺點**：可能被強制買入不想要的股票
- **適用時機**：願意以特定價格買入股票

#### Protective Put（保護性賣權）
- **操作**：持有股票 + 買入 Put
- **優點**：下行保護、上行獲利不限
- **缺點**：支付權利金成本
- **適用時機**：持有股票但擔心短期下跌

### 進階策略

#### Bull Call Spread（看漲價差）
- **操作**：買入低 Strike Call + 賣出高 Strike Call
- **優點**：降低成本、限制風險
- **缺點**：限制獲利空間
- **適用時機**：溫和看漲

#### Bear Put Spread（看跌價差）
- **操作**：買入高 Strike Put + 賣出低 Strike Put
- **優點**：降低成本、限制風險
- **缺點**：限制獲利空間
- **適用時機**：溫和看跌

#### Straddle（跨式選擇權）
- **操作**：買入同 Strike 的 Call + Put
- **優點**：從大幅波動獲利（無論方向）
- **缺點**：需要大幅波動才能獲利
- **適用時機**：預期重大事件（財報、FDA 決定）

#### Strangle（寬跨式選擇權）
- **操作**：買入不同 Strike 的 Call + Put
- **優點**：成本低於 Straddle
- **缺點**：需要更大波動才能獲利
- **適用時機**：預期大幅波動但不確定方向

#### Iron Condor（鐵鷹式選擇權）
- **操作**：賣出 OTM Call Spread + 賣出 OTM Put Spread
- **優點**：高勝率、有限風險
- **缺點**：獲利有限、需要精準判斷
- **適用時機**：預期橫盤整理

## 期權希臘字母（Greeks）

### Delta（Δ）
- **定義**：標的價格變動 1 單位時期權價格的變化
- **Call Delta**：0 到 1
- **Put Delta**：-1 到 0
- **用途**：衡量方向性風險

### Gamma（Γ）
- **定義**：Delta 的變化率
- **特點**：ATM 期權 Gamma 最大
- **用途**：衡量 Delta 的穩定性

### Theta（Θ）
- **定義**：時間經過一期權價格的衰減
- **特點**：到期前 30 天 Theta 最大
- **用途**：賣方策略的重要考量

### Vega（ν）
- **定義**：隱含波動率變動 1% 時期權價格的變化
- **特點**：遠期期權 Vega 較大
- **用途**：衡量波動率風險

### Rho（ρ）
- **定義**：利率變動 1% 時期權價格的變化
- **特點**：影響較小，長期期權較明顯
- **用途**：利率敏感策略

## 隱含波動率（Implied Volatility）

### IV 定義
- 市場對未來波動率的預期
- 從期權價格反推得出
- 以百分比表示

### IV Rank 和 IV Percentile
- **IV Rank**：當前 IV 在过去一年中的位置
- **IV Percentile**：過去一年中 IV 低於當前水平的天數比例
- **用途**：判斷期權是否便宜或貴

### IV Crush（波動率壓縮）
- **定義**：事件後波動率大幅下降導致期權價格暴跌
- **常見時機**：財報發布後、FDA 決定後
- **影響**：Long Straddle/Strangle 損失慘重

### 如何利用 IV
- **高 IV 時**：考慮賣方策略（Sell Premium）
- **低 IV 時**：考慮買方策略（Buy Premium）
- **IV Skew**：不同 Strike 的 IV 差異

## 交易實務

### 訂單類型
- **Market Order**：市價單，立即成交
- **Limit Order**：限價單，指定價格成交
- **Close Order**：平倉單，買入 Call 或賣出 Put 來關閉位置
- **Combo Order**：組合單，同時下多個 leg

### 買賣價差（Bid-Ask Spread）
- **Bid**：買方願意支付的最高價格
- **Ask**：賣方要求的最低價格
- **Spread**：Bid 和 Ask 的差距
- **建議**：使用 Limit Order 避免寬價差損失

### 流動性評估
- **Volume**：當日交易量
- **Open Interest**：未平倉合約數
- **Bid-Ask Spread**：越窄越好
- **建議**：選擇 Volume > 1000 且 Open Interest > 5000 的期權

### 到期日選擇
- **短期（0-30 天）**：Theta 衰減快，適合賣方
- **中期（30-90 天）**：平衡 Theta 和 Vega
- **長期（LEAPS，1 年以上）**：類似股票，Delta 接近 1

### 履約價格選擇
- **ITM（In-The-Money）**：有內在價值，Delta 大
- **ATM（At-The-Money）**：Delta 約 0.5
- **OTM（Out-of-The-Money）**：無內在價值，Delta 小，便宜

## 風險管理

### 最大損失計算
- **買方**：最大損失 = 權利金
- **賣方**：最大損失可能很大，需仔細計算
- **組合策略**：計算淨最大損失

### 倉位控制
- 單一標的期權倉位不超過總資產 5%
- 單一策略組合不超過總資產 10%
- 避免過度杠杆

### 止損策略
- **時間止損**：到期前平倉
- **價格止損**：損失達到一定比例時平倉
- **事件止損**：重大事件前後平倉

### 組合風險
- **Net Delta**：整體方向性風險
- **Net Gamma**：Delta 變化風險
- **Net Theta**：時間衰減風險
- **Net Vega**：波動率風險

## 學習資源

### CBOE Options Institute
- **官網**：https://www.cboe.com/optionsinstitute/
- **Options 101**：30 分鐘基礎課程
- **Learning Portal**：免費線上學習平台
- **Options Calculator**：期權定價工具
- **Trade Optimizer**：策略優化工具

### 線上課程
- **Coursera**：Financial Engineering and Risk Management
- **edX**：Derivatives Courses
- **Udemy**：Options Trading Strategies

### 實戰工具
- **ThinkOrSwim**：TD Ameritrade 的期權交易平台
- **Interactive Brokers**：專業期權交易介面
- **OptionStrat**：視覺化期權策略工具

### 推薦書籍
- **Options as a Strategic Investment** by Lawrence G. McMillan
- **The Options Playbook** by Brian Overby
- **Understanding Options** by Michael S. Martin

