//+------------------------------------------------------------------+
//|                                                     Plan.mqh     |
//|  The geometry of a hypothetical trade, from one setup finding.    |
//+------------------------------------------------------------------+
//
// ## What a plan is, and is not
//
// Entry, stop, target, and the arithmetic between them. It is **not** a
// recommendation (`TradePlan.to_dict()` carries `"is_recommendation":
// false` in the Python, and nothing here is one either) and it is not an
// order. `reward_to_risk` is arithmetic; it is not a forecast, a win
// rate, an expected value, a probability or an edge. Nothing in this
// project has been validated against outcomes.
//
// ## The load-bearing idea
//
// **Every level carries a basis.** A stop at `101.20` means something
// different depending on where it came from, so the basis travels with
// the price and is compared exactly by the parity harness. A port that
// computed the right number from the wrong level would be making a
// claim this engine does not make, and the harness would not see it.
//
// `ATR_FALLBACK` is the row that matters: when a setup names no level
// the engine still produces a stop, because a plan without a stop is not
// a plan -- and that stop is a *fallback*, not a structural claim.
//
// ## One builder, a table of anatomies
//
// The setup families record their geometry in incompatible places. A
// row of **data** saying where each family's fields live, read by one
// algorithm, is what stops that from becoming five builders.

#ifndef ALBROOKS_PLAN_MQH
#define ALBROOKS_PLAN_MQH

// --- bases: why a price is the number it is ---------------------------
#define AB_ENTRY_SETUP     "SETUP_REFERENCE"
#define AB_ENTRY_LAST_CLOSE "LAST_CLOSE"
#define AB_ENTRY_NONE      "NONE"

#define AB_STOP_PULLBACK   "PULLBACK_EXTREME"
#define AB_STOP_BREAKOUT   "BREAKOUT_REFERENCE"
#define AB_STOP_PATTERN    "PATTERN_EXTREME"
#define AB_STOP_SWING      "SWING"
#define AB_STOP_ATR        "ATR_FALLBACK"
#define AB_STOP_NONE       "NONE"

#define AB_TARGET_MEASURED_MOVE "MEASURED_MOVE"
#define AB_TARGET_FADE_ORIGIN   "FADE_ORIGIN"
#define AB_TARGET_SWING         "SWING"
#define AB_TARGET_ATR           "ATR_FALLBACK"
#define AB_TARGET_NONE          "NONE"

// --- issues: statements that are false about the arithmetic ----------
#define AB_ISSUE_NO_DIRECTION    "NO_DIRECTION"
#define AB_ISSUE_NO_ATR          "NO_ATR"
#define AB_ISSUE_ENTRY_UNDEFINED "ENTRY_UNDEFINED"
#define AB_ISSUE_STOP_UNDEFINED  "STOP_UNDEFINED"
#define AB_ISSUE_STOP_NOT_PROTECTIVE "STOP_NOT_PROTECTIVE"
#define AB_ISSUE_TARGET_UNDEFINED   "TARGET_UNDEFINED"
#define AB_ISSUE_TARGET_NOT_AHEAD   "TARGET_NOT_AHEAD"
#define AB_ISSUE_RISK_NOT_POSITIVE  "RISK_NOT_POSITIVE"

// --- AnalyzerConfig defaults ------------------------------------------
#define AB_PLAN_STOP_BUFFER_ATR    0.25
#define AB_PLAN_FALLBACK_STOP_ATR  1.0
#define AB_PLAN_FALLBACK_TARGET_ATR 2.0
#define AB_PLAN_MAX_STOP_ATR       3.0

struct ABPlan
  {
   string       subject;
   int          direction;
   double       entry;
   double       stop;
   double       target;
   string       entry_basis;
   string       stop_basis;
   string       target_basis;
   int          bar_index;
   int          signal_bar;
   double       risk;
   double       reward;
   double       reward_to_risk;
   bool         is_valid;
   bool         has_structural_stop;
   // `_is_terminal(payload)`: the setup behind the plan reached a state that
   // ended it. The geometry is still reported -- reporting it and acting on it
   // are different questions -- but the decision layer reads this, and its
   // failed-attempt gate counts it as one adverse observation.
   bool         has_terminal_warning;
   string       issues[8];      // de-duplicated, in first-seen order
   int          issue_count;
  };

//+------------------------------------------------------------------+
void AB_ResetPlan(ABPlan &p)
  {
   p.subject             = "";
   p.direction           = 0;
   p.entry               = 0.0;
   p.stop                = 0.0;
   p.target              = 0.0;
   p.entry_basis         = AB_ENTRY_NONE;
   p.stop_basis          = AB_STOP_NONE;
   p.target_basis        = AB_TARGET_NONE;
   p.bar_index           = -1;
   p.signal_bar          = -1;
   p.risk                = 0.0;
   p.reward              = 0.0;
   p.reward_to_risk      = 0.0;
   p.is_valid            = true;
   p.has_structural_stop = false;
   p.has_terminal_warning = false;
   p.issue_count         = 0;
  }

//+------------------------------------------------------------------+
//| AB_AddIssue -- de-duplicating append, matching `dict.fromkeys`.   |
//|                                                                    |
//|  Matters because `is_valid` is defined over the list: an issue     |
//|  appended twice is still one issue, and the Python keeps the first |
//|  occurrence. Order is preserved so the list reads the way the      |
//|  builder produced it.                                             |
//+------------------------------------------------------------------+
void AB_AddIssue(ABPlan &p, const string &code)
  {
   for(int i = 0; i < p.issue_count; i++)
      if(p.issues[i] == code)
         return;
   if(p.issue_count < 8)
     {
      p.issues[p.issue_count] = code;
      p.issue_count++;
     }
  }

//+------------------------------------------------------------------+
//| AB_HasIssue                                                       |
//+------------------------------------------------------------------+
bool AB_HasIssue(const ABPlan &p, const string &code)
  {
   for(int i = 0; i < p.issue_count; i++)
      if(p.issues[i] == code)
         return(true);
   return(false);
  }

// ---------------------------------------------------------------------------
// Anatomy
// ---------------------------------------------------------------------------
//
// ## Why it is data
//
// A pullback carries `stop_price`, a measured move keeps its origin
// nested under `origin.price`, a fading setup's *trade* direction is
// `fade_direction` rather than `direction`, and a reversal carries no
// prices at all. `CONTRIBUTING.md` rule 5 forbids solving that with five
// copies of the level-derivation algorithm, so the differences are rows
// and the algorithm is written once.

struct ABAnatomy
  {
   string       family;
   // Indexes into the payload's own fields. Zero means "this family has
   // no such key", which is a fact about the family rather than an
   // absence: a reversal really does name no prices.
   int          entry_key;          // ABK_*
   int          stop_key;           // 0 = none
   bool         stop_from_extremes; // price1 / price2, min for a long
   string       stop_basis;
   int          target_key;         // 0 = none
   string       target_basis;
   int          signal_key;         // second choice, for FADING
   int          invalidation_key;
   bool         direction_is_fade;  // read fade_direction first
  };

// Payload field selectors. Named, because "key 3" in a table of
// anatomies is unreadable and this table is read far more often than it
// is written.
#define ABK_NONE             0
#define ABK_REFERENCE_PRICE  1
#define ABK_ORIGIN_PRICE     2
#define ABK_STOP_PRICE       3
#define ABK_TARGET_PRICE     4
#define ABK_EXTREME_PRICE    5
#define ABK_SIGNAL_BAR       6
#define ABK_BREAKOUT_BAR     7
#define ABK_ORIGIN_BAR_INDEX 8
#define ABK_STATE_BAR        9
#define ABK_CREATED_BAR      10
#define ABK_BAR2             11
#define ABK_CROSS_BAR        12

//+------------------------------------------------------------------+
double AB_PayloadPrice(const ABSetupPayload &p, const int key)
  {
   switch(key)
     {
      case ABK_REFERENCE_PRICE: return(p.reference_price);
      case ABK_ORIGIN_PRICE:    return(p.origin_price);
      case ABK_STOP_PRICE:      return(p.stop_price);
      case ABK_TARGET_PRICE:    return(p.target_price);
      case ABK_EXTREME_PRICE:   return(p.extreme_price);
     }
   return(0.0);
  }

//+------------------------------------------------------------------+
int AB_PayloadIndex(const ABSetupPayload &p, const int key)
  {
   switch(key)
     {
      case ABK_SIGNAL_BAR:       return(p.signal_bar);
      case ABK_BREAKOUT_BAR:     return(p.breakout_bar);
      case ABK_ORIGIN_BAR_INDEX: return(p.origin_bar_index);
      case ABK_STATE_BAR:        return(p.state_bar);
      case ABK_CREATED_BAR:      return(p.created_bar);
      case ABK_BAR2:             return(p.bar2);
      case ABK_CROSS_BAR:        return(p.cross_bar);
     }
   return(-1);
  }

//+------------------------------------------------------------------+
//| `_as_float` returns a value only when it is strictly POSITIVE,    |
//| because every model in this engine uses 0.0 as "not observed".    |
//| So `> 0.0` is the whole test, and a stored zero is indistinguishable
//| from an absent key -- which is exactly what the Python sees.       |
//+------------------------------------------------------------------+
bool AB_FirstPrice(const ABSetupPayload &p, const int key, double &out)
  {
   if(key == ABK_NONE)
      return(false);
   const double v = AB_PayloadPrice(p, key);
   if(v <= 0.0)
      return(false);
   out = v;
   return(true);
  }

//+------------------------------------------------------------------+
int AB_FirstIndex(const ABSetupPayload &p, const int first, const int second)
  {
   const int a = AB_PayloadIndex(p, first);
   if(a >= 0)
      return(a);
   return(AB_PayloadIndex(p, second));
  }

//+------------------------------------------------------------------+
//| AB_AnatomyFor -- the row for `family`, or the default (no keys, so |
//| every level is derived and the plan reports that it was).         |
//|                                                                   |
//|  An unknown family is not an error. A third-party detector that    |
//|  registered itself should still be plannable.                      |
//|                                                                   |
//|  Written as an out-parameter rather than a return value: MQL5 has  |
//|  no copy-assignment from a returned struct, so `ABAnatomy a =     |
//|  AB_AnatomyFor(f);` does not compile.                             |
//+------------------------------------------------------------------+
void AB_AnatomyFor(string family, ABAnatomy &a)
  {
   a.family             = family;
   a.entry_key          = ABK_NONE;
   a.stop_key           = ABK_NONE;
   a.stop_from_extremes = false;
   a.stop_basis         = AB_STOP_ATR;
   a.target_key         = ABK_NONE;
   a.target_basis       = AB_TARGET_ATR;
   a.signal_key         = ABK_SIGNAL_BAR;
   a.invalidation_key   = ABK_NONE;
   a.direction_is_fade  = false;

   if(family == "PULLBACK")
     {
      a.entry_key        = ABK_REFERENCE_PRICE;
      a.stop_key         = ABK_STOP_PRICE;
      a.stop_basis       = AB_STOP_PULLBACK;
      a.signal_key       = ABK_SIGNAL_BAR;
      a.invalidation_key = ABK_EXTREME_PRICE;
      return;
     }
   if(family == "BREAKOUT")
     {
      // No entry key on purpose: a breakout is entered ON the break, and its
      // reference is a level price is leaving rather than one it trades at.
      // The entry falls back to the close and says so via LAST_CLOSE.
      a.stop_key         = ABK_REFERENCE_PRICE;
      a.stop_basis       = AB_STOP_BREAKOUT;
      a.signal_key       = ABK_BREAKOUT_BAR;
      a.invalidation_key = ABK_REFERENCE_PRICE;
      return;
     }
   if(family == "MEASURED_MOVE")
     {
      // "origin.price" is tried before "reference_price" because it is more
      // specific: for a swing family they are the same number, and for the
      // range and gap families the origin is the breakout close the
      // projection was measured from.
      a.entry_key        = ABK_ORIGIN_PRICE;
      a.stop_key         = ABK_NONE;
      a.stop_basis       = AB_STOP_ATR;
      a.target_key       = ABK_TARGET_PRICE;
      a.target_basis     = AB_TARGET_MEASURED_MOVE;
      a.signal_key       = ABK_ORIGIN_BAR_INDEX;
      a.invalidation_key = ABK_ORIGIN_PRICE;
      return;
     }
   if(family == "FADING_MEASURED_MOVE")
     {
      // A fade aims back at where the projected move started, which is the one
      // level the projection itself supplies.
      a.direction_is_fade  = true;
      a.entry_key          = ABK_NONE;
      a.stop_key           = ABK_NONE;
      a.stop_basis         = AB_STOP_ATR;
      a.target_key         = ABK_ORIGIN_PRICE;
      a.target_basis       = AB_TARGET_FADE_ORIGIN;
      a.signal_key         = ABK_STATE_BAR;
      a.invalidation_key   = ABK_ORIGIN_PRICE;
      return;
     }
   if(family == "REVERSAL")
     {
      a.signal_key = ABK_CROSS_BAR;
      return;
     }
   if(family == "DOUBLE_TOP" || family == "DOUBLE_BOTTOM")
     {
      // The stop is the ADVERSE extreme of TWO numbers, not one of them: for
      // a long the reference is the minimum across the keys, for a short the
      // maximum. Taking the first, or averaging, would put the stop inside
      // the pattern.
      a.stop_from_extremes = true;
      a.stop_basis         = AB_STOP_PATTERN;
      a.signal_key         = ABK_BAR2;
      a.invalidation_key   = ABK_NONE;   // "level", only set by a context pass
      return;
     }
  }

// ---------------------------------------------------------------------------
// Swings
// ---------------------------------------------------------------------------

//+------------------------------------------------------------------+
//| AlB_SwingReference -- the most recent confirmed swing that could    |
//| hold a level, else "not found".                                   |
//|                                                                    |
//|  For a long that is the newest confirmed swing LOW BELOW the       |
//|  entry; for a short, the newest confirmed swing HIGH ABOVE it.     |
//|  Negating `direction` turns the stop-oriented search into the      |
//|  target-oriented one, which is why the target derivation does     |
//|  exactly that.                                                     |
//|                                                                    |
//|  `confirmed > bar_index` is refused, and that is what keeps a      |
//|  right-side-confirmed fractal out of a plan dated before its own   |
//|  evidence existed.                                                 |
//+------------------------------------------------------------------+
bool AlB_SwingReference(const ABSwing &swings[],
                        const int nswings,
                        const int direction,
                        const double entry,
                        const int bar_index,
                        double &out)
  {
   bool found = false;
   double value = 0.0;
   for(int i = 0; i < nswings; i++)
     {
      const int confirmed = swings[i].confirmed_bar_index;
      const double price = swings[i].price;
      const int swing_direction = swings[i].direction;
      if(confirmed < 0 || confirmed > bar_index || price <= 0.0)
         continue;
      if(direction > 0 && swing_direction < 0 && price < entry)
        {
         found = true;
         value = price;
        }
      else
         if(direction < 0 && swing_direction > 0 && price > entry)
           {
            found = true;
            value = price;
           }
     }
   if(found)
      out = value;
   return(found);
  }

// ---------------------------------------------------------------------------
// Derivation
// ---------------------------------------------------------------------------

//+------------------------------------------------------------------+
void AlB_DeriveStop(const ABSetupPayload &payload,
                    const ABAnatomy &anat,
                    const int direction,
                    const double entry,
                    const double atr,
                    const int bar_index,
                    const ABSwing &swings[],
                    const int nswings,
                    double &stop,
                    string &basis,
                    double &reference)
  {
   const double buffer = (atr > 0.0) ? AB_PLAN_STOP_BUFFER_ATR * atr : 0.0;
   const double away = (direction > 0) ? 1.0 : -1.0;

   basis = anat.stop_basis;
   double ref = 0.0;
   AB_FirstPrice(payload, anat.stop_key, ref);

   if(ref <= 0.0 && anat.stop_from_extremes)
     {
      bool have = false;
      double extreme = 0.0;
      if(payload.price1 > 0.0)
        {
         extreme = payload.price1;
         have = true;
        }
      if(payload.price2 > 0.0)
        {
         if(!have)
           {
            extreme = payload.price2;
            have = true;
           }
         else
            extreme = (direction > 0) ? MathMin(extreme, payload.price2)
                                      : MathMax(extreme, payload.price2);
        }
      if(have)
         ref = extreme;
     }

   if(ref <= 0.0)
     {
      double swing = 0.0;
      if(AlB_SwingReference(swings, nswings, direction, entry, bar_index, swing))
        {
         ref   = swing;
         basis = AB_STOP_SWING;
        }
     }

   if(ref <= 0.0)
     {
      if(atr <= 0.0)
        {
         stop = 0.0;
         basis = AB_STOP_NONE;
         reference = 0.0;
         return;
        }
      // The fallback is a volatility DISTANCE, not a buffer. Applying the
      // buffer to the entry instead would make a 0.25 ATR stop, which is the
      // opposite of what plan_fallback_stop_atr means.
      stop = entry - away * AB_PLAN_FALLBACK_STOP_ATR * atr;
      basis = AB_STOP_ATR;
      reference = 0.0;
      return;
     }

   stop = ref - away * buffer;
   reference = ref;
  }

//+------------------------------------------------------------------+
//| AlB_DeriveTarget                                                   |
//|                                                                    |
//|  A projected target BEHIND the entry is dropped rather than used    |
//|  with a negative reward: it means the projection and the entry      |
//|  describe different things, which is a fact worth reporting        |
//|  rather than something to paper over by taking an absolute value.  |
//+------------------------------------------------------------------+
void AlB_DeriveTarget(const ABSetupPayload &payload,
                      const ABAnatomy &anat,
                      const int direction,
                      const double entry,
                      const double atr,
                      const int bar_index,
                      const ABSwing &swings[],
                      const int nswings,
                      double &target,
                      string &basis,
                      double &reference)
  {
   const double ahead = (direction > 0) ? 1.0 : -1.0;

   double found = 0.0;
   const bool has_found = AB_FirstPrice(payload, anat.target_key, found);
   if(has_found && (found - entry) * ahead > 0.0)
     {
      target = found;
      basis = anat.target_basis;
      reference = found;
      return;
     }

   double swing = 0.0;
   if(AlB_SwingReference(swings, nswings, -direction, entry, bar_index, swing))
     {
      target = swing;
      basis = AB_TARGET_SWING;
      reference = swing;
      return;
     }

   if(atr <= 0.0)
     {
      target = 0.0;
      basis = AB_TARGET_NONE;
      reference = 0.0;
      return;
     }

   target = entry + ahead * AB_PLAN_FALLBACK_TARGET_ATR * atr;
   basis = AB_TARGET_ATR;
   reference = 0.0;
  }

//+------------------------------------------------------------------+
//| AB_IsTerminalPayload -- has the setup reached a state that ended  |
//| it?                                                               |
//|                                                                    |
//|  Read so that the GEOMETRY is still reported: a failed breakout's |
//|  arithmetic is coherent, and whether it deserves a plan is the     |
//|  decision engine's question. Gating here would answer it without    |
//|  the machinery that makes such an answer auditable.               |
//+------------------------------------------------------------------+
bool AB_IsTerminalPayload(const ABSetupPayload &p)
  {
   if(p.state == "INVALIDATED" || p.state == "FAILED")
      return(true);
   return(p.outcome == "FAILED" || p.outcome == "INVALIDATED");
  }

//+------------------------------------------------------------------+
//| AlB_BuildPlan -- `trade/plan.py::build_trade_plan`.                |
//|                                                                    |
//|  One plan per finding, and the finding's own family selects the    |
//|  anatomy. `bar_index` is clamped rather than rejected, matching    |
//|  every detector in this engine.                                    |
//+------------------------------------------------------------------+
void AlB_BuildPlan(const string &subject,
                   const ABSetupFinding &finding,
                   const ABBar &bars[],
                   const int count,
                   const int bar_index,
                   const double atr,
                   const ABSwing &swings[],
                   const int nswings,
                   ABPlan &out)
  {
   AB_ResetPlan(out);
   out.subject = subject;

   // Both copied out of `finding` first: MQL5 will not bind a `const string &`
   // parameter to a struct member, and it reports that as a confusing
   // "parameter passed as reference, variable expected".
   string detector = finding.detector;
   ABSetupPayload payload = finding.payload;

   ABAnatomy anat;
   AB_AnatomyFor(AB_FamilyFor(detector), anat);

   // --- direction -------------------------------------------------------
   int direction = 0;
   if(anat.direction_is_fade)
     {
      // The fade runs AGAINST the projection, so the trade-facing direction is
      // the fade direction. Reading `direction` first is the easiest way to
      // fade a trend by mistake.
      if(payload.fade_direction != -2 && payload.fade_direction != 0)
         direction = (payload.fade_direction > 0) ? 1 : -1;
      else
         direction = (payload.direction > 0) ? 1 : ((payload.direction < 0) ? -1 : 0);
     }
   else
      direction = (payload.direction > 0) ? 1 : ((payload.direction < 0) ? -1 : 0);

   if(direction == 0)
      AB_AddIssue(out, AB_ISSUE_NO_DIRECTION);
   if(atr <= 0.0)
      AB_AddIssue(out, AB_ISSUE_NO_ATR);

   const int closed = (count > 0) ? MathMin(bar_index, count - 1) : -1;

   // --- entry -----------------------------------------------------------
   double entry = 0.0;
   string entry_basis = AB_ENTRY_NONE;
   if(AB_FirstPrice(payload, anat.entry_key, entry))
     {
      entry_basis = AB_ENTRY_SETUP;
     }
   else
     {
      if(closed >= 0 && closed < count)
        {
         entry = bars[closed].close;
         entry_basis = AB_ENTRY_LAST_CLOSE;
        }
      else
        {
         entry = 0.0;
         entry_basis = AB_ENTRY_NONE;
         AB_AddIssue(out, AB_ISSUE_ENTRY_UNDEFINED);
        }
     }

   // --- stop and target -------------------------------------------------
   double stop = 0.0, target = 0.0, stop_reference = 0.0, target_reference = 0.0;
   string stop_basis = AB_STOP_NONE, target_basis = AB_TARGET_NONE;

   if(entry_basis == AB_ENTRY_NONE || direction == 0)
     {
      // Without an entry or a direction there is no "protective side" to
      // reason about, so no level is invented. NO_DIRECTION and *_UNDEFINED
      // say why, rather than a plan whose stop happens to sit on the wrong
      // side of a trade that does not exist.
     }
   else
     {
      AlB_DeriveStop(payload, anat, direction, entry, atr, closed, swings, nswings,
                     stop, stop_basis, stop_reference);
      AlB_DeriveTarget(payload, anat, direction, entry, atr, closed, swings, nswings,
                       target, target_basis, target_reference);
     }

   if(stop_basis == AB_STOP_NONE)
      AB_AddIssue(out, AB_ISSUE_STOP_UNDEFINED);
   if(target_basis == AB_TARGET_NONE)
      AB_AddIssue(out, AB_ISSUE_TARGET_UNDEFINED);

   // --- the three geometric issues, read off the numbers ---------------
   //
   // A level of 0.0 means "undefined" and is SKIPPED rather than compared:
   // `STOP_UNDEFINED` is the builder's statement about it, and testing a
   // missing stop for being on the wrong side of the entry would report the
   // same thing twice.
   if(direction != 0)
     {
      const double away = (direction > 0) ? 1.0 : -1.0;
      if(entry > 0.0 && stop > 0.0)
        {
         if((entry - stop) * away < 0.0)
            AB_AddIssue(out, AB_ISSUE_STOP_NOT_PROTECTIVE);
         if(MathAbs(entry - stop) == 0.0)
            AB_AddIssue(out, AB_ISSUE_RISK_NOT_POSITIVE);
        }
      if(entry > 0.0 && target > 0.0 && (target - entry) * away <= 0.0)
         AB_AddIssue(out, AB_ISSUE_TARGET_NOT_AHEAD);
     }

   out.direction    = direction;
   out.entry        = entry;
   out.stop         = stop;
   out.target       = target;
   out.entry_basis  = entry_basis;
   out.stop_basis   = stop_basis;
   out.target_basis = target_basis;
   out.bar_index    = closed;
   out.signal_bar   = AB_FirstIndex(payload, anat.signal_key, ABK_NONE);
   out.risk         = MathAbs(entry - stop);
   out.reward       = MathAbs(target - entry);
   // 0.0 when the risk is 0, because the ratio is undefined there and `inf`
   // would travel into JSON as a non-standard literal. Such a plan carries
   // RISK_NOT_POSITIVE and is not valid.
   out.reward_to_risk = (out.risk > 0.0) ? (out.reward / out.risk) : 0.0;

   out.is_valid = !AB_HasIssue(out, AB_ISSUE_NO_DIRECTION)
                  && !AB_HasIssue(out, AB_ISSUE_NO_ATR)
                  && !AB_HasIssue(out, AB_ISSUE_ENTRY_UNDEFINED)
                  && !AB_HasIssue(out, AB_ISSUE_STOP_UNDEFINED)
                  && !AB_HasIssue(out, AB_ISSUE_STOP_NOT_PROTECTIVE)
                  && !AB_HasIssue(out, AB_ISSUE_TARGET_UNDEFINED)
                  && !AB_HasIssue(out, AB_ISSUE_TARGET_NOT_AHEAD)
                  && !AB_HasIssue(out, AB_ISSUE_RISK_NOT_POSITIVE);

   // Whether the stop is derived from something the market actually did. A
   // caller filtering for plans worth reading should test THIS rather than
   // `is_valid`: a valid plan on an ATR_FALLBACK stop is arithmetically
   // sound and structurally empty.
   out.has_structural_stop = (stop_basis != AB_STOP_ATR && stop_basis != AB_STOP_NONE);
   out.has_terminal_warning = AB_IsTerminalPayload(payload);
  }

//+------------------------------------------------------------------+
//| AlB_BuildPlans -- one plan per finding, in the order the findings  |
//| arrived.                                                           |
//|                                                                    |
//|  That order is the registry's registration order, which the        |
//| registry documents as deterministic and explicitly NOT a ranking.   |
//|  It is preserved rather than sorted by reward:risk, for the same   |
//|  reason `evaluation.compare()` refuses to be a recommendation.     |
//+------------------------------------------------------------------+
int AlB_BuildPlans(const ABSetupFinding &findings[],
                   const int nfindings,
                   const ABBar &bars[],
                   const int count,
                   const int bar_index,
                   const double atr,
                   const ABSwing &swings[],
                   const int nswings,
                   ABPlan &plans[])
  {
   ArrayResize(plans, 0);
   for(int i = 0; i < nfindings; i++)
     {
      const int k = ArraySize(plans);
      ArrayResize(plans, k + 1);
      AlB_BuildPlan(findings[i].detector, findings[i], bars, count, bar_index,
                    atr, swings, nswings, plans[k]);
     }
   return(ArraySize(plans));
  }

#endif // ALBROOKS_PLAN_MQH
//+------------------------------------------------------------------+
