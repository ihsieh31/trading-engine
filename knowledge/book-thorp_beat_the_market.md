---
tags: [quantitative, options, arbitrage]
---

# Beat the Market (Thorp)

Ed Thorp's 1967 classic on quantitative investing, following his prior work on card counting (Beat the Dealer). Introduced warrant hedging and convertible arbitrage.

## Core Philosophy
- Markets can be systematically beaten using mathematical models
- Mispricings in derivatives create arbitrage opportunities
- The key is finding positive expected value bets and sizing them correctly

## Key Concepts

### Warrant Hedging (Original Strategy)
- Warrants are call options on stocks, often mispriced
- Buy undervalued warrants, short the underlying stock to hedge
- The hedge ratio (delta) determines how many shares to short per warrant
- Adjust the hedge as price and volatility change

### Convertible Arbitrage
- Buy convertible bonds (or preferred stock)
- Short the underlying common stock to eliminate market risk
- Earn the yield advantage while waiting for conversion premium
- Key metric: the conversion parity and yield-to-worst

### The Kelly Criterion (Position Sizing)
- f* = (bp - q) / b where:
  - f* = fraction of capital to bet
  - b = odds received (net odds)
  - p = probability of winning
  - q = probability of losing (1-p)
- Maximizes long-term growth rate
- Prevents overbetting
- Practical rule: bet a fraction of full Kelly to reduce volatility

## Risk Management Framework

### Before Entering a Trade
1. Calculate expected value (must be positive)
2. Compute the hedge ratio
3. Size position using Kelly criterion
4. Determine exit conditions (price target, stop-loss, time stop)

### During the Trade
- Rebalance hedge as delta changes
- Monitor for model breakdown
- Close if the original reasoning is invalidated

### After the Trade
- Review model accuracy
- Update parameters
- Learn from prediction errors

## Market Efficiency Perspective
- Markets are NOT perfectly efficient
- Mispricings exist but require sophisticated analysis to find
- The more participants who search, the smaller the anomalies
- First-mover advantage is real — early quantitative strategies had the best returns

## Practical Application
- Look for mispriced options (implied vol vs realized vol)
- Use convertible bonds as yield-enhanced bond substitutes
- Never buy options at the ask and sell at the bid — the spread destroys edge
- Size positions mathematically, not emotionally

## Closing Quote
> "If you can't find an edge, don't play. The market will grind down even the best strategy if it has no mathematical advantage."
