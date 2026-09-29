//+------------------------------------------------------------------+
//|                                                 Decision.mqh     |
//|  Evidence factors, the gates, and one answer.                    |
//+------------------------------------------------------------------+
//
// ## The number, and what it is not
//
// The evidence score is the mean of a bundle's factors, averaged
// **within** each source first and then across sources. It is an
// evidence score. It is **not** a probability, a win rate, an expected
// value, or a likelihood. Nothing in this project has been calibrated
// against outcomes, so there is no population of cases to compute a
// rate against, and `CONCEPT_TAXONOMY.md` §6 asks for "evidence score"
// rather than "confidence" for exactly that reason. `0.8` means "the
// factors behind this reading were, on average, at 0.8 of their own
// scale". It does not mean the reading is right 80% of the time.
//
// ## Why the mean is per source, not per factor
//
// A flat mean over all factors would let whichever source emits the
// most factors dominate -- the pullback adapter emits one factor per
// pullback while the reversal adapter emits one per satisfied leg, so a
// four-leg reversal would outweigh a confirmed pullback on arithmetic
// alone. That is an artefact of how many fields each layer happens to
// expose, not a statement about the market.
//
// ## `basis` is the load-bearing field
//
// `MEASURED` is a magnitude computed from the data; `LIFECYCLE` is a
// discrete position in a state machine; `ASSERTED` is present with no
// magnitude. A number without a basis is a lie waiting to happen:
// `CONFIRMED` is not "0.75 confirmed", and `ASSERTED` must not be
// recorded as `0.0`, which would read as "measured, and came out nil".
//
// ## Four actions, and the difference between two of them
//
// `NO_TRADE` is the engine declining to answer. `WAIT` means there *was*
// something and a stated condition is not met. Collapsing them would
// make an empty result look like a judgement.
//
// ## What a `BUY` here means
//
// "Of the plans that passed every gate, this one had the most evidence
// behind it by the declared criteria." Not "this is more likely to work".
// The criteria are echoed in the output so a reader never has to guess
// why one plan beat another.

#ifndef ALBROOKS_DECISION_MQH
#define ALBROOKS_DECISION_MQH

// --- AnalyzerConfig defaults -------------------------------------------
#define AB_MIN_SCORE            0.40
#define AB_MIN_RR               1.0
#define AB_MAX_LATE_ATR         0.50
#define AB_CONFLICT_PPTS        10.0
#define AB_MAX_FAILED_ATTEMPTS  2
#define AB_EVIDENCE_STRONG_BAND 0.70
#define AB_EVIDENCE_MODERATE_BAND 0.40

// `evidence.UNQUANTIFIED_WEIGHT`: not 0.0 (that would claim the factor
// was measured and came out nil, and would drag any average down as
// though it were a negative observation) and not 1.0 (that would rank a
// bare observation above a weak measurement).
#define AB_UNQUANTIFIED_WEIGHT 0.5

// Actions and reasons. Stable codes, rather than sentences a caller has
// to parse.
#define AB_ACTION_NO_TRADE "NO_TRADE"
#define AB_ACTION_WAIT     "WAIT"
#define AB_ACTION_BUY      "BUY"
#define AB_ACTION_SELL     "SELL"

#define AB_REASON_DISABLED     "DECISION_DISABLED"
#define AB_REASON_NO_ANALYSIS  "NO_ANALYSIS"
#define AB_REASON_NO_CANDIDATES "NO_CANDIDATES"
#define AB_REASON_ALL_VETOED   "ALL_CANDIDATES_VETOED"
#define AB_REASON_CONFLICT     "EVIDENCE_CONFLICT"
#define AB_REASON_RANKED       "RANKED_CANDIDATE"

// Veto codes. Every blocking veto names its threshold in its detail, so
// a reader can check the comparison rather than trust the verdict.
#define AB_VETO_NO_DIRECTION   "NO_DIRECTION"
#define AB_VETO_NO_OWN_EVIDENCE "NO_OWN_EVIDENCE"
#define AB_VETO_INVALID_GEOMETRY "INVALID_GEOMETRY"
#define AB_VETO_TERMINAL_SETUP "TERMINAL_SETUP"
#define AB_VETO_NO_ATR         "NO_ATR"
#define AB_VETO_EVIDENCE_TOO_WEAK "EVIDENCE_TOO_WEAK"
#define AB_VETO_RISK_REWARD_TOO_LOW "RISK_REWARD_TOO_LOW"
#define AB_VETO_TRADE_IS_LATE  "TRADE_IS_LATE"
#define AB_VETO_TOO_MANY_FAILED_ATTEMPTS "TOO_MANY_FAILED_ATTEMPTS"
#define AB_VETO_VOLATILITY_STOP_ONLY "VOLATILITY_STOP_ONLY"

// Basis codes.
#define AB_BASIS_MEASURED   "MEASURED"
#define AB_BASIS_LIFECYCLE  "LIFECYCLE"
#define AB_BASIS_ASSERTED   "ASSERTED"

// Sources.
#define AB_SRC_MARKET_STATE "MARKET_STATE"
#define AB_SRC_MEASURED_MOVE "MEASURED_MOVE"
#define AB_SRC_REVERSAL     "REVERSAL"
#define AB_SRC_PULLBACK     "PULLBACK"
#define AB_SRC_BREAKOUT     "BREAKOUT"
#define AB_SRC_FADING       "FADING_MEASURED_MOVE"

#define AB_MAX_FACTORS 8

struct ABFactor
  {
   string   source;
   string   code;
   double   weight;
   string   basis;
  };

struct ABVeto
  {
   string   code;
   int      blocking;      // 0/1, written as a JSON bool
  };

struct ABCandidate
  {
   string   candidate_id;   // "<detector>#<position>"
   ABPlan   plan;
   ABFactor factors[AB_MAX_FACTORS];
   int      factor_count;
   double   evidence_value;
   bool     has_own_evidence;
   bool     blocked;
  };

struct ABDecision
  {
   string   action;
   string   reason;
   int      direction;
   int      is_actionable;   // 0/1, written as a JSON bool
   string   subject;
   double   bull_ppts;
   double   bear_ppts;
   int      considered;
   int      eligible;
   int      rejected;
  };

//+------------------------------------------------------------------+
void AB_ResetDecision(ABDecision &d)
  {
   d.action        = AB_ACTION_NO_TRADE;
   d.reason        = AB_REASON_NO_CANDIDATES;
   d.direction     = 0;
   d.is_actionable = 0;
   d.subject       = "";
   d.bull_ppts     = 0.0;
   d.bear_ppts     = 0.0;
   d.considered    = 0;
   d.eligible      = 0;
   d.rejected      = 0;
  }

//+------------------------------------------------------------------+
void AB_AddFactor(ABFactor &factors[], int &count, string source, string code,
                  double weight, string basis)
  {
   if(count >= AB_MAX_FACTORS)
      return;
   factors[count].source = source;
   factors[count].code   = code;
   factors[count].weight = AlB_Clamp01(weight);
   factors[count].basis  = basis;
   count++;
  }

//+------------------------------------------------------------------+
//| AlB_ParseNumericDetail -- read a trailing NUMBER out of a detail. |
//|                                                                   |
//|  Only the LAST token is considered, and only if it parses, so a     |
//|  detail like "closed 0.8 beyond the edge" is not read as 0.8.      |
//|  Present-but-unquantified is `ASSERTED` at the midpoint, and a     |
//|  code that DID carry a number is `MEASURED` -- and that difference |
//|  is worth keeping: a slope of 1.00 and the presence of compression |
//|  are not the same kind of claim.                                   |
//|                                                                   |
//|  `out_basis` is written as well as the weight, because the two    |
//|  travel together and the caller must not have to infer one from   |
//|  the other.                                                       |
//+------------------------------------------------------------------+
double AlB_ParseNumericDetail(const string &detail, string &out_basis)
  {
   out_basis = AB_BASIS_ASSERTED;
   if(StringLen(detail) == 0)
      return(AB_UNQUANTIFIED_WEIGHT);

   int end = StringLen(detail);
   while(end > 0)
     {
      ushort c = StringGetCharacter(detail, end - 1);
      if(c == ' ' || c == '\t')
        {
         end--;
         continue;
        }
      break;
     }
   if(end == 0)
      return(AB_UNQUANTIFIED_WEIGHT);

   int start = end;
   while(start > 0)
     {
      ushort c = StringGetCharacter(detail, start - 1);
      if(c == ' ' || c == '\t')
         break;
      start--;
     }
   string token = StringSubstr(detail, start, end - start);
   // `rstrip(".,;:%")`
   while(StringLen(token) > 0)
     {
      ushort c = StringGetCharacter(token, StringLen(token) - 1);
      if(c == '.' || c == ',' || c == ';' || c == ':' || c == '%')
        {
         token = StringSubstr(token, 0, StringLen(token) - 1);
         continue;
        }
      break;
     }
   if(StringLen(token) == 0)
      return(AB_UNQUANTIFIED_WEIGHT);

   // MQL5 has no "is this a number" test, so the token is validated the way
   // `float()` would: an optional sign, then digits with at most one point
   // and optional exponent. Anything else is not a number and the factor
   // stays ASSERTED.
   if(!AB_IsNumericToken(token))
      return(AB_UNQUANTIFIED_WEIGHT);

   out_basis = AB_BASIS_MEASURED;
   return(AlB_Clamp01(StringToDouble(token)));
  }

//+------------------------------------------------------------------+
bool AB_IsNumericToken(const string &s)
  {
   const int n = StringLen(s);
   if(n == 0)
      return(false);
   int i = 0;
   if(s[i] == '+' || s[i] == '-')
      i++;
   int digits = 0, points = 0, exp_digits = 0;
   bool seen_exp = false;
   for(; i < n; i++)
     {
      ushort c = StringGetCharacter(s, i);
      if(c >= '0' && c <= '9')
        {
         if(seen_exp)
            exp_digits++;
         else
            digits++;
         continue;
        }
      if(c == '.' && !seen_exp && points == 0)
        {
         points++;
         continue;
        }
      if((c == 'e' || c == 'E') && !seen_exp && digits > 0)
        {
         seen_exp = true;
         if(i + 1 < n && (StringGetCharacter(s, i + 1) == '+' || StringGetCharacter(s, i + 1) == '-'))
            i++;
         continue;
        }
      return(false);
     }
   return(digits > 0 || exp_digits > 0);
  }

//+------------------------------------------------------------------+
//| AlB_AddMarketStateFactors -- `evidence.from_market_state`.         |
//|                                                                    |
//|  Market-state evidence is added to EVERY bundle, because context is  |
//|  part of what backs a candidate: the same pullback in a strong trend |
//|  and the same pullback in a tight range are not the same claim.     |
//|  It is identical for all candidates, so on its own it says nothing  |
//|  about one -- which is why `NO_OWN_EVIDENCE` exists.                |
//+------------------------------------------------------------------+
void AlB_AddMarketStateFactors(const ABMarketState &ms, ABFactor &factors[], int &count)
  {
   for(int i = 0; i < ms.evidence_count; i++)
     {
      const string line = ms.evidence[i];
      int colon = StringFind(line, ":");
      string code = line;
      string detail = "";
      if(colon >= 0)
        {
         code = StringSubstr(line, 0, colon);
         detail = StringSubstr(line, colon + 1);
         // `.strip()`
         while(StringLen(detail) > 0 && StringGetCharacter(detail, 0) == ' ')
            detail = StringSubstr(detail, 1);
         while(StringLen(detail) > 0 && StringGetCharacter(detail, StringLen(detail) - 1) == ' ')
            detail = StringSubstr(detail, 0, StringLen(detail) - 1);
        }
      string basis = "";
      const double weight = AlB_ParseNumericDetail(detail, basis);
      AB_AddFactor(factors, count, AB_SRC_MARKET_STATE, code, weight, basis);
     }
  }

//+------------------------------------------------------------------+
//| AlB_AddFactorsFor -- `decision.engine.bundle_for`, family by       |
//| family.                                                            |
//|                                                                    |
//|  A family with no adapter here contributes NO factors rather than   |
//|  a wrong number, and the `NO_OWN_EVIDENCE` gate then refuses to    |
//|  rank the result -- so a missing adapter is visible rather than    |
//|  silently producing a context-only candidate. That is deliberate:  |
//|  a bundle of nothing but `MARKET_STATE` scores that source's value |
//|  outright, which once let a fade outrank a real measured move.      |
//+------------------------------------------------------------------+
void AlB_AddFactorsFor(const ABSetupFinding &finding,
                       const ABMarketState &ms,
                       ABFactor &factors[],
                       int &count)
  {
   count = 0;
   string detector = finding.detector;
   string family = AB_FamilyFor(detector);
   ABSetupPayload payload = finding.payload;

   if(family == "MEASURED_MOVE")
     {
      AB_AddFactor(factors, count, AB_SRC_MEASURED_MOVE, "MM_SCALE",
                   payload.w_scale, AB_BASIS_MEASURED);
      AB_AddFactor(factors, count, AB_SRC_MEASURED_MOVE, "MM_STRUCTURE",
                   payload.w_structure, AB_BASIS_MEASURED);
     }
   else
      if(family == "FADING_MEASURED_MOVE")
        {
         // Two sources in one adapter and both are needed: a fade is a
         // lifecycle over someone else's target, so the projection's evidence
         // is the only measurement behind it, and without the lifecycle factor
         // a fade of a projection and the projection itself would score
         // identically.
         AB_AddFactor(factors, count, AB_SRC_FADING, "MM_SCALE",
                      payload.w_scale, AB_BASIS_MEASURED);
         AB_AddFactor(factors, count, AB_SRC_FADING, "MM_STRUCTURE",
                      payload.w_structure, AB_BASIS_MEASURED);
         double weight = 0.0;
         if(payload.state == "PROJECTED")
            weight = 0.2;
         else
            if(payload.state == "POTENTIAL")
               weight = 0.4;
            else
               if(payload.state == "DEVELOPING")
                  weight = 0.7;
               else
                  if(payload.state == "CONFIRMED")
                     weight = 1.0;
         // The gaps between the lifecycle values are NOT meaningful: a
         // POTENTIAL fade is not "twice as potential" as a PROJECTED one. What
         // matters is that the positions are discrete rather than points on a
         // continuum. COMPLETED and INVALIDATED are excluded entirely: a
         // terminal negative is a dead observation, not a weak one.
         if(weight > 0.0)
            AB_AddFactor(factors, count, AB_SRC_FADING, payload.state, weight,
                         AB_BASIS_LIFECYCLE);
        }
      else
         if(family == "PULLBACK")
           {
            // INVALIDATED is deliberately EXCLUDED for the same reason: folding
            // a negative in at a low weight would make an invalidated setup look
            // like a weak one rather than a dead one.
            double weight = 0.0;
            if(payload.state == "CANDIDATE")
               weight = 1.0 / 3.0;
            else
               if(payload.state == "PROVISIONAL")
                  weight = 2.0 / 3.0;
               else
                  if(payload.state == "CONFIRMED")
                     weight = 1.0;
            if(weight > 0.0)
               AB_AddFactor(factors, count, AB_SRC_PULLBACK, payload.state, weight,
                            AB_BASIS_LIFECYCLE);
           }
         else
            if(family == "BREAKOUT")
              {
               // FAILED is excluded: a failed breakout is not a weak breakout,
               // it is the opposite one.
               double weight = 0.0;
               string code = "";
               if(payload.outcome == "FOLLOW")
                 {
                  weight = 1.0;
                  code = "OUTCOME_FOLLOW";
                 }
               else
                  if(payload.outcome == "PENDING")
                    {
                     weight = 0.5;
                     code = "OUTCOME_PENDING";
                    }
               if(code != "")
                  AB_AddFactor(factors, count, AB_SRC_BREAKOUT, code, weight,
                               AB_BASIS_LIFECYCLE);
               // Both traps are adverse observations, recorded rather than
               // subtracted: a bundle is never a number that had things taken
               // away from it, and the codes say what was observed.
               if(payload.trap)
                  AB_AddFactor(factors, count, AB_SRC_BREAKOUT, "BREAKOUT_TRAP",
                               1.0, AB_BASIS_ASSERTED);
               if(payload.second_leg_trap)
                  AB_AddFactor(factors, count, AB_SRC_BREAKOUT, "SECOND_LEG_TRAP",
                               1.0, AB_BASIS_ASSERTED);
              }
            else
               if(family == "REVERSAL")
                 {
                  // The registry hands over a `ReversalResult`, not a
                  // `ReversalQuality`, and that model has no `satisfied`
                  // list -- so the verdict is the ONLY factor a reversal
                  // contributes. A reversal's legs are read by its own
                  // detector, not restated here.
                  if(payload.verdict != "NONE" && StringLen(payload.verdict) > 0)
                     AB_AddFactor(factors, count, AB_SRC_REVERSAL,
                                  "VERDICT_" + payload.verdict, 1.0,
                                  AB_BASIS_LIFECYCLE);
                 }
               // DOUBLE_TOP / DOUBLE_BOTTOM have no adapter: two similar
               // extremes are a shape, and this project has not earned a
               // number for it.

   AlB_AddMarketStateFactors(ms, factors, count);
  }

//+------------------------------------------------------------------+
//| AlB_Score -- `evaluation.scoring.score`.                           |
//|                                                                    |
//|  Sources are weighted equally: each source's factors are averaged  |
//|  first, and those means are then averaged.                         |
//|                                                                    |
//|  The result is a NUMBER and not a probability. It cannot be used as |
//|  one, and `is_actionable` in the output says so rather than        |
//|  trusting the reader to remember.                                  |
//+------------------------------------------------------------------+
double AlB_Score(const ABFactor &factors[], const int count)
  {
   if(count <= 0)
      return(0.0);

   // First-seen source order, which is the order the factors were added in.
   string sources[];
   double means[];
   ArrayResize(sources, 0);
   ArrayResize(means, 0);
   for(int i = 0; i < count; i++)
     {
      int k = -1;
      for(int s = 0; s < ArraySize(sources); s++)
         if(sources[s] == factors[i].source)
           {
            k = s;
            break;
           }
      if(k < 0)
        {
         k = ArraySize(sources);
         ArrayResize(sources, k + 1);
         ArrayResize(means, k + 1);
         sources[k] = factors[i].source;
         means[k] = 0.0;
        }
      means[k] += factors[i].weight;
     }

   // Divide each source's total by its own factor count. The counts are
   // gathered in a second pass so the means are in first-seen source order,
   // which is the order the mean over sources is then taken in.
   int seen[];
   ArrayResize(seen, ArraySize(sources));
   ArrayInitialize(seen, 0);
   for(int i = 0; i < count; i++)
     {
      for(int s = 0; s < ArraySize(sources); s++)
         if(sources[s] == factors[i].source)
           {
            seen[s]++;
            break;
           }
     }
   for(int s = 0; s < ArraySize(sources); s++)
      if(seen[s] > 0)
         means[s] /= (double)seen[s];

   double total = 0.0;
   for(int s = 0; s < ArraySize(means); s++)
      total += means[s];
   return(total / (double)ArraySize(means));
  }

//+------------------------------------------------------------------+
string AlB_Band(const double value)
  {
   if(value <= 0.0)
      return("NONE");
   if(value >= AB_EVIDENCE_STRONG_BAND)
      return("STRONG");
   if(value >= AB_EVIDENCE_MODERATE_BAND)
      return("MODERATE");
   return("WEAK");
  }

//+------------------------------------------------------------------+
//| AlB_VetoesFor -- `decision.veto.vetoes_for`.                       |
//|                                                                    |
//|  Gates run in a FIXED order and NONE is short-circuited: a         |
//|  candidate that fails two of them reports both, because a reader   |
//|  fixing one condition should not have to re-run to discover the     |
//|  second.                                                           |
//|                                                                    |
//|  Every blocking gate is a CHOSEN THRESHOLD on a transparent number |
//|  -- a heuristic, not a calibrated one. Setting `min_rr` to 3.0 does |
//|  not make a 3.1 plan better; it makes fewer plans eligible.        |
//|                                                                    |
//|  The seventh, `INVALID_GEOMETRY`, carries no threshold: a plan     |
//|  whose stop is not on the protective side of its entry is not a    |
//|  weak trade, it is an arithmetically broken one.                   |
//+------------------------------------------------------------------+
void AlB_VetoesFor(const ABCandidate &candidate,
                   const double close,
                   const double atr,
                   ABVeto &vetoes[],
                   int &count)
  {
   count = 0;
   // Copied out of the candidate: MQL5 will not bind a reference to a struct
   // member, and reports it as "reference cannot be used".
   ABPlan plan = candidate.plan;

   // 1. direction
   if(plan.direction == 0)
     {
      vetoes[count].code = AB_VETO_NO_DIRECTION;
      vetoes[count].blocking = 1;
      count++;
     }

   // 2. own evidence. `score()` averages within each source and then across
   //    them, so a bundle holding only `MARKET_STATE` -- added to EVERY
   //    candidate and identical for all of them -- scores that source's value
   //    outright with no penalty for having said nothing about the setup.
   if(!candidate.has_own_evidence)
     {
      vetoes[count].code = AB_VETO_NO_OWN_EVIDENCE;
      vetoes[count].blocking = 1;
      count++;
     }

   // 3. geometry
   if(!plan.is_valid)
     {
      vetoes[count].code = AB_VETO_INVALID_GEOMETRY;
      vetoes[count].blocking = 1;
      count++;
     }

   // 4. terminal state
   if(plan.has_terminal_warning)
     {
      vetoes[count].code = AB_VETO_TERMINAL_SETUP;
      vetoes[count].blocking = 1;
      count++;
     }

   // 5. volatility reference
   if(atr <= 0.0)
     {
      vetoes[count].code = AB_VETO_NO_ATR;
      vetoes[count].blocking = 1;
      count++;
     }

   // 6. evidence score
   if(candidate.evidence_value < AB_MIN_SCORE)
     {
      vetoes[count].code = AB_VETO_EVIDENCE_TOO_WEAK;
      vetoes[count].blocking = 1;
      count++;
     }

   // 7. reward:risk
   if(plan.reward_to_risk < AB_MIN_RR)
     {
      vetoes[count].code = AB_VETO_RISK_REWARD_TOO_LOW;
      vetoes[count].blocking = 1;
      count++;
     }

   // 8. staleness. Says the plan is OUT OF DATE, not that it is wrong: a
   //    pullback whose reference entry is half an ATR behind the market can
   //    still work, it just is not the entry the plan described.
   if(atr > 0.0 && plan.entry > 0.0)
     {
      const double drift = MathAbs(close - plan.entry) / atr;
      if(drift > AB_MAX_LATE_ATR)
        {
         vetoes[count].code = AB_VETO_TRADE_IS_LATE;
         vetoes[count].blocking = 1;
         count++;
        }
     }

   // 9. adverse observations. The list is deliberately short and named: these
   //    are the only negative observations the adapters emit, a breakout's two
   //    trap flags. The plan's own terminal flag counts too.
   int adverse = 0;
   for(int i = 0; i < candidate.factor_count; i++)
      if(candidate.factors[i].code == "BREAKOUT_TRAP"
         || candidate.factors[i].code == "SECOND_LEG_TRAP")
         adverse++;
   if(plan.has_terminal_warning)
      adverse++;
   if(adverse > AB_MAX_FAILED_ATTEMPTS)
     {
      vetoes[count].code = AB_VETO_TOO_MANY_FAILED_ATTEMPTS;
      vetoes[count].blocking = 1;
      count++;
     }

   // Advisory. Notice, not exclusion: a plan whose stop was invented from an
   // ATR multiple is materially weaker than one placed behind a swing low,
   // and that is worth saying while the candidate is still in the running --
   // without pretending this layer has earned the authority to exclude it.
   if(!plan.has_structural_stop)
     {
      vetoes[count].code = AB_VETO_VOLATILITY_STOP_ONLY;
      vetoes[count].blocking = 0;
      count++;
     }
  }

//+------------------------------------------------------------------+
//| AlB_Decide -- `decision.engine.decide`.                            |
//|                                                                    |
//|  The order of the steps is the order of the explanation, and no     |
//|  step is skipped silently:                                         |
//|                                                                    |
//|  1. `enable_decision` -- off means `NO_TRADE` / `DECISION_DISABLED`.|
//|  2. A volatility reference -- without one no ATR-relative gate is   |
//|     evaluable, and a decision over ungated candidates would rest    |
//|     on unchecked numbers.                                          |
//|  3. Nothing found -- `NO_TRADE` / `NO_CANDIDATES`.                 |
//|  4. Vetoes.                                                          |
//|  5. Nothing survived -- `WAIT` / `ALL_CANDIDATES_VETOED`.          |
//|  6. Conflict -- both directions eligible and neither dominating is  |
//|     a disagreement, not a reading: `WAIT`.                         |
//|  7. Rank the dominant side on the declared criteria.               |
//+------------------------------------------------------------------+
void AlB_Decide(ABCandidate &candidates[],
                const int ncandidates,
                const ABBar &bars[],
                const int count,
                const int last_closed,
                const double atr,
                ABDecision &out)
  {
   AB_ResetDecision(out);
   out.considered = ncandidates;

   if(atr <= 0.0)
     {
      out.action = AB_ACTION_NO_TRADE;
      out.reason = AB_REASON_NO_ANALYSIS;
      return;
     }
   if(ncandidates == 0)
     {
      out.action = AB_ACTION_NO_TRADE;
      out.reason = AB_REASON_NO_CANDIDATES;
      return;
     }

   const int closed = (count > 0) ? MathMin(last_closed, count - 1) : -1;
   const double close = (closed >= 0 && closed < count) ? bars[closed].close : 0.0;

   int eligible = 0;
   for(int i = 0; i < ncandidates; i++)
     {
      ABVeto vetoes[16];
      int n = 0;
      AlB_VetoesFor(candidates[i], close, atr, vetoes, n);
      candidates[i].blocked = false;
      for(int v = 0; v < n; v++)
         if(vetoes[v].blocking)
           {
            candidates[i].blocked = true;
            break;
           }
      if(!candidates[i].blocked)
         eligible++;
     }
   out.eligible = eligible;
   out.rejected = ncandidates - eligible;

   if(eligible == 0)
     {
      out.action = AB_ACTION_WAIT;
      out.reason = AB_REASON_ALL_VETOED;
      return;
     }

   // The strongest evidence on each side. 0.0 when a side has nothing
   // eligible, which is what makes `contested` false rather than a
   // comparison against a fabricated zero.
   double bull_ppts = 0.0, bear_ppts = 0.0;
   bool has_bull = false, has_bear = false;
   for(int i = 0; i < ncandidates; i++)
     {
      if(candidates[i].blocked)
         continue;
      const double ppts = candidates[i].evidence_value * 100.0;
      if(candidates[i].plan.direction > 0)
        {
         has_bull = true;
         if(ppts > bull_ppts)
            bull_ppts = ppts;
        }
      else
         if(candidates[i].plan.direction < 0)
           {
            has_bear = true;
            if(ppts > bear_ppts)
               bear_ppts = ppts;
           }
     }
   out.bull_ppts = bull_ppts;
   out.bear_ppts = bear_ppts;

   const bool contested = has_bull && has_bear;
   const double gap = MathAbs(bull_ppts - bear_ppts);
   if(contested && gap < AB_CONFLICT_PPTS)
     {
      out.action = AB_ACTION_WAIT;
      out.reason = AB_REASON_CONFLICT;
      return;
     }

   const bool take_bull = (bull_ppts >= bear_ppts);

   // The winner is the best of the dominant pool, on the criteria the module
   // declares: evidence score, then reward:risk, then candidate_id ascending
   // so the result is reproducible. Two candidates with identical evidence and
   // identical reward:risk are separated only by a name.
   int winner = -1;
   for(int i = 0; i < ncandidates; i++)
     {
      if(candidates[i].blocked)
         continue;
      if(take_bull && candidates[i].plan.direction <= 0)
         continue;
      if(!take_bull && candidates[i].plan.direction >= 0)
         continue;
      if(winner < 0)
        {
         winner = i;
         continue;
        }
      const double a = candidates[i].evidence_value;
      const double b = candidates[winner].evidence_value;
      if(a > b)
        {
         winner = i;
         continue;
        }
      if(a < b)
         continue;
      const double ra = candidates[i].plan.reward_to_risk;
      const double rb = candidates[winner].plan.reward_to_risk;
      if(ra > rb)
        {
         winner = i;
         continue;
        }
      if(ra < rb)
         continue;
      if(StringCompare(candidates[i].candidate_id, candidates[winner].candidate_id) < 0)
         winner = i;
     }

   if(winner < 0)
     {
      // Unreachable while `NO_DIRECTION` is a blocking gate, which is the
      // right place for it. Kept so a future change to the gates degrades into
      // an abstention rather than reading off the end of the array.
      out.action = AB_ACTION_NO_TRADE;
      out.reason = AB_REASON_NO_CANDIDATES;
      return;
     }

   out.action = (candidates[winner].plan.direction > 0) ? AB_ACTION_BUY : AB_ACTION_SELL;
   out.reason = AB_REASON_RANKED;
   out.direction = candidates[winner].plan.direction;
   out.subject = candidates[winner].candidate_id;
   out.is_actionable = 1;
  }

#endif // ALBROOKS_DECISION_MQH
//+------------------------------------------------------------------+
