---
title: "trading_rules_cheatsheet"
tags:
  - trading
  - strategy
  - reference
source: "trading_rules_cheatsheet.md"
---

# trading_rules_cheatsheet

> 來源：trading_rules_cheatsheet.md

---

# 美股交易規則速查表

## 訂單類型

| 類型 | 說明 |
|------|------|
| Market Order（市價單） | 立即以當前最佳價格成交 |
| Limit Order（限價單） | 指定價格或更好價格才成交 |
| Stop Order（停損單） | 觸發價格後轉為市價單 |
| Stop-Limit Order | 觸發價格後轉為限價單 |
| OCO（One-Cancels-Other） | 一單成交，另一單自動取消 |
| Bracket Order | 止盈+止損一次下達 |
| Trailing Stop | 跟蹤停損，隨價格上漲調整 |

---

## 交易時間

- **盤前交易：** 4:00 AM – 9:30 AM ET
- **正常交易：** 9:30 AM – 4:00 PM ET
- **盤後交易：** 4:00 PM – 8:00 PM ET
- **週末：** 休市
- **節假日休市：** 新年元旦、馬丁路德金日、華盛頓日（2月）、耶穌受難日、獨立日、勞動節、感恩節、感恩節後隔天、聖誕節

---

## 保證金規定

| 項目 | 規定 |
|------|------|
| Reg T Margin（初始保證金） | 50% |
| Maintenance Margin（維持保證金） | 25% |
| Pattern Day Trader (PDT) | 最低門檻 $25,000 |
| PDT 限制 | 5次內觸發 margin call 會被限制交易 |

---

## 做空規則

- **Short Selling 機制：** 向券商借入股票賣出，待價格下跌後買回還券，賺取差價
- **Borrow Fee（借券費用）：** 按年計收，難借股票費率可達 100%+
- **Short Interest（空頭持倉比例）：** 反映市場做空情緒
- **Short Squeeze 機制：** 股價急漲迫使空頭平倉，進一步推升股價
- **Uptick Rule（漲停規則）：** 當空頭持倉佔流通股本達 20%，觸發規則限制做空必須在漲價時進行

---

## 稅務規則

| 項目 | 說明 |
|------|------|
| Short-term Capital Gains | 持有 <1年，按普通所得稅率課稅 |
| Long-term Capital Gains | 持有 >1年，適用優惠稅率 0%/15%/20% |
| Wash Sale Rule（洗售規則） | 虧損卖出後 30天內買入相同證券，虧損不得扣抵 |
| 外資稅務 | 資本利得通常免稅；股息預扣 30%（有稅務協定者可降低）；需填 W-8BEN 表格 |

---

## 重要日期

- **除息日（Ex-Dividend Date）：** 當日或之後買入不享有本次股利分配
- **財報發布季：** 1月、4月、7月、10月
- **FOMC 會議：** 每年 8 次，決議影響利率與市場波動
- **非農就業報告：** 每月第一個週五（實際為週二或週三）
- **CPI 發布日：** 每月月中左右

---

## 市場結構

| 項目 | 說明 |
|------|------|
| NYSE | 紐約證券交易所，實體撮合撮合+電子 |
| NASDAQ | 全國證券交易員協會自動報價系統，全電子化 |
| ARCA | Archipelago 交易所，電子化程度高 |
| IEX | Intercontinental Exchange，自帶緩衝區保護 |
| 做市商（Market Makers） | 提供流動性，持續報出買賣價差 |
| 暗池（Dark Pools） | 隱匿訂單的大型機構交易場所 |
| Payment for Order Flow (PFOF) | 訂單路由商向做市商支付費用獲取訂單 |
| Level 1 報價 | 僅顯示最佳買價/賣價 |
| Level 2 報價 | 顯示全部市場深度（Order Book） |

