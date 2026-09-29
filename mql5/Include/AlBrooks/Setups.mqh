//+------------------------------------------------------------------+
//|                                                    Setups.mqh    |
//|  The eleven detectors and the registry that runs them.           |
//+------------------------------------------------------------------+
//
// ## Honesty
//
// A `SetupFinding` says "this detector fired, in this direction". It is
// not a score, not a ranking and not a recommendation. Nothing here is
// a probability, a win rate, a profitability figure or an edge.
//
// ## What is ported
//
// | Python | Here |
// |---|---|
// | `setups/pullback.py` | `AlB_DetectPullback` |
// | `setups/breakout.py` | `AlB_AnalyzeBreakout` |
// | `setups/reversal.py` | `AlB_AnalyzeReversal` |
// | `setups/double.py` | `AlB_DetectDoubleTop` / `AlB_DetectDoubleBottom` |
// | `setups/measured_move.py` | `AlB_DetectMeasuredMoves` |
// | `setups/fading_measured_move.py` | `AlB_CreateFadeSetups` |
// | `setups/registry.py` | `AlB_RunRegistry`, `AB_FamilyFor` |
// | `setups/base.py` | `ABSetupFinding` |
//
// `fading_measured_move` is ported only as far as the registry uses it.
// The registry calls `create_setups`, which seeds from the projections and
// stops there; the lifecycle (`_advance`, `detect_exhaustion`) is reached
// only through `track_fading_measured_moves`, which the analyzer does not
// call. Porting it would be porting a code path this port never takes, and
// an untested copy of one is worse than its absence.

#ifndef ALBROOKS_SETUPS_MQH
#define ALBROOKS_SETUPS_MQH

// `AlB_TrendGap` and `AlB_Clamp01` come from here. The include is explicit
// rather than relying on the exporter's order: this module already depends
// on both, and a header that works only when something else happened to be
// included first is a header that breaks on the next caller.
#include <AlBrooks/MarketState.mqh>

// --- AnalyzerConfig defaults ------------------------------------------------
#define AB_MIN_LEG_BARS      3
#define AB_MAX_LEG_BARS      100
#define AB_MIN_LEG_ATR       1.0
#define AB_MIN_PB_RATIO      0.15
#define AB_MAX_PB_RATIO      0.90
#define AB_MAX_PB_BARS       50
#define AB_DOUBLE_TOL_ATR    0.25
#define AB_FAILED_BO_BARS    5
#define AB_RANGE_LOOKBACK    50
#define AB_MIN_GAP_ATR       1.0
#define AB_FM_RECENT_SWINGS  8
#define AB_FM_MAX_ACTIVE     20
#define AB_FM_ENABLE_INVERSE 1

// `pullback.determine_trend_direction`: the normalised EMA gap either side of
// this counts as a trend strong enough to pull back in.
#define AB_PB_TREND_GAP 0.4

// `reversal`: the four legs, and what each one needs.
#define AB_PRESSURE_PUSHES 5
#define AB_CROSS_LOOKBACK  10
#define AB_EMA_TOL_ATR    0.25
#define AB_MAJOR_LEGS     4

// `measured_move` evidence ramps. Not free parameters: the decision layer's
// evidence score is a mean of these weights, so a change here moves the score
// of every measured-move candidate.
#define AB_MM_SCALE_FULL_ATR    2.0
#define AB_MM_STRUCTURE_FULL_ATR 0.5
#define AB_MM_CHANNEL_MIN_DEPTH 0.02
#define AB_MM_MAX_INVERSE_LEGS  6
#define AB_MM_RECENT_SWINGS     8

// `breakout`: how far back a break is looked for, and how far it may be back.
#define AB_BO_F_BARS 5
#define AB_BO_T_BARS 20
#define AB_BO_TOL_ATR 0.10
#define AB_BO_LEG2_BARS 10
#define AB_BO_PB_BARS 10

// `price_action.pressure.MAX_RUN_SCAN`
#define AB_MAX_RUN_SCAN 6

// `pullback` trend gate and `measured_move` depth, in the Python source.
const string AB_PB_H1 = "H1";
const string AB_PB_H2 = "H2";
const string AB_PB_L1 = "L1";
const string AB_PB_L2 = "L2";

const string AB_MM_REGULAR  = "REGULAR";
const string AB_MM_RANGE    = "RANGE";
const string AB_MM_CHANNEL  = "CHANNEL";
const string AB_MM_GAP      = "GAP";
const string AB_MM_INVERSE  = "INVERSE";

// ---------------------------------------------------------------------------
// Payload
// ---------------------------------------------------------------------------
//
// ## Why this is a struct and not a dict
//
// MQL5 has no associative container, and the Python payloads are dicts. What
// the *plan* layer needs from a payload is a short, fixed list of fields, so
// those are carried explicitly and the rest of each detector's payload is
// dropped. That is not a shortcut: `contract.py` compares five leaves per
// setup, and `plan.py` reads a named subset. Everything else a payload holds
// is prose or a nested evidence structure, and `PYTHON_MQL5_PARITY.md` §3
// puts both outside the scope on purpose.
//
// The optional-price convention below is the one that matters. `plan._as_float`
// returns a value **only when it is strictly positive**, because every model
// in this engine uses `0.0` as "not observed". So a price field here needs no
// separate "present" flag: `> 0.0` *is* present, and storing a placeholder
// that Python would have rejected is indistinguishable from not storing it.

struct ABSetupPayload
  {
   // --- direction -------------------------------------------------------
   int             direction;          // the detector's own direction
   int             fade_direction;     // FADING_MEASURED_MOVE only; -2 when absent

   // --- prices (absent when <= 0.0, by construction) -------------------
   double          reference_price;
   double          stop_price;
   double          extreme_price;
   double          target_price;
   double          origin_price;
   double          price1;
   double          price2;
   double          level;

   // --- indices (absent when < 0) --------------------------------------
   int             signal_bar;
   int             anchor_bar;
   int             breakout_bar;
   int             origin_bar_index;
   int             state_bar;
   int             created_bar;
   int             bar2;
   int             cross_bar;

   // --- codes -----------------------------------------------------------
   string          state;              // pullback / breakout / fade lifecycle
   string          outcome;            // breakout's historical field
   string          verdict;            // reversal's MAJOR / MINOR
   // Breakout's two adverse flags. Recorded as evidence factors rather than
   // subtracted, so a bundle is never a number that had things taken away
   // from it -- and `ADVERSE_EVIDENCE_CODES` counts them as failed attempts.
   bool            trap;
   bool            second_leg_trap;

   // The projection's two evidence weights, carried through to the decision
   // layer. A measured move's own `confidence` is deliberately NOT re-used:
   // the score is recomputed from the factors, which is what keeps the scalar
   // reproducible from its own evidence rather than able to drift from it.
   double          w_scale;
   double          w_structure;
  };

//+------------------------------------------------------------------+
void AB_ResetPayload(ABSetupPayload &p)
  {
   p.direction        = 0;
   p.fade_direction   = -2;      // -2, because -1 is a real fade direction
   p.reference_price  = 0.0;
   p.stop_price       = 0.0;
   p.extreme_price    = 0.0;
   p.target_price     = 0.0;
   p.origin_price     = 0.0;
   p.price1           = 0.0;
   p.price2           = 0.0;
   p.level            = 0.0;
   p.signal_bar       = -1;
   p.anchor_bar       = -1;
   p.breakout_bar     = -1;
   p.origin_bar_index = -1;
   p.state_bar        = -1;
   p.created_bar      = -1;
   p.bar2             = -1;
   p.cross_bar        = -1;
   p.state            = "";
   p.outcome          = "";
   p.verdict          = "";
   p.trap             = false;
   p.second_leg_trap  = false;
   p.w_scale          = 0.0;
   p.w_structure      = 0.0;
  }

struct ABSetupFinding
  {
   string          detector;
   string          kind;
   int             direction;
   // MQL5 has no null, and `setup_type` is genuinely nullable: only the two
   // pullback detectors carry one. The string "NONE" is a *value* those
   // detectors can produce, so the two are kept apart -- a port that emitted
   // "NONE" everywhere would fail every case rather than half of them.
   bool            has_setup_type;
   string          setup_type;
   ABSetupPayload  payload;
  };

struct ABLeg
  {
   int             start_index;
   int             end_index;
   double          start_price;
   double          end_price;
   int             direction;
   int             bars_count;
   double          price_change;
   int             confirmed_index;
  };

struct ABBreakout
  {
   bool            found;
   int             direction;
   int             breakout_bar;
   double          reference_price;
   bool            ref_is_swing;
   string          outcome;
   string          state;
   int             decide_bar;
   bool            trap;
   int             second_leg_bar;
   int             pullback_bar;
  };

struct ABPullback
  {
   bool            found;
   string          setup_type;
   int             legs;
   int             signal_bar;
   int             anchor_bar;
   double          reference_price;
   double          stop_price;
   int             direction;
   string          state;
   int             extreme_bar;
   double          extreme_price;
  };

struct ABProjection
  {
   bool            found;
   string          family;
   int             direction;
   double          target_price;
   double          mm_range;
   int             origin_bar;
   int             anchor_bar;
   double          reference_price;
   double          pullback_depth;
   double          origin_price;    // `origin.price`
   int             origin_bar_index;// `origin.bar_index`
   // The two evidence weights. The decision layer's score is computed from
   // THESE and not from the projection's `confidence`, because recomputing
   // the scalar from its own factors is what keeps it reproducible rather
   // than able to drift away from them.
   //
   // `MM_SCALE` is the measured range as a fraction of two ATR; the structure
   // factor is the family's own ratio. Both in 0..1.
   double          w_scale;
   double          w_structure;
  };

//+------------------------------------------------------------------+
void AlB_ResetBreakout(ABBreakout &b)
  {
   b.found            = false;
   b.direction        = 0;
   b.breakout_bar     = -1;
   b.reference_price  = 0.0;
   b.ref_is_swing     = false;
   b.outcome          = "NONE";
   b.state            = "NONE";
   b.decide_bar       = -1;
   b.trap             = false;
   b.second_leg_bar   = -1;
   b.pullback_bar     = -1;
  }

//+------------------------------------------------------------------+
void AlB_ResetPullback(ABPullback &p)
  {
   p.found           = false;
   p.setup_type      = "NONE";
   p.legs            = 0;
   p.signal_bar      = -1;
   p.anchor_bar      = -1;
   p.reference_price = 0.0;
   p.stop_price      = 0.0;
   p.direction       = 0;
   p.state           = "NONE";
   p.extreme_bar     = -1;
   p.extreme_price   = 0.0;
  }

//+------------------------------------------------------------------+
//| AB_Round9 -- `round(x, 9)`, for the projection de-duplication key.  |
//|                                                                    |
//|  Two projections are the same finding when their target prices agree |
//|  to nine decimals, not to the last bit. Two arithmetic routes that  |
//|  differ in the seventeenth digit are the same target, and dropping  |
//|  one of them would change the setup count -- which is compared      |
//|  exactly.                                                           |
//|                                                                    |
//|  `DoubleToString` rounds to the requested digits and `StringToDouble`
//|  reads it back, which is round-half-away-from-zero where Python's     |
//|  `round` is round-half-even. The two differ only on an exact tie     |
//|  after 999 digits of scale, which no target price in these cases is. |
//+------------------------------------------------------------------+
double AB_Round9(const double v)
  {
   return(StringToDouble(DoubleToString(v, 9)));
  }

//+------------------------------------------------------------------+
//| AlB_BuildLegs -- `core/legs.py::build_legs_from_swings`.           |
//|                                                                    |
//|  A leg connects ALTERNATE swings, so a pair of same-direction      |
//|  swings is skipped and no leg is emitted for it. The direction is  |
//|  then read off the PRICES, not off the second swing's direction --  |
//|  a low-to-low pair is a bear leg.                                  |
//+------------------------------------------------------------------+
int AlB_BuildLegs(const ABSwing &swings[], const int n, ABLeg &legs[])
  {
   ArrayResize(legs, 0);
   if(n < 2)
      return(0);
   for(int i = 0; i < n - 1; i++)
     {
      if(swings[i].direction == swings[i + 1].direction)
         continue;
      const int k = ArraySize(legs);
      ArrayResize(legs, k + 1);
      legs[k].start_index     = swings[i].bar_index;
      legs[k].end_index       = swings[i + 1].bar_index;
      legs[k].start_price     = swings[i].price;
      legs[k].end_price       = swings[i + 1].price;
      legs[k].direction       = (swings[i + 1].price > swings[i].price) ? 1 : -1;
      legs[k].bars_count      = swings[i + 1].bar_index - swings[i].bar_index;
      legs[k].price_change    = MathAbs(swings[i + 1].price - swings[i].price);
      legs[k].confirmed_index = MathMax(swings[i].confirmed_bar_index,
                                         swings[i + 1].confirmed_bar_index);
     }
   return(ArraySize(legs));
  }

//+------------------------------------------------------------------+
//| AlB_PushCountBack -- `price_action/pressure.py::push_count_back`.  |
//|                                                                    |
//|  A bull push needs BOTH a higher close and a higher high than the   |
//|  bar before. Counting direction alone is a different, looser thing. |
//+------------------------------------------------------------------+
int AlB_PushCountBack(const ABBar &bars[],
                      const int count,
                      const int idx,
                      const int last_closed,
                      const int direction,
                      const int limit)
  {
   if(idx < 0 || idx > last_closed || idx >= count)
      return(0);
   if(direction != 1 && direction != -1)
      return(0);
   int n = 0;
   int i = idx;
   while(i >= 1 && i <= last_closed && i < count)
     {
      if(direction > 0)
        {
         if(!(bars[i].close > bars[i - 1].close && bars[i].high > bars[i - 1].high))
            break;
        }
      else
        {
         if(!(bars[i].close < bars[i - 1].close && bars[i].low < bars[i - 1].low))
            break;
        }
      n++;
      if(n >= limit)
         break;
      i--;
     }
   return(n);
  }

// ---------------------------------------------------------------------------
// Pullback (H1/H2, L1/L2)
// ---------------------------------------------------------------------------

// The four predicates `_classify` closes over, as named tests. Passing them
// through one helper keeps the two directions reading identically, which is
// the property the shared implementation exists to provide.
//
// `DEEPER_LOW` and `DEEPER_HIGH` are two tests and not one with a sign,
// because the two are not mirrors: for a bull pullback "deeper" means a LOWER
// low against the level between the entries, and for a bear pullback it means
// a HIGHER high. One test with a flipped sign would compare the wrong side of
// the bar, and would only be caught by a case that produces a bear pullback.
#define AB_MADE_UP        0
#define AB_MADE_DOWN      1
#define AB_DEEPER_LOW     2
#define AB_DEEPER_HIGH    3

//+------------------------------------------------------------------+
int AlB_TrendDirection(const ABBar &bars[],
                       const int count,
                       const int idx,
                       const int last_closed,
                       const double atr)
  {
   if(idx < 0 || idx > last_closed || idx >= count || atr <= 0.0)
      return(0);
   const double t_gap = AlB_TrendGap(bars, count, idx) / atr;
   if(t_gap > AB_PB_TREND_GAP)
      return(1);
   if(t_gap < -AB_PB_TREND_GAP)
      return(-1);
   return(0);
  }

//+------------------------------------------------------------------+
//| AlB_DetectPullback -- `setups/pullback.py::_classify`.              |
//|                                                                   |
//|  One implementation for both directions, with the sign flipped --  |
//|  which is what the Python does, and the reason a correction to one |
//|  cannot land in the other.                                         |
//|                                                                   |
//|  The window is `[idx - max_pb_bars, idx]`, and `w0 + 1 > idx` is a |
//|  real early exit: a window of one bar has no second bar to compare  |
//|  against, so the "made an extreme" test would read bars[w0 - 1].   |
//+------------------------------------------------------------------+
void AlB_DetectPullback(const ABBar &bars[],
                        const int count,
                        const int idx,
                        const int last_closed,
                        const double atr,
                        const int direction,
                        ABPullback &out)
  {
   AlB_ResetPullback(out);
   if(direction != 1 && direction != -1)
      return;
   if(idx < 0 || idx > last_closed || idx >= count || atr <= 0.0)
      return;
   if(AlB_TrendDirection(bars, count, idx, last_closed, atr) != direction)
      return;

   const bool up = (direction > 0);
   const string entry_1 = up ? AB_PB_H1 : AB_PB_L1;
   const string entry_2 = up ? AB_PB_H2 : AB_PB_L2;

   const int w0 = MathMax(0, idx - AB_MAX_PB_BARS);
   if(w0 + 1 > idx)
      return;

   double mxh = bars[w0].high, mnl = bars[w0].low;
   for(int i = w0 + 1; i <= idx; i++)
     {
      if(bars[i].high > mxh)
         mxh = bars[i].high;
      if(bars[i].low < mnl)
         mnl = bars[i].low;
     }
   if((mxh - mnl) < AB_MIN_PB_RATIO * atr)
      return;

   // `_made_extreme`: bar i pushed further counter-trend than bar i-1.
   const int leg1 = up ? AlB_FirstExtreme(bars, count, w0 + 1, idx, AB_MADE_UP)
                       : AlB_FirstExtreme(bars, count, w0 + 1, idx, AB_MADE_DOWN);
   if(leg1 < 0)
     {
      out.found         = true;
      out.setup_type    = entry_1;
      out.legs          = 0;
      out.state         = "CANDIDATE";
      out.direction     = direction;
      out.anchor_bar    = -1;
      out.extreme_bar   = idx;
      out.extreme_price = up ? bars[idx].low : bars[idx].high;
      out.stop_price    = up ? mnl : mxh;
      return;
     }

   // The counter-move level between the first entry and the next attempt.
   double level_at_1 = up ? DBL_MAX : -DBL_MAX;
   for(int i = w0; i <= leg1; i++)
     {
      if(up)
        {
         if(bars[i].low < level_at_1)
            level_at_1 = bars[i].low;
        }
      else
        {
         if(bars[i].high > level_at_1)
            level_at_1 = bars[i].high;
        }
     }

   // The second counter-trend leg: price pushes past the level the first entry
   // established. Downward for a bull pullback, upward for a bear one.
   const int leg2_low = up
                        ? AlB_FirstExtreme(bars, count, leg1 + 1, idx, AB_DEEPER_LOW, level_at_1)
                        : AlB_FirstExtreme(bars, count, leg1 + 1, idx, AB_DEEPER_HIGH, level_at_1);

   if(leg2_low < 0)
     {
      out.found            = true;
      out.setup_type       = entry_1;
      out.legs             = 1;
      out.signal_bar       = leg1;
      out.anchor_bar       = leg1;
      out.reference_price  = up ? bars[leg1].high : bars[leg1].low;
      out.state            = "PROVISIONAL";
      out.direction        = direction;
      out.extreme_bar      = leg1;
      out.extreme_price    = up ? bars[leg1].low : bars[leg1].high;
      out.stop_price       = up ? mnl : mxh;
      return;
     }

   const int resumption = up ? AlB_FirstExtreme(bars, count, leg2_low + 1, idx, AB_MADE_UP)
                             : AlB_FirstExtreme(bars, count, leg2_low + 1, idx, AB_MADE_DOWN);
   const int extreme_bar = leg2_low;
   const double extreme_price = up ? bars[leg2_low].low : bars[leg2_low].high;
   if(resumption < 0)
     {
      out.found           = true;
      out.setup_type      = entry_2;
      out.legs            = 2;
      out.signal_bar      = -1;
      out.anchor_bar      = leg1;
      out.reference_price = 0.0;
      out.state           = "PROVISIONAL";
      out.direction       = direction;
      out.extreme_bar     = extreme_bar;
      out.extreme_price   = extreme_price;
      out.stop_price      = up ? mnl : mxh;
      return;
     }

   out.found           = true;
   out.setup_type      = entry_2;
   out.legs            = 2;
   out.signal_bar      = resumption;
   out.anchor_bar      = leg1;
   out.reference_price = up ? bars[resumption].high : bars[resumption].low;
   out.state           = "CONFIRMED";
   out.direction       = direction;
   out.extreme_bar     = extreme_bar;
   out.extreme_price   = extreme_price;
   out.stop_price      = up ? mnl : mxh;
  }

//+------------------------------------------------------------------+
int AlB_FirstExtreme(const ABBar &bars[],
                     const int count,
                     const int start,
                     const int idx,
                     const int test,
                     const double level = 0.0)
  {
   for(int i = MathMax(0, start); i <= MathMin(idx, count - 1); i++)
     {
      bool hit = false;
      if(test == AB_MADE_UP)
         hit = (bars[i].high > bars[i - 1].high);
      else if(test == AB_MADE_DOWN)
         hit = (bars[i].low < bars[i - 1].low);
      else if(test == AB_DEEPER_LOW)
         hit = (bars[i].low < level);
      else
         hit = (bars[i].high > level);
      if(hit)
         return(i);
     }
   return(-1);
  }


// ---------------------------------------------------------------------------
// Breakout
// ---------------------------------------------------------------------------

//+------------------------------------------------------------------+
//| AlB_NBarReference -- the highest high and lowest low of the `n`    |
//| bars BEFORE `k`, or "none" when the window is under ten bars.     |
//|                                                                    |
//|  The window is `[max(0, k-n), k)` -- it EXCLUDES bar k. Including  |
//|  it would let the breakout bar set its own reference, and nothing  |
//|  would ever break out.                                            |
//+------------------------------------------------------------------+
bool AlB_NBarReference(const ABBar &bars[],
                       const int count,
                       const int k,
                       const int n,
                       double &hi,
                       double &lo)
  {
   const int start = MathMax(0, k - n);
   if(k - start < 10)
      return(false);
   hi = bars[start].high;
   lo = bars[start].low;
   for(int i = start + 1; i < k; i++)
     {
      if(bars[i].high > hi)
         hi = bars[i].high;
      if(bars[i].low < lo)
         lo = bars[i].low;
     }
   return(true);
  }

//+------------------------------------------------------------------+
//| AlB_SwingReference -- the last swing high and swing low BEFORE `k`.|
//|                                                                    |
//|  "Last", not "extreme": iterating in order and overwriting is the  |
//|  whole behaviour, and taking the highest or the lowest instead     |
//|  picks a different reference on every case with three swings.      |
//+------------------------------------------------------------------+
void AlB_SwingReference(const ABSwing &swings[],
                        const int n,
                        const int k,
                        bool &has_sh,
                        double &sh,
                        bool &has_sl,
                        double &sl)
  {
   has_sh = false;
   sh     = 0.0;
   has_sl = false;
   sl     = 0.0;
   for(int i = 0; i < n; i++)
     {
      if(swings[i].bar_index >= k)
         continue;
      if(swings[i].direction == 1)
        {
         sh     = swings[i].price;
         has_sh = true;
        }
      else
         if(swings[i].direction == -1)
           {
            sl     = swings[i].price;
            has_sl = true;
           }
     }
  }

//+------------------------------------------------------------------+
//| AlB_DetectBreakoutEvent -- direction, reference and whether the    |
//| reference was a swing, for the bar `k`.                           |
//|                                                                    |
//|  The swing reference is tested BEFORE the N-bar one, and it is an |
//|  `elif`: when both would qualify the swing wins. Swapping the two  |
//|  changes `ref_is_swing`, which changes the plan's `stop_basis`, and |
//|  the basis is compared exactly.                                    |
//+------------------------------------------------------------------+
int AlB_DetectBreakoutEvent(const ABBar &bars[],
                            const int count,
                            const int k,
                            const int last_closed,
                            const double atr,
                            const ABSwing &swings[],
                            const int nswings,
                            const int lookback,
                            const double tol_atr,
                            double &reference,
                            bool &is_swing)
  {
   reference = 0.0;
   is_swing   = false;
   if(k < 0 || k > last_closed || k >= count || atr <= 0.0)
      return(0);

   const int n = MathMax(10, lookback);
   const double tol = tol_atr * atr;
   double nb_hi = 0.0, nb_lo = 0.0;
   const bool has_nb = AlB_NBarReference(bars, count, k, n, nb_hi, nb_lo);
   bool has_sh = false, has_sl = false;
   double sh = 0.0, sl = 0.0;
   AlB_SwingReference(swings, nswings, k, has_sh, sh, has_sl, sl);

   const double c = bars[k].close;
   if(has_sh && c > sh + tol)
     {
      reference = sh;
      is_swing   = true;
      return(1);
     }
   if(has_nb && c > nb_hi + tol)
     {
      reference = nb_hi;
      is_swing   = false;
      return(1);
     }
   if(has_sl && c < sl - tol)
     {
      reference = sl;
      is_swing   = true;
      return(-1);
     }
   if(has_nb && c < nb_lo - tol)
     {
      reference = nb_lo;
      is_swing   = false;
      return(-1);
     }
   return(0);
  }

//+------------------------------------------------------------------+
int AlB_FailedSince(const ABBar &bars[],
                    const int count,
                    const int m,
                    const int stop_idx,
                    const double ref,
                    const int direction,
                    const double tol)
  {
   for(int j = m - 1; j > stop_idx; j--)
     {
      if(j < 0 || j >= count)
         continue;
      const double c = bars[j].close;
      if(direction > 0 && c < ref - tol)
         return(j);
      if(direction < 0 && c > ref + tol)
         return(j);
     }
   return(-1);
  }

//+------------------------------------------------------------------+
int AlB_SecondLegTrap(const ABBar &bars[],
                      const int count,
                      const int breakout_bar,
                      const int last_closed,
                      const double reference,
                      const int direction,
                      const double tol,
                      const int max_bars)
  {
   if(direction != 1 && direction != -1)
      return(-1);
   if(breakout_bar < 0 || last_closed >= count)
      return(-1);
   const int upper = MathMin(last_closed, breakout_bar + max_bars);
   int extended = -1;
   for(int i = breakout_bar; i <= upper; i++)
     {
      const double c = bars[i].close;
      const bool beyond = (direction > 0) ? (c > reference + tol) : (c < reference - tol);
      if(beyond)
         extended = i;
      else
         if(extended >= 0)
           {
            const bool back = (direction > 0) ? (c < reference - tol) : (c > reference + tol);
            if(back)
               return(i);
           }
     }
   return(-1);
  }

//+------------------------------------------------------------------+
int AlB_BreakoutPullback(const ABBar &bars[],
                         const int count,
                         const int breakout_bar,
                         const int last_closed,
                         const double reference,
                         const int direction,
                         const double tol,
                         const int max_bars)
  {
   if(direction != 1 && direction != -1)
      return(-1);
   if(breakout_bar < 0 || last_closed >= count)
      return(-1);
   const int upper = MathMin(last_closed, breakout_bar + max_bars);
   for(int i = breakout_bar + 1; i <= upper; i++)
     {
      const double c = bars[i].close;
      const bool through = (direction > 0) ? (c < reference - tol) : (c > reference + tol);
      if(through)
         return(-1);                 // failed, not a pullback
      if(MathAbs(c - reference) <= tol)
         return(i);
     }
   return(-1);
  }

//+------------------------------------------------------------------+
//| AlB_AnalyzeBreakout -- `setups/breakout.py::analyze_breakout`.     |
//|                                                                    |
//|  The search loop runs over `idx .. idx - f_bars` INCLUSIVE -- six  |
//|  bars, not five. `max(-1, idx - f_bars - 1)` is the stop of a       |
//|  `range` whose first argument is `idx`, and a range with a stop of  |
//|  `idx-6` visits six values. Stopping one bar earlier drops the      |
//|  oldest candidate and changes which break is found.                |
//+------------------------------------------------------------------+
void AlB_AnalyzeBreakout(const ABBar &bars[],
                         const int count,
                         const int idx,
                         const int last_closed,
                         const double atr,
                         const ABSwing &swings[],
                         const int nswings,
                         ABBreakout &out)
  {
   AlB_ResetBreakout(out);
   if(idx < 0 || idx > last_closed || idx >= count || atr <= 0.0)
      return;

   const double tol = AB_BO_TOL_ATR * atr;
   int k = -1;
   double ref = 0.0;
   bool is_sw = false;
   int direction = 0;

   const int stop = MathMax(-1, idx - AB_BO_F_BARS - 1);
   for(int kk = idx; kk > stop; kk--)
     {
      if(kk < 0)
         continue;
      double rp = 0.0;
      bool sw = false;
      const int d = AlB_DetectBreakoutEvent(bars, count, kk, last_closed, atr,
                                            swings, nswings, 20, AB_BO_TOL_ATR, rp, sw);
      if(d != 0)
        {
         k = kk;
         ref = rp;
         is_sw = sw;
         direction = d;
         break;
        }
     }

   if(k < 0)
      return;

   out.found           = true;
   out.breakout_bar    = k;
   out.reference_price = ref;
   out.ref_is_swing    = is_sw;
   out.direction       = direction;

   string outcome = "PENDING";
   int decide_bar = -1;
   const int fb = AlB_FailedSince(bars, count, idx + 1, k, ref, direction, tol);
   if(fb >= 0)
     {
      outcome     = "FAILED";
      decide_bar  = fb;
     }
   else
     {
      for(int j = idx; j > k; j--)
        {
         const double c = bars[j].close;
         if(direction > 0 && c > ref + tol)
           {
            outcome    = "FOLLOW";
            decide_bar = j;
            break;
           }
         if(direction < 0 && c < ref - tol)
           {
            outcome    = "FOLLOW";
            decide_bar = j;
            break;
           }
        }
     }
   out.outcome    = outcome;
   out.decide_bar = decide_bar;

   for(int m = MathMax(0, k - AB_BO_T_BARS); m < k; m++)
     {
      if(m > last_closed)
         continue;
      double rp = 0.0;
      bool sw = false;
      const int d = AlB_DetectBreakoutEvent(bars, count, m, last_closed, atr,
                                            swings, nswings, 20, AB_BO_TOL_ATR, rp, sw);
      if(d != direction)
         continue;
      if(AlB_FailedSince(bars, count, k + 1, m, rp, direction, tol) >= 0)
        {
         out.trap = true;
         break;
        }
     }

   out.second_leg_bar = AlB_SecondLegTrap(bars, count, k, last_closed, ref, direction,
                                         tol, AB_BO_LEG2_BARS);
   out.pullback_bar   = AlB_BreakoutPullback(bars, count, k, last_closed, ref, direction,
                                              tol, AB_BO_PB_BARS);

   if(outcome == "FAILED")
      out.state = "FAILED";
   else
      if(outcome == "FOLLOW")
         out.state = "FOLLOW_THROUGH";
      else
         out.state = (idx == k) ? "BREAKOUT" : "PENDING";
  }

// ---------------------------------------------------------------------------
// Reversal
// ---------------------------------------------------------------------------

//+------------------------------------------------------------------+
int AlB_EmaSide(const double close, const double ema, const double tol)
  {
   if(close > ema + tol)
      return(1);
   if(close < ema - tol)
      return(-1);
   return(0);
  }

//+------------------------------------------------------------------+
//| AlB_AnalyzeReversal -- `setups/reversal.py::analyze_reversal`.      |
//|                                                                    |
//|  Returns `found`, which is `verdict != "NONE"`, i.e. **at least   |
//|  one leg satisfied** -- not all four. Reading it as "all four" is  |
//|  the difference between a MINOR reversal firing and nothing firing, |
//|  and the registry records both as the same boolean.                |
//|                                                                    |
//|  `direction` is the requested reversal direction and is returned   |
//|  even when nothing was found, because that is what the Python's    |
//|  `ReversalResult` does.                                            |
//+------------------------------------------------------------------+
bool AlB_AnalyzeReversal(const ABBar &bars[],
                         const int count,
                         const int idx,
                         const int last_closed,
                         const double atr,
                         const ABSwing &swings[],
                         const int nswings,
                         const int reversal_direction,
                         int &out_direction,
                         int &out_legs)
  {
   out_direction = reversal_direction;
   out_legs = 0;
   if(reversal_direction != 1 && reversal_direction != -1)
      return(false);
   if(idx < 0 || idx > last_closed || idx >= count || atr <= 0.0)
      return(false);
   if(idx + 1 < AB_CROSS_LOOKBACK + 2)
      return(false);

   const double tol = AB_EMA_TOL_ATR * atr;

   // EMA20 at every index, forward from the first close.
   double ema[];
   ArrayResize(ema, count);
   ArrayInitialize(ema, 0.0);
   const double k = 2.0 / 21.0;
   double e = bars[0].close;
   for(int i = 1; i <= idx; i++)
     {
      e = bars[i].close * k + e * (1.0 - k);
      ema[i] = e;
     }

   if(AlB_EmaSide(bars[idx].close, ema[idx], tol) != reversal_direction)
      return(false);

   // Leg 1: where price crossed to the reversal side.
   int cross_bar = -1;
   for(int j = idx - 1; j > MathMax(-1, idx - AB_CROSS_LOOKBACK); j--)
     {
      if(AlB_EmaSide(bars[j].close, ema[j], tol) == -reversal_direction)
        {
         cross_bar = j;
         break;
        }
     }
   if(cross_bar < 0)
      return(false);

   int leg_count = 1;   // ema_break

   // Leg 2: price returns to the EMA and holds on the far side.
   bool retest = false;
   for(int j = cross_bar + 1; j <= idx; j++)
     {
      const double ee = ema[j];
      if(reversal_direction > 0 && bars[j].low <= ee + tol && bars[j].close > ee - tol)
        {
         retest = true;
         break;
        }
      if(reversal_direction < 0 && bars[j].high >= ee - tol && bars[j].close < ee + tol)
        {
         retest = true;
         break;
        }
     }
   if(retest)
      leg_count++;

   // Leg 3: the swing structure breaks with the reversal, and has followed
   // through. A break that is still PENDING does not count.
   ABBreakout bo;
   AlB_AnalyzeBreakout(bars, count, idx, last_closed, atr, swings, nswings, bo);
   if(bo.found && bo.direction == reversal_direction && bo.outcome == "FOLLOW")
      leg_count++;

   // Leg 4: consecutive pushes overwhelming the old trend.
   const int pressure = AlB_PushCountBack(bars, count, idx, last_closed,
                                          reversal_direction, AB_MAX_RUN_SCAN);
   if(pressure >= AB_PRESSURE_PUSHES)
      leg_count++;

   out_legs = leg_count;
   return(leg_count >= 1);
  }

//+------------------------------------------------------------------+
int AlB_ReversalCrossBar(const ABBar &bars[],
                         const int count,
                         const int idx,
                         const int last_closed,
                         const double atr,
                         const int reversal_direction)
  {
   if(reversal_direction != 1 && reversal_direction != -1)
      return(-1);
   if(idx < 0 || idx > last_closed || idx >= count || atr <= 0.0)
      return(-1);
   if(idx + 1 < AB_CROSS_LOOKBACK + 2)
      return(-1);
   const double tol = AB_EMA_TOL_ATR * atr;
   double ema[];
   ArrayResize(ema, count);
   ArrayInitialize(ema, 0.0);
   const double k = 2.0 / 21.0;
   double e = bars[0].close;
   for(int i = 1; i <= idx; i++)
     {
      e = bars[i].close * k + e * (1.0 - k);
      ema[i] = e;
     }
   if(AlB_EmaSide(bars[idx].close, ema[idx], tol) != reversal_direction)
      return(-1);
   for(int j = idx - 1; j > MathMax(-1, idx - AB_CROSS_LOOKBACK); j--)
      if(AlB_EmaSide(bars[j].close, ema[j], tol) == -reversal_direction)
         return(j);
   return(-1);
  }

// ---------------------------------------------------------------------------
// Double tops and bottoms
// ---------------------------------------------------------------------------

//+------------------------------------------------------------------+
//| AlB_DetectMicroDoubleTop -- `setups/double.py::                    |
//| detect_micro_double_top`, which reads bars and not swings.          |
//|                                                                   |
//|  The loops run j DOWNWARD from idx and i downward from j, so the   |
//|  FIRST pattern found is the one with the most recent second leg -- |
//|  and within that, the most recent first leg. Reversing either      |
//|  direction picks a different pair, and both bar indices are in    |
//|  the plan's `signal_bar`.                                         |
//+------------------------------------------------------------------+
bool AlB_DetectMicroDoubleTop(const ABBar &bars[],
                              const int count,
                              const int idx,
                              const int last_closed,
                              const double atr,
                              int &bar1, int &bar2, double &price1, double &price2)
  {
   bar1 = -1;
   bar2 = -1;
   if(idx < 0 || idx > last_closed || idx >= count || atr <= 0.0)
      return(false);

   const int w = 5;
   const int w0 = MathMax(0, idx - w + 1);
   if(idx - w0 + 1 < 3)
      return(false);
   const double tol = AB_DOUBLE_TOL_ATR * atr;
   const double need = 0.50 * atr * 0.5;

   for(int j = idx; j >= w0; j--)
     {
      const double h_j = bars[j].high;
      for(int i = j - 1; i >= w0; i--)
        {
         const double h_i = bars[i].high;
         if(MathAbs(h_j - h_i) > tol)
            continue;
         const double base = MathMin(h_i, h_j);
         bool ok = false;
         for(int k2 = i + 1; k2 < j; k2++)
            if(base - bars[k2].low >= need)
              {
               ok = true;
               break;
              }
         if(!ok)
            continue;
         bar1 = i;
         bar2 = j;
         price1 = h_i;
         price2 = h_j;
         return(true);
        }
     }
   return(false);
  }

//+------------------------------------------------------------------+
bool AlB_FindMajorDoubleTop(const ABSwing &swings[],
                            const int n,
                            const double atr,
                            int &bar1, int &bar2, double &price1, double &price2)
  {
   bar1 = -1;
   bar2 = -1;
   if(n == 0 || atr <= 0.0)
      return(false);
   const double tol = AB_DOUBLE_TOL_ATR * atr;
   const double need = 0.50 * atr;

   for(int j = n - 1; j >= 0; j--)
     {
      if(swings[j].direction != 1)
         continue;
      for(int i = j - 1; i >= 0; i--)
        {
         if(swings[i].direction != 1)
            continue;
         if(MathAbs(swings[j].price - swings[i].price) > tol)
            continue;
         if(swings[j].bar_index - swings[i].bar_index > 20)
            continue;
         const double base = MathMin(swings[i].price, swings[j].price);
         bool ok = false;
         for(int k2 = i + 1; k2 < j; k2++)
            if(swings[k2].direction == -1 && (base - swings[k2].price) >= need)
              {
               ok = true;
               break;
              }
         if(!ok)
            continue;
         bar1 = swings[i].bar_index;
         bar2 = swings[j].bar_index;
         price1 = swings[i].price;
         price2 = swings[j].price;
         return(true);
        }
     }
   return(false);
  }

//+------------------------------------------------------------------+
bool AlB_FindMajorDoubleBottom(const ABSwing &swings[],
                               const int n,
                               const double atr,
                               int &bar1, int &bar2, double &price1, double &price2)
  {
   bar1 = -1;
   bar2 = -1;
   if(n == 0 || atr <= 0.0)
      return(false);
   const double tol = AB_DOUBLE_TOL_ATR * atr;
   const double need = 0.50 * atr;

   for(int j = n - 1; j >= 0; j--)
     {
      if(swings[j].direction != -1)
         continue;
      for(int i = j - 1; i >= 0; i--)
        {
         if(swings[i].direction != -1)
            continue;
         if(MathAbs(swings[j].price - swings[i].price) > tol)
            continue;
         if(swings[j].bar_index - swings[i].bar_index > 20)
            continue;
         const double base = MathMax(swings[i].price, swings[j].price);
         bool ok = false;
         for(int k2 = i + 1; k2 < j; k2++)
            if(swings[k2].direction == 1 && (swings[k2].price - base) >= need)
              {
               ok = true;
               break;
              }
         if(!ok)
            continue;
         bar1 = swings[i].bar_index;
         bar2 = swings[j].bar_index;
         price1 = swings[i].price;
         price2 = swings[j].price;
         return(true);
        }
     }
   return(false);
  }

//+------------------------------------------------------------------+
//| AlB_DetectMicroDoubleBottom -- `setups/double.py::                  |
//| detect_micro_double_bottom`. The mirror of the top, with the sign  |
//| of the separating move flipped.                                   |
//+------------------------------------------------------------------+
bool AlB_DetectMicroDoubleBottom(const ABBar &bars[],
                                 const int count,
                                 const int idx,
                                 const int last_closed,
                                 const double atr,
                                 int &bar1, int &bar2, double &price1, double &price2)
  {
   bar1 = -1;
   bar2 = -1;
   if(idx < 0 || idx > last_closed || idx >= count || atr <= 0.0)
      return(false);

   const int w = 5;
   const int w0 = MathMax(0, idx - w + 1);
   if(idx - w0 + 1 < 3)
      return(false);
   const double tol = AB_DOUBLE_TOL_ATR * atr;
   const double need = 0.50 * atr * 0.5;

   for(int j = idx; j >= w0; j--)
     {
      const double l_j = bars[j].low;
      for(int i = j - 1; i >= w0; i--)
        {
         const double l_i = bars[i].low;
         if(MathAbs(l_j - l_i) > tol)
            continue;
         const double base = MathMax(l_i, l_j);
         bool ok = false;
         for(int k2 = i + 1; k2 < j; k2++)
            if(bars[k2].high - base >= need)
              {
               ok = true;
               break;
              }
         if(!ok)
            continue;
         bar1 = i;
         bar2 = j;
         price1 = l_i;
         price2 = l_j;
         return(true);
        }
     }
   return(false);
  }

// ---------------------------------------------------------------------------
// Measured moves
// ---------------------------------------------------------------------------

//+------------------------------------------------------------------+
double AlB_MmDepth(const int direction,
                   const double leg_extreme,
                   const double pullback_price,
                   const double mm_range)
  {
   if(direction > 0)
      return((leg_extreme - pullback_price) / mm_range);
   return((pullback_price - leg_extreme) / mm_range);
  }

//+------------------------------------------------------------------+
//| AlB_LegGeometry -- the direction and measured range of a           |
//| low-high-low or high-low-high triple, or found = false.           |
//|                                                                    |
//|  `found` rather than a sentinel direction, because direction 0 is  |
//|  a legitimate value in a projection (`project_range` produces one) |
//|  and cannot double as "no such triple".                            |
//+------------------------------------------------------------------+
bool AlB_LegGeometry(const ABSwing &s0,
                     const ABSwing &s1,
                     const ABSwing &sb,
                     int &direction,
                     double &mm_range)
  {
   direction = 0;
   mm_range  = 0.0;
   if(s0.direction == -1 && s1.direction == 1 && sb.direction == -1)
     {
      direction = 1;
      mm_range  = s1.price - s0.price;
      return(true);
     }
   if(s0.direction == 1 && s1.direction == -1 && sb.direction == 1)
     {
      direction = -1;
      mm_range  = s0.price - s1.price;
      return(true);
     }
   return(false);
  }

//+------------------------------------------------------------------+
void AB_ResetProjection(ABProjection &p)
  {
   p.found            = false;
   p.family           = "NONE";
   p.direction        = 0;
   p.target_price     = 0.0;
   p.mm_range         = 0.0;
   p.origin_bar       = -1;
   p.anchor_bar       = -1;
   p.reference_price  = 0.0;
   p.pullback_depth   = 0.0;
   p.origin_price     = 0.0;
   p.origin_bar_index = -1;
   p.w_scale          = 0.0;
   p.w_structure      = 0.0;
  }

//+------------------------------------------------------------------+
//| AlB_Ramp -- a linear 0..1 ramp reaching 1.0 at `full`.           |
//+------------------------------------------------------------------+
double AlB_Ramp(const double value, const double full)
  {
   if(full <= 0.0)
      return(0.0);
   return(AlB_Clamp01(value / full));
  }

//+------------------------------------------------------------------+
//| AlB_BandQuality -- 1.0 at the centre of `[low, high]`, falling   |
//| linearly to 0.0 at each edge.                                     |
//|                                                                    |
//|  The edges score 0.0 rather than something small but positive, so |
//|  "at the limit" and "not really in the band" cannot be confused   |
//|  for a graded difference.                                          |
//+------------------------------------------------------------------+
double AlB_BandQuality(const double value, const double low, const double high)
  {
   if(high <= low)
      return(0.0);
   const double mid = (low + high) / 2.0;
   const double half = (high - low) / 2.0;
   return(AlB_Clamp01(1.0 - MathAbs(value - mid) / half));
  }

//+------------------------------------------------------------------+
//| AlB_ProjectLegEquality -- `project_leg_equality`, and with the     |
//| channel band swapped in, `project_channel`.                       |
//|                                                                    |
//|  One function for both, because the Python's two are the same     |
//|  algorithm with one comparison changed -- and that is exactly     |
//|  where a port drifts: writing them out separately invites the      |
//|  channel's `depth < min_pb_ratio` to become `<=`, which silently   |
//|  admits a depth of exactly 0.15 to both families at once.         |
//|                                                                    |
//|  The gate order is preserved exactly, because a gate that moves    |
//|  changes which projection is reported and therefore the count.     |
//+------------------------------------------------------------------+
bool AlB_ProjectSwingTriple(const ABSwing &s0,
                            const ABSwing &s1,
                            const ABSwing &sb,
                            const double atr,
                            const bool channel,
                            ABProjection &out)
  {
   AB_ResetProjection(out);
   if(atr <= 0.0)
      return(false);
   if(!(s0.bar_index < s1.bar_index && s1.bar_index < sb.bar_index))
      return(false);

   int direction = 0;
   double mm_range = 0.0;
   if(!AlB_LegGeometry(s0, s1, sb, direction, mm_range))
      return(false);
   if(mm_range <= 0.0)
      return(false);

   const int leg_bars = s1.bar_index - s0.bar_index;
   if(!(leg_bars >= AB_MIN_LEG_BARS && leg_bars <= AB_MAX_LEG_BARS))
      return(false);
   if(mm_range < AB_MIN_LEG_ATR * atr)
      return(false);

   const double depth = AlB_MmDepth(direction, s1.price, sb.price, mm_range);
   if(channel)
     {
      if(!(depth >= AB_MM_CHANNEL_MIN_DEPTH && depth < AB_MIN_PB_RATIO))
         return(false);
     }
   else
     {
      if(!(depth >= AB_MIN_PB_RATIO && depth <= AB_MAX_PB_RATIO))
         return(false);
     }

   if(sb.bar_index - s1.bar_index > AB_MAX_PB_BARS)
      return(false);

   out.found            = true;
   out.family           = channel ? AB_MM_CHANNEL : AB_MM_REGULAR;
   out.direction        = direction;
   out.target_price     = sb.price + direction * mm_range;
   out.mm_range         = mm_range;
   out.origin_bar       = s0.bar_index;
   out.anchor_bar       = sb.bar_index;
   out.reference_price  = sb.price;
   out.pullback_depth   = depth;
   out.origin_price     = sb.price;
   out.origin_bar_index = sb.bar_index;
   out.w_scale          = AlB_Ramp(mm_range, AB_MM_SCALE_FULL_ATR * atr);
   // Scored against the family's OWN band: a depth of 0.08 is mid-band for a
   // channel and a reject for a regular pullback, so the same number is not
   // comparable across the two.
   out.w_structure      = channel
                          ? AlB_BandQuality(depth, AB_MM_CHANNEL_MIN_DEPTH, AB_MIN_PB_RATIO)
                          : AlB_BandQuality(depth, AB_MIN_PB_RATIO, AB_MAX_PB_RATIO);
   return(true);
  }

//+------------------------------------------------------------------+
bool AlB_ProjectRange(const ABBar &bars[],
                      const int count,
                      const int bo_idx,
                      const double atr,
                      ABProjection &out)
  {
   AB_ResetProjection(out);
   if(atr <= 0.0)
      return(false);
   if(bo_idx < 1 || bo_idx >= count)
      return(false);

   const int lookback = AB_RANGE_LOOKBACK;
   const int start_idx = bo_idx - lookback;
   if(lookback < 1 || start_idx < 0)
      return(false);

   double hh = bars[start_idx].high, ll = bars[start_idx].low;
   for(int i = start_idx + 1; i < bo_idx; i++)
     {
      if(bars[i].high > hh)
         hh = bars[i].high;
      if(bars[i].low < ll)
         ll = bars[i].low;
     }
   const double height = hh - ll;
   if(height < AB_MIN_LEG_ATR * atr)
      return(false);

   const double bo_c = bars[bo_idx].close;
   int direction = 0;
   if(bo_c > hh)
      direction = 1;
   else
      if(bo_c < ll)
         direction = -1;
      else
         return(false);

   out.found            = true;
   out.family           = AB_MM_RANGE;
   out.direction        = direction;
   out.target_price     = bo_c + direction * height;
   out.mm_range         = height;
   out.origin_bar       = start_idx;
   out.anchor_bar       = bo_idx;
   out.reference_price  = bo_c;
   out.pullback_depth   = 0.0;
   out.origin_price     = bo_c;
   out.origin_bar_index = bo_idx;
   out.w_scale          = AlB_Ramp(height, AB_MM_SCALE_FULL_ATR * atr);
   // How far the close cleared the range edge. A breakout that barely exceeded
   // the extreme is the one most likely to fall back into the range.
   out.w_structure      = AlB_Ramp(MathAbs(bo_c - ((direction > 0) ? hh : ll)),
                                   AB_MM_STRUCTURE_FULL_ATR * atr);
   return(true);
  }

//+------------------------------------------------------------------+
bool AlB_ProjectGap(const ABBar &bars[],
                    const int count,
                    const int gap_idx,
                    const double atr,
                    ABProjection &out)
  {
   AB_ResetProjection(out);
   if(atr <= 0.0)
      return(false);
   if(gap_idx < 1 || gap_idx >= count)
      return(false);

   const double curr_h = bars[gap_idx].high;
   const double curr_l = bars[gap_idx].low;
   const double curr_c = bars[gap_idx].close;
   const double prev_h = bars[gap_idx - 1].high;
   const double prev_l = bars[gap_idx - 1].low;

   const double rg = curr_h - curr_l;
   if(rg <= 0.0 || rg < AB_MIN_GAP_ATR * atr)
      return(false);

   const bool bull_gap = (curr_l > prev_h) && ((curr_c - curr_l) / rg >= 0.75);
   const bool bear_gap = (curr_h < prev_l) && ((curr_h - curr_c) / rg >= 0.75);
   if(!bull_gap && !bear_gap)
      return(false);

   const int direction = bull_gap ? 1 : -1;
   const double gap_size = bull_gap ? (curr_c - prev_h) : (prev_l - curr_c);
   if(gap_size < 0.25 * atr)
      return(false);

   out.found            = true;
   out.family           = AB_MM_GAP;
   out.direction        = direction;
   out.target_price     = curr_c + direction * gap_size;
   out.mm_range         = gap_size;
   out.origin_bar       = gap_idx - 1;
   out.anchor_bar       = gap_idx;
   out.reference_price  = curr_c;
   out.pullback_depth   = 0.0;
   out.origin_price     = curr_c;
   out.origin_bar_index = gap_idx;
   out.w_scale          = AlB_Ramp(gap_size, AB_MM_SCALE_FULL_ATR * atr);
   // The gate already requires a close in the extreme 25% of the bar. Within
   // that accepted range, a close on the very edge outranks one near the 0.75
   // boundary, which is the marginal case the gate lets through.
   const double close_strength = bull_gap ? ((curr_c - curr_l) / rg) : ((curr_h - curr_c) / rg);
   out.w_structure      = AlB_Clamp01((close_strength - 0.75) / 0.25);
   return(true);
  }

//+------------------------------------------------------------------+
//| AlB_ProjectInverse -- `project_inverse`, the failed-breakout       |
//| projection.                                                       |
//|                                                                    |
//|  The anchor is the FAR side of the failure bar, which is the       |
//|  conservative choice and the one that makes the two branches       |
//|  asymmetric: the bull leg's anchor is the low of the bar that made  |
//|  the extreme HIGH, and the bear leg's is the high of the bar that   |
//|  made the extreme LOW. Using the failure bar's own opposite        |
//|  extreme in either case gives a different target.                  |
//+------------------------------------------------------------------+
bool AlB_ProjectInverse(const ABBar &bars[],
                        const int count,
                        const ABLeg &leg,
                        const double atr,
                        const int last_closed,
                        ABProjection &out)
  {
   AB_ResetProjection(out);
   if(atr <= 0.0)
      return(false);
   const int direction = leg.direction;
   if(direction != 1 && direction != -1)
      return(false);
   if(leg.price_change < AB_MIN_LEG_ATR * atr)
      return(false);

   const int upper = MathMin(last_closed, count - 1);
   const int from_bar = leg.end_index + 1;
   const int to_bar = MathMin(upper, leg.end_index + AB_FAILED_BO_BARS);
   if(from_bar > to_bar)
      return(false);

   const double ext = leg.end_price;
   int break_bar = -1;
   int fail_bar = -1;
   double fail_close = 0.0;

   if(direction > 0)
     {
      double extreme_high = 0.0, extreme_low = 0.0;
      for(int s = from_bar; s <= to_bar; s++)
        {
         const double bh = bars[s].high, bl = bars[s].low, bc = bars[s].close;
         if(bh > extreme_high)
           {
            extreme_high = bh;
            extreme_low  = bl;
           }
         if(bc > ext)
           {
            break_bar = s;
            break;
           }
        }
      if(break_bar < 0 || extreme_high <= ext)
         return(false);
      for(int t = break_bar + 1; t <= to_bar; t++)
        {
         const double th = bars[t].high, tl = bars[t].low, tc = bars[t].close;
         if(th > extreme_high)
           {
            extreme_high = th;
            extreme_low  = tl;
           }
         if(tc < ext)
           {
            fail_bar = t;
            fail_close = tc;
            break;
           }
        }
      if(fail_bar < 0)
         return(false);
      const double target = extreme_low - leg.price_change;
      if(target >= extreme_low)
         return(false);

      out.found            = true;
      out.family           = AB_MM_INVERSE;
      out.direction        = -1;
      out.target_price     = target;
      out.mm_range         = leg.price_change;
      out.origin_bar       = leg.start_index;
      out.anchor_bar       = fail_bar;
      out.reference_price  = extreme_low;
      out.pullback_depth   = 0.0;
      out.origin_price     = extreme_low;
      out.origin_bar_index = fail_bar;
      out.w_scale          = AlB_Ramp(leg.price_change, AB_MM_SCALE_FULL_ATR * atr);
      // The reclaim has to close back through the leg extreme to count at all,
      // so the factor grades how decisively it did rather than whether.
      out.w_structure      = AlB_Ramp(MathAbs(ext - fail_close),
                                      AB_MM_STRUCTURE_FULL_ATR * atr);
      return(true);
     }

   // The low of the most bearish bar seen so far, and that bar's index.
   double lowest = 0.0;
   int low_bar = -1;
   bool have_lowest = false;
   for(int s = from_bar; s <= to_bar; s++)
     {
      const double bl = bars[s].low, bc = bars[s].close;
      if(!have_lowest || bl < lowest)
        {
         lowest = bl;
         low_bar = s;
         have_lowest = true;
        }
      if(bc < ext)
        {
         break_bar = s;
         break;
        }
     }
   if(break_bar < 0 || !have_lowest || low_bar < from_bar || !(lowest < ext))
      return(false);
   for(int t = break_bar + 1; t <= to_bar; t++)
     {
      const double tl = bars[t].low, tc = bars[t].close;
      if(tl < lowest)
        {
         lowest = tl;
         low_bar = t;
        }
      if(tc > ext)
        {
         fail_bar = t;
         fail_close = tc;
         break;
        }
     }
   if(fail_bar < 0)
      return(false);
   const double anchor_high = bars[low_bar].high;

   out.found            = true;
   out.family           = AB_MM_INVERSE;
   out.direction        = 1;
   out.target_price     = anchor_high + leg.price_change;
   out.mm_range         = leg.price_change;
   out.origin_bar       = leg.start_index;
   out.anchor_bar       = fail_bar;
   out.reference_price  = anchor_high;
   out.pullback_depth   = 0.0;
   out.origin_price     = anchor_high;
   out.origin_bar_index = fail_bar;
   out.w_scale          = AlB_Ramp(leg.price_change, AB_MM_SCALE_FULL_ATR * atr);
   out.w_structure      = AlB_Ramp(MathAbs(ext - fail_close),
                                   AB_MM_STRUCTURE_FULL_ATR * atr);
   return(true);
  }

//+------------------------------------------------------------------+
//| AlB_ProjectionsEqual -- the de-duplication key, without the key.  |
//+------------------------------------------------------------------+
bool AlB_ProjectionsEqual(const ABProjection &a, const ABProjection &b)
  {
   if(a.family != b.family)
      return(false);
   if(a.direction != b.direction)
      return(false);
   if(a.anchor_bar != b.anchor_bar)
      return(false);
   return(AB_Round9(a.target_price) == AB_Round9(b.target_price));
  }

//+------------------------------------------------------------------+
void AppendProjection(ABProjection &all[], const ABProjection &p)
  {
   const int k = ArraySize(all);
   ArrayResize(all, k + 1);
   all[k] = p;
  }

//+------------------------------------------------------------------+
//| AlB_DetectMeasuredMoves -- `measured_move.detect_measured_moves`.  |
//|                                                                    |
//|  The no-lookahead filter is on `confirmed_bar` AND on `bar`, and   |
//|  both matter: a right-side-confirmed fractal whose pivot is older |
//|  is only known from the later bar, and admitting it on its pivot   |
//|  index alone would let a projection use evidence that did not      |
//|  exist at `last_closed`.                                          |
//|                                                                    |
//|  `recent_swings` is a SLICE, not a filter by age, and it is the    |
//|  most recent N -- so it keeps the tail of the list.               |
//+------------------------------------------------------------------+
int AlB_DetectMeasuredMoves(const ABBar &bars[],
                            const int count,
                            const ABSwing &swings[],
                            const int nswings,
                            const double atr,
                            const int last_closed,
                            const ABLeg &legs[],
                            const int nlegs,
                            ABProjection &out[])
  {
   ArrayResize(out, 0);
   if(count == 0 || atr <= 0.0)
      return(0);
   const int closed = MathMin(last_closed, count - 1);
   if(closed < 0)
      return(0);

   // --- the confirmed swings this run may use ---------------------------
   ABSwing confirmed[];
   ArrayResize(confirmed, 0);
   for(int i = 0; i < nswings; i++)
     {
      if(swings[i].confirmed_bar_index >= 0 && swings[i].confirmed_bar_index > closed)
         continue;
      if(swings[i].bar_index > closed)
         continue;
      const int k = ArraySize(confirmed);
      ArrayResize(confirmed, k + 1);
      confirmed[k] = swings[i];
     }
   if(AB_MM_RECENT_SWINGS > 0)
     {
      const int keep = MathMin(AB_MM_RECENT_SWINGS, ArraySize(confirmed));
      for(int i = 0; i < keep; i++)
         confirmed[i] = confirmed[ArraySize(confirmed) - keep + i];
      ArrayResize(confirmed, keep);
     }

   const int nconfirmed = ArraySize(confirmed);
   ABProjection all[];
   ArrayResize(all, 0);

   for(int i = 0; i < nconfirmed - 2; i++)
     {
      ABProjection p;
      if(AlB_ProjectSwingTriple(confirmed[i], confirmed[i + 1], confirmed[i + 2],
                                atr, false, p))
        AppendProjection(all, p);
      if(AlB_ProjectSwingTriple(confirmed[i], confirmed[i + 1], confirmed[i + 2],
                                atr, true, p))
        AppendProjection(all, p);
     }

   ABProjection p;
   if(AlB_ProjectRange(bars, count, closed, atr, p))
      AppendProjection(all, p);
   if(AlB_ProjectGap(bars, count, closed, atr, p))
      AppendProjection(all, p);

   // --- inverse, over the most recent legs -----------------------------
   ABLeg to_check[];
   ArrayResize(to_check, 0);
   if(nlegs > 0)
     {
      for(int i = 0; i < nlegs; i++)
        {
         const int k = ArraySize(to_check);
         ArrayResize(to_check, k + 1);
         to_check[k] = legs[i];
        }
     }
   else
     {
      for(int i = 0; i < nconfirmed - 1; i++)
        {
         const int k = ArraySize(to_check);
         ArrayResize(to_check, k + 1);
         to_check[k].start_index     = confirmed[i].bar_index;
         to_check[k].end_index       = confirmed[i + 1].bar_index;
         to_check[k].start_price     = confirmed[i].price;
         to_check[k].end_price       = confirmed[i + 1].price;
         to_check[k].price_change    = MathAbs(confirmed[i + 1].price - confirmed[i].price);
         to_check[k].confirmed_index = 0;
         to_check[k].bars_count      = 0;
         to_check[k].direction       = 0;   // derived below, as `_leg_fields` does
        }
     }
   if(AB_MM_MAX_INVERSE_LEGS > 0 && ArraySize(to_check) > 0)
     {
      const int start = MathMax(0, ArraySize(to_check) - AB_MM_MAX_INVERSE_LEGS);
      for(int i = start; i < ArraySize(to_check); i++)
        {
         ABLeg leg = to_check[i];
         if(leg.direction == 0)
            leg.direction = (leg.end_price > leg.start_price) ? 1 : -1;
         if(AlB_ProjectInverse(bars, count, leg, atr, closed, p))
            AppendProjection(all, p);
        }
     }

   // --- de-duplicate, keeping the first occurrence ----------------------
   ArrayResize(out, 0);
   for(int i = 0; i < ArraySize(all); i++)
     {
      bool seen = false;
      for(int j = 0; j < ArraySize(out); j++)
         if(AlB_ProjectionsEqual(all[i], out[j]))
           {
            seen = true;
            break;
           }
      if(!seen)
        {
         const int k = ArraySize(out);
         ArrayResize(out, k + 1);
         out[k] = all[i];
        }
     }
   return(ArraySize(out));
  }

// ---------------------------------------------------------------------------
// The registry
// ---------------------------------------------------------------------------

//+------------------------------------------------------------------+
//| AB_FamilyFor -- `setups/base.py::FAMILY_BY_DETECTOR` +             |
//| `family_for`.                                                      |
//|                                                                    |
//|  One table, not two. The Python owns it in one place precisely      |
//|  because the pipeline's grouping, the plan layer's anatomy lookup   |
//|  and the decision layer's evidence adapters all need the same       |
//|  answer, and a second copy is a second thing to keep in step.        |
//+------------------------------------------------------------------+
string AB_FamilyFor(string detector)
  {
   if(detector == "PULLBACK_H"        || detector == "PULLBACK_L")        return("PULLBACK");
   if(detector == "BREAKOUT")                                       return("BREAKOUT");
   if(detector == "REVERSAL_BULL"    || detector == "REVERSAL_BEAR")    return("REVERSAL");
   if(detector == "DOUBLE_TOP_MAJOR" || detector == "DOUBLE_TOP_MICRO")  return("DOUBLE_TOP");
   if(detector == "DOUBLE_BOTTOM_MAJOR" || detector == "DOUBLE_BOTTOM_MICRO")
      return("DOUBLE_BOTTOM");
   if(detector == "MEASURED_MOVE")                                  return("MEASURED_MOVE");
   if(detector == "FADING_MEASURED_MOVE")                           return("FADING_MEASURED_MOVE");
   return("UNKNOWN");
  }

//+------------------------------------------------------------------+
void AB_AddFinding(ABSetupFinding &findings[],
                   const string &detector,
                   const string &kind,
                   const int direction,
                   const bool has_setup_type,
                   const string &setup_type,
                   const ABSetupPayload &payload)
  {
   const int k = ArraySize(findings);
   ArrayResize(findings, k + 1);
   findings[k].detector       = detector;
   findings[k].kind           = kind;
   findings[k].direction      = direction;
   findings[k].has_setup_type = has_setup_type;
   findings[k].setup_type     = setup_type;
   findings[k].payload        = payload;
  }

//+------------------------------------------------------------------+
//| AlB_RunRegistry -- `SetupRegistry.run` over `build_default_        |
//| registry()`, in registration order.                               |
//|                                                                    |
//|  Registration order, and it is NOT a ranking: it is the order the  |
//|  eleven detectors are declared in `registry.py`, and the port      |
//|  follows it exactly so a diff of two runs lines up finding for    |
//|  finding. The comparator sorts lists anyway, so this costs nothing  |
//|  and buys a readable file.                                         |
//|                                                                    |
//|  `skip_if_unusable` is honoured: with no volatility, every        |
//|  detector would otherwise report a confident "nothing found" on a  |
//|  market that was never measured.                                   |
//+------------------------------------------------------------------+
int AlB_RunRegistry(const ABBar &bars[],
                    const int count,
                    const int idx,
                    const int last_closed,
                    const double atr,
                    const ABSwing &swings[],
                    const int nswings,
                    const ABLeg &legs[],
                    const int nlegs,
                    ABSetupFinding &findings[])
  {
   ArrayResize(findings, 0);
   if(atr <= 0.0 || last_closed < 0)
      return(0);

   ABSetupPayload p;

   // --- 1. PULLBACK_H ----------------------------------------------------
   ABPullback pb;
   AlB_DetectPullback(bars, count, idx, last_closed, atr, 1, pb);
   if(pb.found)
     {
      AB_ResetPayload(p);
      p.direction       = pb.direction;
      p.reference_price = pb.reference_price;
      p.stop_price      = pb.stop_price;
      p.signal_bar      = pb.signal_bar;
      p.anchor_bar      = pb.anchor_bar;
      p.extreme_price   = pb.extreme_price;
      p.state           = pb.state;
      AB_AddFinding(findings, "PULLBACK_H", "DEFAULT", pb.direction,
                    true, pb.setup_type, p);
     }

   // --- 2. PULLBACK_L ----------------------------------------------------
   AlB_DetectPullback(bars, count, idx, last_closed, atr, -1, pb);
   if(pb.found)
     {
      AB_ResetPayload(p);
      p.direction       = pb.direction;
      p.reference_price = pb.reference_price;
      p.stop_price      = pb.stop_price;
      p.signal_bar      = pb.signal_bar;
      p.anchor_bar      = pb.anchor_bar;
      p.extreme_price   = pb.extreme_price;
      p.state           = pb.state;
      AB_AddFinding(findings, "PULLBACK_L", "DEFAULT", pb.direction,
                    true, pb.setup_type, p);
     }

   // --- 3. BREAKOUT ------------------------------------------------------
   ABBreakout bo;
   AlB_AnalyzeBreakout(bars, count, idx, last_closed, atr, swings, nswings, bo);
   if(bo.found)
     {
      AB_ResetPayload(p);
      p.direction       = bo.direction;
      p.reference_price = bo.reference_price;
      p.breakout_bar    = bo.breakout_bar;
      p.state           = bo.state;
      p.outcome         = bo.outcome;
      p.trap            = bo.trap;
      p.second_leg_trap = bo.second_leg_bar >= 0;
      AB_AddFinding(findings, "BREAKOUT", "DEFAULT", bo.direction, false, "", p);
     }

   // --- 4/5. REVERSAL_BULL / REVERSAL_BEAR ------------------------------
   for(int r = 0; r < 2; r++)
     {
      const int rev_dir = (r == 0) ? 1 : -1;
      const string name = (r == 0) ? "REVERSAL_BULL" : "REVERSAL_BEAR";
      int rev_direction = 0;
      int rev_legs = 0;
      if(AlB_AnalyzeReversal(bars, count, idx, last_closed, atr, swings, nswings,
                             rev_dir, rev_direction, rev_legs))
        {
         AB_ResetPayload(p);
         p.direction  = rev_direction;
         p.cross_bar  = AlB_ReversalCrossBar(bars, count, idx, last_closed, atr, rev_dir);
         // `MAJOR` at four legs, `MINOR` at one or more, `NONE` below that.
         // Only a non-`NONE` verdict becomes an evidence factor, so the verdict
         // string is what the decision layer reads.
         p.verdict    = (rev_legs >= AB_MAJOR_LEGS) ? "MAJOR"
                        : ((rev_legs >= 1) ? "MINOR" : "NONE");
         AB_AddFinding(findings, name, "REVERSAL", rev_direction, false, "", p);
        }
     }

   // --- 6/7. the major doubles, from swings only ------------------------
   int d1 = 0, d2 = 0;
   double dp1 = 0.0, dp2 = 0.0;
   if(AlB_FindMajorDoubleTop(swings, nswings, atr, d1, d2, dp1, dp2))
     {
      AB_ResetPayload(p);
      p.direction = -1;
      p.price1    = dp1;
      p.price2    = dp2;
      p.bar2      = d2;
      AB_AddFinding(findings, "DOUBLE_TOP_MAJOR", "DOUBLE_TOP", -1, false, "", p);
     }
   if(AlB_FindMajorDoubleBottom(swings, nswings, atr, d1, d2, dp1, dp2))
     {
      AB_ResetPayload(p);
      p.direction = 1;
      p.price1    = dp1;
      p.price2    = dp2;
      p.bar2      = d2;
      AB_AddFinding(findings, "DOUBLE_BOTTOM_MAJOR", "DOUBLE_BOTTOM", 1, false, "", p);
     }

   // --- 8/9. the micro doubles, from bars -------------------------------
   if(AlB_DetectMicroDoubleTop(bars, count, idx, last_closed, atr, d1, d2, dp1, dp2))
     {
      AB_ResetPayload(p);
      p.direction = -1;
      p.price1    = dp1;
      p.price2    = dp2;
      p.bar2      = d2;
      AB_AddFinding(findings, "DOUBLE_TOP_MICRO", "DOUBLE_TOP", -1, false, "", p);
     }
   if(AlB_DetectMicroDoubleBottom(bars, count, idx, last_closed, atr, d1, d2, dp1, dp2))
     {
      AB_ResetPayload(p);
      p.direction = 1;
      p.price1    = dp1;
      p.price2    = dp2;
      p.bar2      = d2;
      AB_AddFinding(findings, "DOUBLE_BOTTOM_MICRO", "DOUBLE_BOTTOM", 1, false, "", p);
     }

   // --- 10. MEASURED_MOVE ------------------------------------------------
   ABProjection projections[];
   const int nproj = AlB_DetectMeasuredMoves(bars, count, swings, nswings, atr,
                                             last_closed, legs, nlegs, projections);
   for(int i = 0; i < nproj; i++)
     {
      AB_ResetPayload(p);
      p.direction        = projections[i].direction;
      p.target_price     = projections[i].target_price;
      p.origin_price     = projections[i].origin_price;
      p.origin_bar_index = projections[i].origin_bar_index;
      p.reference_price  = projections[i].reference_price;
      p.w_scale          = projections[i].w_scale;
      p.w_structure      = projections[i].w_structure;
      AB_AddFinding(findings, "MEASURED_MOVE", "MEASURED_MOVE",
                    projections[i].direction, false, "", p);
     }

   // --- 11. FADING_MEASURED_MOVE ----------------------------------------
   //
   // `create_setups` seeds one fade per projection and takes the last
   // `fm_max_active`. `fm_enable_inverse` is on by default, so INVERSE
   // projections are included here; dropping them would be a port that
   // quietly disagreed with a configuration flag.
   for(int i = 0; i < nproj; i++)
     {
      if(projections[i].direction == 0)
         continue;
      if(projections[i].family == AB_MM_INVERSE && !AB_FM_ENABLE_INVERSE)
         continue;
      AB_ResetPayload(p);
      p.direction        = projections[i].direction;
      p.fade_direction   = -projections[i].direction;
      p.target_price     = projections[i].target_price;
      p.origin_price     = projections[i].origin_price;
      p.created_bar      = last_closed;
      p.state            = "PROJECTED";
      p.w_scale          = projections[i].w_scale;
      p.w_structure      = projections[i].w_structure;
      AB_AddFinding(findings, "FADING_MEASURED_MOVE", "FADING_MEASURED_MOVE",
                    p.fade_direction, false, "", p);
     }

   return(ArraySize(findings));
  }

#endif // ALBROOKS_SETUPS_MQH
//+------------------------------------------------------------------+
