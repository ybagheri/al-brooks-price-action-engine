//+------------------------------------------------------------------+
//|                                                    Core.mqh       |
//|  Bar, ATR and swing detection, ported from the Python reference.  |
//+------------------------------------------------------------------+
#ifndef ALBROOKS_CORE_MQH
#define ALBROOKS_CORE_MQH

// A single bar. `time` is the OPEN time, matching the Python `Bar.time`.
// MQL5 has no null, so a missing value is carried as this sentinel rather
// than 0.0 -- 0.0 is a legitimate price in some series and silently
// substituting it would move a swing.
#define AB_NAN DBL_MAX

struct ABBar
  {
   datetime       time;
   double         open;
   double         high;
   double         low;
   double         close;
  };

struct ABSwing
  {
   int            bar_index;            // index of the pivot bar
   int            confirmed_bar_index;  // bar_index + k, never bar_index
   double         price;
   int            direction;            // +1 high, -1 low
  };

//+------------------------------------------------------------------+
//| AlB_CalculateAtrSeries                                            |
//|  A direct port of `price_action/bars.py::calculate_atr_series`.   |
//|                                                                   |
//|  Four details decide whether this agrees with Python to 1e-9, and |
//|  each is a place a port silently diverges:                        |
//|                                                                   |
//|   1. Bar 0's true range is `high - low`. There is no previous     |
//|      close to gap against, and using one is the common port.      |
//|   2. The seed at index period-1 is the SIMPLE mean of the first   |
//|      `period` TRs -- not a single TR, and not one Wilder step.    |
//|   3. Indices 0..period-2 are BACKFILLED with the seed, so the      |
//|      series is flat before the seed rather than zero. Leaving     |
//|      them 0.0 disagrees on every early bar.                       |
//|   4. A series shorter than `period` takes a different branch      |
//|      entirely: a running mean, no seed, no backfill.              |
//|                                                                   |
//|  The summation order matches Python's `sum()`, which is left to    |
//|  right from 0.0. Reassociating the additions would drift in the   |
//|  last bits, and the contract compares at 1e-9.                    |
//+------------------------------------------------------------------+
bool AlB_CalculateAtrSeries(const ABBar &bars[],
                            const int count,
                            const int period,
                            double &atrs[])
  {
   if(count <= 0)
      return(false);
   if(period <= 0)
      return(false);

   ArrayResize(atrs, count);
   ArrayInitialize(atrs, 0.0);

   double trs[];
   ArrayResize(trs, count);
   ArrayInitialize(trs, 0.0);

   for(int i = 0; i < count; i++)
     {
      double bh = bars[i].high;
      double bl = bars[i].low;
      if(i == 0)
         trs[i] = bh - bl;                 // no previous close to gap against
      else
        {
         double pc = bars[i - 1].close;
         trs[i] = MathMax(bh - bl, MathMax(MathAbs(bh - pc), MathAbs(bl - pc)));
        }
     }

   if(count < period)
     {
      // Short series: running mean, a different branch from the seed path.
      double cum = 0.0;
      for(int i = 0; i < count; i++)
        {
         cum += trs[i];
         atrs[i] = cum / (i + 1);
        }
      return(true);
     }

   double cum = 0.0;
   for(int i = 0; i < period; i++)
      cum += trs[i];
   atrs[period - 1] = cum / period;

   for(int i = period; i < count; i++)
      atrs[i] = (atrs[i - 1] * (period - 1) + trs[i]) / period;

   const double seed = atrs[period - 1];
   for(int i = 0; i < period - 1; i++)
      atrs[i] = seed;                      // backfill, not zero

   return(true);
  }

//+------------------------------------------------------------------+
//| AlB_FindSwings                                                    |
//|  A direct port of `core/swings.py::find_swings`.                  |
//|                                                                   |
//|  Four details decide whether this agrees, and the third is why    |
//|  the range case exists at all:                                    |
//|                                                                   |
//|   1. The window is SYMMETRIC [s-k, s+k], and the bar at s+k is     |
//|      the last candidate -- the right wing is NOT truncated. The   |
//|      outer bound `last_closed - k + 1` is inclusive.              |
//|   2. Comparisons are STRICT, so an equal high in the LEFT wing   |
//|      does not disqualify a candidate.                             |
//|   3. Earliest-wins is a FORWARD-ONLY tie-break on the RIGHT wing |
//|      only. An equal high at s+1..s+k kills the candidate. Equal   |
//|      prices in the left wing do not. This is the single easiest   |
//|      thing to get wrong, and `parity_range_breakout_001` puts     |
//|      equal highs inside every 5-bar window to make it load-bearing.|
//|   4. `if is_high ... elif is_low`: a bar that is both is recorded |
//|      as a high only. And confirmed is always s+k, never s.        |
//+------------------------------------------------------------------+
int AlB_FindSwings(const ABBar &bars[],
                   const int count,
                   const int last_closed_idx,
                   const int k,
                   ABSwing &swings[])
  {
   ArrayResize(swings, 0);
   if(count == 0)
      return(0);

   int last_closed = (last_closed_idx < count - 1) ? last_closed_idx : count - 1;

   for(int s = k; s <= last_closed - k + 1; s++)
     {
      if(s < 1 || s + k >= count)
         continue;

      const double ps_h = bars[s].high;
      const double ps_l = bars[s].low;

      bool is_high = true;
      bool is_low  = true;

      for(int j = s - k; j <= s + k; j++)
        {
         if(j == s)
            continue;
         if(bars[j].high > ps_h)            // strict: equal does NOT disqualify
            is_high = false;
         if(bars[j].low < ps_l)
            is_low = false;
        }

      // Earliest-wins, forward, right wing only.
      if(is_high)
        {
         for(int j = s + 1; j <= s + k; j++)
           {
            if(bars[j].high == ps_h)        // exact equality, as in Python
              {
               is_high = false;
               break;
              }
           }
        }
      if(is_low)
        {
         for(int j = s + 1; j <= s + k; j++)
           {
            if(bars[j].low == ps_l)
              {
               is_low = false;
               break;
              }
           }
        }

      if(is_high)                           // a bar that is both is a high only
        {
         int n = ArraySize(swings);
         ArrayResize(swings, n + 1);
         swings[n].bar_index           = s;
         swings[n].confirmed_bar_index = s + k;
         swings[n].price               = ps_h;
         swings[n].direction           = 1;
        }
      else
         if(is_low)
           {
            int n = ArraySize(swings);
            ArrayResize(swings, n + 1);
            swings[n].bar_index           = s;
            swings[n].confirmed_bar_index = s + k;
            swings[n].price               = ps_l;
            swings[n].direction           = -1;
           }
     }

   return(ArraySize(swings));
  }

#endif // ALBROOKS_CORE_MQH
//+------------------------------------------------------------------+
