---
tags: [options, arbitrage, quantitative]
---

# ABC of Options and Arbitrage (Nelson)

S.A. Nelson's early technical analysis and options trading reference, documenting the pioneering strategies of the late 19th and early 20th century.

## Core Philosophy
- Options and arbitrage are precision instruments for experienced traders
- Understanding the mechanics of these instruments reveals market mispricings
- Successful arbitrage requires speed, capital, and mathematical precision

## Options Fundamentals (Historical Context)

### Put and Call Basics
- **Call**: Right to buy 100 shares at a fixed price (strike) within a fixed time
- **Put**: Right to sell 100 shares at a fixed price within a fixed time
- Premium is paid upfront — non-refundable
- Options are wasting assets — time decay is constant

### Early Option Strategies

**Covered Call Writing:**
- Own 100 shares, sell call against them
- Income from premium as price stays flat
- Risk: missed upside if stock rallies sharply

**Protective Put (Hedge):**
- Own 100 shares, buy put for protection
- Insurance against decline
- Cost of put reduces profit if stock rises

**Straddle:**
- Buy both a put and a call at same strike and expiration
- Profits from large moves in either direction
- Requires volatility; loses to time decay

**Spread (Bull/Bear):**
- Buy one option, sell another on same stock
- Reduces cost and risk, caps reward
- Vertical spread = same expiration, different strike

## Arbitrage Strategies

### Definition
- Simultaneously buying and selling equivalent instruments in different markets
- Goal: capture price discrepancies with zero market risk
- Golden age of individual arbitrageurs before electronic trading

### Types of Arbitrage

**Stock vs. Stock:**
- Same stock traded on multiple exchanges
- Buy the cheaper, sell the dearer
- Profits are small but nearly risk-free

**Stock vs. Convertible:**
- Buy convertible bond, short the common stock
- Capture yield while hedged
- Adjust hedge ratio as delta changes

**Stock vs. Option:**
- Buy/sell options and hedge with underlying stock
- Capture implied vs realized volatility differences
- Requires continuous rebalancing

**Dividend Arbitrage:**
- Buy stock before ex-date, short equivalent position
- Capture dividend net of borrowing costs
- Risk: stock moves against the hedge

## Key Principles

### 1. Time is the Enemy
   - Option positions decay in value daily
   - Time premium erodes fastest in the final month
   - Every day the trade does not move in your favor, the option loses value

### 2. Volatility is the Price
   - Option prices reflect expected volatility
   - Buy options when implied volatility is low
   - Sell options when implied volatility is high
   - Historical volatility is the benchmark

### 3. Arbitrage is a Race Against Technology
   - Price discrepancies close faster as technology improves
   - The individual arbitrageur's edge shrinks with every advance
   - Focus on complex or less-watched instruments

### 4. Transaction Costs Consume Edge
   - Commissions, bid/ask spreads, and borrowing costs must be factored
   - Small edges become negative after costs
   - Scale matters — larger positions reduce proportional costs

## Practical Application

### Option Selection Checklist
- Is implied volatility reasonable vs historical?
- Is there sufficient liquidity (tight bid/ask)?
- Is the time to expiration adequate for the thesis?
- Is the position size appropriate (Kelly criterion)?
- What is the maximum loss scenario?

### Arbitrage Rules
- Confirm both legs can be executed simultaneously
- Prefer cash settlement over physical delivery
- Know the borrowing cost for shorts
- Monitor position continuously — edge disappears instantly
- Close immediately if the spread reverts

## Closing Quote
> "The successful arbitrageur must be quick of thought, decisive, and perfectly disciplined. An opportunity missed is nothing; an opportunity taken without proper hedge is everything."
