# Bar-by-Bar Price Action Engine Specification

## 1. Overview
The bar-by-bar engine extracts objective, non-repainting geometric features and systematic heuristic classifications from closed OHLC bars. It operates with zero lookahead bias.

## 2. Geometric Primitive Features
- **Range**: `High - Low`
- **Body**: `|Close - Open|`
- **Body Ratio**: `Body / Range`
- **Close Position**: `(Close - Low) / Range` (0.0 = low of bar, 1.0 = high of bar)
- **Upper Tail / Wick**: `High - max(Close, Open)`
- **Lower Tail / Wick**: `min(Close, Open) - Low`

## 3. Heuristic Classifications
- **Doji**: `Body / Range <= 0.15` (configurable via `doji_max_body`). Treated as pause/equilibrium, resetting directional runs.
- **Strong Bull Bar**: `Close > Open`, `Close Position >= 0.70`, and `Body Ratio >= 0.30`.
- **Strong Bear Bar**: `Close < Open`, `1.0 - Close Position >= 0.70`, and `Body Ratio >= 0.30`.
- **Big Bar**: `Range >= 2.0 * ATR` (climax / expansion candidate).
- **Small Bar**: `Range < 0.5 * ATR` (stall / consolidation candidate).
- **Inside Bar**: `High <= Prev High` and `Low >= Prev Low`.
- **Outside Bar**: `High >= Prev High` and `Low <= Prev Low` with at least one strict inequality.
- **ii Pattern**: Consecutive inside bars (`ii_count >= 2`).
- **Pair Overlap**: Intersection of price bodies divided by the minimum bar range:
  $$\text{Overlap}(A, B) = \frac{\max(0, \min(\max(A_c, A_o), \max(B_c, B_o)) - \max(\min(A_c, A_o), \min(B_c, B_o)))}{\min(\text{Range}_A, \text{Range}_B)}$$
- **Barbwire**: $\ge 3$ overlapping pairs within a rolling 5-bar window that contains at least one doji bar.
- **Pressure**: Cumulative counts of strong bull/bear bars over lookback window (default 10 bars).
