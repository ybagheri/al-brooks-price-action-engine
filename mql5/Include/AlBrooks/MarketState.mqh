//+------------------------------------------------------------------+
//|                                               MarketState.mqh   |
//|  The market-mode classifier and its four proxy modules.         |
//+------------------------------------------------------------------+
//
// ## Honesty
//
// "BULL_TREND" here is a PROXY. It does not mean the market is in a bull
// trend; it means a documented set of geometric conditions scored
// highest. Nothing in this file is a probability, a win rate, a
// profitability figure or an edge, and nothing in it is validated
// against outcomes.
//
// ## What is ported
//
// | Python | Here |
// |---|---|
// | `context/trend.py` | `AlB_TrendGap`, `AlB_MeasurePressure` |
// | `context/channel.py` | `AlB_CalculateChop` |
// | `context/trading_range.py` | `AlB_MeasureRange`, the three score helpers |
// | `context/breakout_mode.py` | `AlB_IsTightening` |
// | `context/market_state.py` | `AlB_LargestRemainder`, `AlB_AnalyzeMarketState` |
//
// Every constant below is `AnalyzerConfig`'s default, and the case files
// carry `"config": {}`, so reading them from here is reading the same
// values Python reads rather than a second opinion about them.

#ifndef ALBROOKS_MARKETSTATE_MQH
#define ALBROOKS_MARKETSTATE_MQH

// --- AnalyzerConfig defaults this module depends on ---------------------
#define AB_STRONG_CLOSE_PCT  0.70
#define AB_MIN_BODY_PCT      0.30
#define AB_OVERLAP_RATIO     0.50
#define AB_PRESSURE_LOOKBACK 10
#define AB_STATE_LOOKBACK    20
#define AB_STATE_OVERLAP     10

// `trend.MIN_EMA_BARS`: below this the EMA pair is meaningless, and the
// gap is reported as 0.0 rather than as a small confident number.
#define AB_MIN_EMA_BARS 50
// `trend.SLOPE_ATR_DIVISOR`
#define AB_SLOPE_ATR_DIVISOR 2.0

// `trading_range.EXPAND_SPAN` / `COMPACT_SPAN`
#define AB_EXPAND_SPAN  3.0
#define AB_COMPACT_SPAN 6.0
// The divisor `compaction_score` uses, and it is NOT `EXPAND_SPAN`.
#define AB_COMPACT_DIVISOR 4.0

// `breakout_mode.TIGHTNESS_WINDOW`
#define AB_TIGHTNESS_WINDOW 4

// `market_state.MODE_SCORE_FLOOR`: a winning raw score below this reports
// TRANSITION rather than the winning mode.
#define AB_MODE_SCORE_FLOOR 1.0

// The order is load-bearing: the Nth entry of the raw-score array is the
// Nth state here, and `strength` is the winner's apportionment.
const string AB_STATES[6] = {
   "BULL_TREND", "BEAR_TREND", "BULL_CHANNEL",
   "BEAR_CHANNEL", "TRADING_RANGE", "BREAKOUT_MODE"
};
#define AB_STATE_COUNT 6

const string AB_TRANSITION = "TRANSITION";
const string AB_UNKNOWN    = "UNKNOWN";

struct ABMarketState
  {
   bool            valid;
   string          mode;
   int             direction;
   double          strength;
   double          raws[AB_STATE_COUNT];   // diagnostics only
   int             percentages[AB_STATE_COUNT];
   // The `evidence` list, as the strings Python builds. The decision layer
   // reads a trailing NUMBER out of each one and calls the factor `MEASURED`
   // when there is one, so these are load-bearing, not prose: dropping them
   // would make every candidate's market context unquantified and change
   // the evidence score of every bundle.
   string          evidence[3];
   int             evidence_count;
  };

//+------------------------------------------------------------------+
double AlB_Clamp01(const double x)
  {
   return(MathMin(MathMax(x, 0.0), 1.0));
  }

//+------------------------------------------------------------------+
double AlB_Clamp11(const double x)
  {
   return(MathMin(MathMax(x, -1.0), 1.0));
  }

//+------------------------------------------------------------------+
//| AlB_PairOverlap -- `price_action/overlap.py::pair_overlap`.        |
//|                                                                    |
//|  The shared portion of the two BODIES, over the smaller of the    |
//| two RANGES. Bodies, not bars: using the highs and lows here is   |
//| the single most common way this number comes out different, and   |
//| it changes `chop`, which changes four of the six raw scores.       |
//+------------------------------------------------------------------+
double AlB_PairOverlap(const ABBar &a, const ABBar &b)
  {
   const double m = MathMin(a.high - a.low, b.high - b.low);
   if(m <= 0.0)
      return(0.0);
   const double top    = MathMin(MathMax(a.close, a.open), MathMax(b.close, b.open));
   const double bottom = MathMax(MathMin(a.close, a.open), MathMin(b.close, b.open));
   return(MathMax(0.0, (top - bottom) / m));
  }

//+------------------------------------------------------------------+
//| AlB_TrendGap -- EMA20 minus EMA50 at `idx`, in price units.       |
//|                                                                    |
//|  Seeded from the FIRST close and smoothed forward, not a standard |
//|  SMA seed. The seed is the whole function for the first fifty     |
//|  bars, and seeding differently moves the gap by percent.         |
//|                                                                    |
//|  Below `MIN_EMA_BARS` it returns 0.0, which is a decision and    |
//|  not a limit: the callers clamp the result anyway, but the test   |
//|  for it is on the index, not on the size of the answer.          |
//+------------------------------------------------------------------+
double AlB_TrendGap(const ABBar &bars[], const int count, const int idx)
  {
   if(idx < 0 || idx >= count || idx + 1 < AB_MIN_EMA_BARS)
      return(0.0);
   const double k20 = 2.0 / 21.0;
   const double k50 = 2.0 / 51.0;
   double e20 = bars[0].close;
   double e50 = bars[0].close;
   for(int i = 1; i <= idx; i++)
     {
      const double c = bars[i].close;
      e20 = c * k20 + e20 * (1.0 - k20);
      e50 = c * k50 + e50 * (1.0 - k50);
     }
   return(e20 - e50);
  }

//+------------------------------------------------------------------+
//| AlB_MeasurePressure -- net strong-bar pressure over the lookback. |
//|                                                                    |
//|  Three details decide whether this agrees:                       |
//|                                                                    |
//|  1. The window is `n` BARS ENDING AT `idx` inclusive, walking    |
//|     backwards, and it is clipped at 0 -- never at 1.             |
//|  2. The divisor is `n`, the CONFIGURED lookback, not the number  |
//|     of bars actually examined. At the start of a series the two  |
//|     differ and the pressure is genuinely smaller.                |
//|  3. The bar's range is floored at 1e-9, so a zero-range bar is   |
//|     divided by 1e-9 rather than raising.                          |
//+------------------------------------------------------------------+
double AlB_MeasurePressure(const ABBar &bars[],
                           const int count,
                           const int idx,
                           const int last_closed,
                           const int lookback,
                           int &bull,
                           int &bear)
  {
   bull = 0;
   bear = 0;
   if(idx < 0 || idx >= count)
      return(0.0);
   const int n = MathMax(1, lookback);
   const int stop = MathMax(-1, idx - n);
   for(int i = idx; i > stop; i--)
     {
      if(i < 0 || i > last_closed || i >= count)
         continue;
      const double o = bars[i].open;
      const double l_val = bars[i].low;
      const double c = bars[i].close;
      const double rg = MathMax(bars[i].high - l_val, 1e-9);
      const int direction = (c > o) ? 1 : ((c < o) ? -1 : 0);
      const double close_pos = (c - l_val) / rg;
      const double body_ratio = MathAbs(c - o) / rg;
      if(direction > 0 && close_pos >= AB_STRONG_CLOSE_PCT && body_ratio >= AB_MIN_BODY_PCT)
         bull++;
      if(direction < 0 && (1.0 - close_pos) >= AB_STRONG_CLOSE_PCT
         && body_ratio >= AB_MIN_BODY_PCT)
         bear++;
     }
   return((double)(bull - bear) / (double)n);
  }

//+------------------------------------------------------------------+
//| AlB_MeasureRange -- window high/low over the lookback, in ATR.   |
//|                                                                    |
//|  `hh` and `ll` are independent maxima and minima over the SAME    |
//| window, not the high and low of the same bar.                     |
//+------------------------------------------------------------------+
double AlB_MeasureRange(const ABBar &bars[],
                        const int count,
                        const int idx,
                        const double atr,
                        const int lookback,
                        double &window_high,
                        double &window_low)
  {
   window_high = 0.0;
   window_low  = 0.0;
   if(idx < 0 || idx >= count || atr <= 0.0 || lookback < 1)
      return(0.0);
   const int w0 = MathMax(0, idx - lookback + 1);
   double hh = bars[w0].high;
   double ll = bars[w0].low;
   for(int i = w0 + 1; i <= idx; i++)
     {
      if(bars[i].high > hh)
         hh = bars[i].high;
      if(bars[i].low < ll)
         ll = bars[i].low;
     }
   window_high = hh;
   window_low  = ll;
   return((hh - ll) / atr);
  }

//+------------------------------------------------------------------+
double AlB_ExpansionScore(const double span_atr)
  {
   return(AlB_Clamp01((span_atr - AB_EXPAND_SPAN) / AB_EXPAND_SPAN));
  }

//+------------------------------------------------------------------+
double AlB_CompactionScore(const double span_atr)
  {
   return(AlB_Clamp01((AB_COMPACT_SPAN - span_atr) / AB_COMPACT_DIVISOR));
  }

//+------------------------------------------------------------------+
double AlB_BalanceScore(const double pressure)
  {
   return(1.0 - MathAbs(AlB_Clamp11(pressure)));
  }

//+------------------------------------------------------------------+
//| AlB_CalculateChop -- fraction of recent consecutive PAIRS that    |
//| overlap, in 0..1.                                                  |
//|                                                                    |
//|  The denominator is the number of pairs, which is                 |
//|  `idx - max(0, idx - overlap_bars + 1)` -- so on a long series    |
//|  with `overlap_bars = 10` it is NINE, not ten, because the        |
//|  window spans eleven bars. Dividing by the configured count       |
//|  instead is a 10% error in `chop`, and `chop` is in four of the   |
//|  six raw scores.                                                  |
//+------------------------------------------------------------------+
double AlB_CalculateChop(const ABBar &bars[],
                         const int count,
                         const int idx,
                         const int overlap_bars,
                         const double overlap_ratio)
  {
   if(idx < 0 || idx >= count || overlap_bars < 1)
      return(0.0);
   const int o0 = MathMax(0, idx - overlap_bars + 1);
   const int pairs = idx - o0;
   if(pairs <= 0)
      return(0.0);
   int ov_count = 0;
   for(int i = o0 + 1; i <= idx; i++)
      if(AlB_PairOverlap(bars[i], bars[i - 1]) >= overlap_ratio)
         ov_count++;
   return((double)ov_count / (double)pairs);
  }

//+------------------------------------------------------------------+
//| AlB_IsTightening -- the newest bar is tighter than the MEDIAN of  |
//| the previous four.                                                 |
//|                                                                    |
//|  With four values the "median" is the mean of the middle two,    |
//|  and it is taken of the SORTED ranges -- so this is a real        |
//|  median, not the mean of four. Using the mean changes the         |
//|  threshold and flips the answer on exactly the bars that sit      |
//|  between the two.                                                  |
//+------------------------------------------------------------------+
bool AlB_IsTightening(const ABBar &bars[], const int count, const int idx)
  {
   if(idx < AB_TIGHTNESS_WINDOW || idx >= count)
      return(false);
   double r[AB_TIGHTNESS_WINDOW];
   for(int i = 0; i < AB_TIGHTNESS_WINDOW; i++)
      r[i] = bars[idx - AB_TIGHTNESS_WINDOW + i].high - bars[idx - AB_TIGHTNESS_WINDOW + i].low;
   // Insertion sort: four elements, and the order of the equalities is
   // irrelevant to the median.
   for(int i = 1; i < AB_TIGHTNESS_WINDOW; i++)
     {
      const double key = r[i];
      int j = i - 1;
      while(j >= 0 && r[j] > key)
        {
         r[j + 1] = r[j];
         j--;
        }
      r[j + 1] = key;
     }
   const double med = (r[1] + r[2]) * 0.5;
   return((bars[idx].high - bars[idx].low) < med);
  }

//+------------------------------------------------------------------+
//| AlB_LargestRemainder -- `market_state._largest_remainder`.        |
//|                                                                    |
//|  Two details decide whether this agrees, and both are invisible   |
//|  in the output unless they are wrong:                             |
//|                                                                    |
//|  1. `exact = v / total * 100.0` -- a division THEN a multiply,   |
//|     not `v * 100.0 / total`. Same value to 1e-16, and `floor`    |
//|     is a step function, so a value sitting on an integer can go  |
//|     the other way.                                                |
//|  2. The round count is computed ONCE, from the un-adjusted sum   |
//|     of the floors, and then the loop mutates `pct`. Computing    |
//|     it fresh each pass would be a different algorithm.            |
//|                                                                    |
//|  The tie-break is `(frac, -i)`: largest fraction wins, and on an |
//|  exact tie the EARLIEST index wins. Picking the last one instead |
//|  changes which mode's `strength` is reported.                    |
//+------------------------------------------------------------------+
void AlB_LargestRemainder(const double &values[],
                          const int n,
                          const double total,
                          int &pct[])
  {
   double exact[];
   double frac[];
   ArrayResize(exact, n);
   ArrayResize(frac, n);

   int sum_floor = 0;
   for(int i = 0; i < n; i++)
     {
      const double e = values[i] / total * 100.0;
      const int p = (int)MathFloor(e);
      pct[i]  = p;
      frac[i] = e - (double)p;
      sum_floor += p;
     }

   const int rounds = 100 - sum_floor;
   for(int pass = 0; pass < rounds; pass++)
     {
      int bi = 0;
      for(int i = 1; i < n; i++)
        {
         if(frac[i] > frac[bi])            // strict: an exact tie keeps the earlier index
            bi = i;
        }
      pct[bi]++;
      frac[bi] = -1.0;                     // a spent slot cannot be won again
     }
  }

//+------------------------------------------------------------------+
int AlB_DirectionFor(const string &mode)
  {
   if(mode == "BULL_TREND" || mode == "BULL_CHANNEL")
      return(1);
   if(mode == "BEAR_TREND" || mode == "BEAR_CHANNEL")
      return(-1);
   return(0);
  }

//+------------------------------------------------------------------+
//| AlB_AnalyzeMarketState -- `context/market_state.py::              |
//| analyze_market_state`, reduced to the four leaves the parity      |
//| vector compares.                                                  |
//|                                                                    |
//|  `strength` is the winner's APPORTIONED PERCENTAGE divided by     |
//|  100, not its raw share of the total. That is what makes it a    |
//|  whole number of hundredths, and why it is the one leaf here     |
//|  that cannot drift: any port that reports the raw share is out   |
//|  by whole percentage points rather than in the last bits.        |
//|                                                                    |
//|  The early exits are all "not enough data" answers, and each is   |
//|  the DEFAULT state -- valid=false, mode=UNKNOWN -- rather than a  |
//|  partial one. A state that is half computed is not a state.      |
//+------------------------------------------------------------------+
void AlB_AnalyzeMarketState(const ABBar &bars[],
                            const int count,
                            const int idx,
                            const int last_closed,
                            const double atr,
                            ABMarketState &out)
  {
   out.valid     = false;
   out.mode      = AB_UNKNOWN;
   out.direction = 0;
   out.strength  = 0.0;
   out.evidence_count = 0;
   for(int i = 0; i < AB_STATE_COUNT; i++)
     {
      out.raws[i] = 0.0;
      out.percentages[i] = 0;
     }

   if(idx < 0 || idx > last_closed || idx >= count)
      return;
   if(atr <= 0.0)
      return;

   const int lookback     = MathMax(10, AB_STATE_LOOKBACK);
   const int overlap_bars = MathMax(5, AB_STATE_OVERLAP);
   if(idx + 1 < MathMax(MathMax(lookback + 1, overlap_bars + 1), 6))
      return;

   // --- the four proxies ------------------------------------------------
   const double gap = AlB_TrendGap(bars, count, idx);
   const double slope = AlB_Clamp11(gap / atr / AB_SLOPE_ATR_DIVISOR);
   int bull = 0, bear = 0;
   const double pressure = AlB_MeasurePressure(bars, count, idx, last_closed,
                                               AB_PRESSURE_LOOKBACK, bull, bear);
   const double bull_slope = AlB_Clamp01(slope);
   const double bear_slope = AlB_Clamp01(-slope);
   const double bull_pressure = AlB_Clamp01(pressure);
   const double bear_pressure = AlB_Clamp01(-pressure);

   double window_high = 0.0, window_low = 0.0;
   const double span_atr = AlB_MeasureRange(bars, count, idx, atr, lookback,
                                            window_high, window_low);

   const double chop = AlB_CalculateChop(bars, count, idx, overlap_bars, AB_OVERLAP_RATIO);
   const bool tight = AlB_IsTightening(bars, count, idx);

   const double expand   = AlB_ExpansionScore(span_atr);
   const double compact  = AlB_CompactionScore(span_atr);
   const double balance  = AlB_BalanceScore(pressure);

   // --- the six raw scores, in STATES order ---------------------------
   double raws[AB_STATE_COUNT];
   raws[0] = bull_slope   + bull_pressure   + expand;   // BULL_TREND
   raws[1] = bear_slope   + bear_pressure   + expand;   // BEAR_TREND
   raws[2] = bull_slope   + chop + compact;            // BULL_CHANNEL
   raws[3] = bear_slope   + chop + compact;            // BEAR_CHANNEL
   raws[4] = compact + chop + balance;                 // TRADING_RANGE
   raws[5] = (tight ? 1.0 : 0.0) + compact + chop;      // BREAKOUT_MODE

   // `sum()`, left to right from 0.0, as Python's builtin does.
   double total = 0.0;
   for(int i = 0; i < AB_STATE_COUNT; i++)
      total += raws[i];

   if(total <= 0.0)
     {
      out.valid = true;
      out.mode  = AB_TRANSITION;
      AlB_StateEvidence(out, slope, chop, tight);
      return;
     }

   // Highest raw wins; an exact tie goes to the EARLIEST mode.
   int bi = 0;
   for(int i = 1; i < AB_STATE_COUNT; i++)
      if(raws[i] > raws[bi])
         bi = i;

   // Arrays are copied out of the struct rather than passed as struct
   // members: MQL5 will not take an array member by reference, and the
   // alternative -- returning six values -- is what the copy avoids.
   double carry[AB_STATE_COUNT];
   for(int i = 0; i < AB_STATE_COUNT; i++)
      carry[i] = raws[i];

   int pct[AB_STATE_COUNT];
   AlB_LargestRemainder(carry, AB_STATE_COUNT, total, pct);

   for(int i = 0; i < AB_STATE_COUNT; i++)
     {
      out.raws[i] = raws[i];
      out.percentages[i] = pct[i];
     }

   out.mode = (raws[bi] >= AB_MODE_SCORE_FLOOR) ? AB_STATES[bi] : AB_TRANSITION;
   out.valid     = true;
   out.direction = AlB_DirectionFor(out.mode);
   out.strength  = (double)pct[bi] / 100.0;
   AlB_StateEvidence(out, slope, chop, tight);
  }

//+------------------------------------------------------------------+
//| AlB_StateEvidence -- the three `CODE: detail` lines, in order.      |
//|                                                                    |
//|  `%.2f` and NOT a raw double, because the decision layer parses the |
//|  trailing number back out of the text: `0.666...` is written "0.67" |
//|  and read as 0.67. Emitting the full-precision slope would give a   |
//|  different evidence weight, and it is the FORMATTED value the      |
//|  Python weighs.                                                    |
//+------------------------------------------------------------------+
void AlB_StateEvidence(ABMarketState &out,
                       const double slope,
                       const double chop,
                       const bool tight)
  {
   out.evidence_count = 0;
   if(MathAbs(slope) > 0.5)
     {
      out.evidence[out.evidence_count] =
         "STRONG_EMA_TREND_SLOPE: " + DoubleToString(slope, 2);
      out.evidence_count++;
     }
   if(chop > 0.5)
     {
      out.evidence[out.evidence_count] =
         "HIGH_BAR_OVERLAP_CHOP: " + DoubleToString(chop, 2);
      out.evidence_count++;
     }
   if(tight)
     {
      out.evidence[out.evidence_count] = "RANGE_TIGHTENING_COMPRESSION";
      out.evidence_count++;
     }
  }

#endif // ALBROOKS_MARKETSTATE_MQH
//+------------------------------------------------------------------+
