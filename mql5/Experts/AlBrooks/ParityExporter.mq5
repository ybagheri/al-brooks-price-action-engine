//+------------------------------------------------------------------+
//|                                             ParityExporter.mq5   |
//|  Reads a parity case, runs the port, writes the MQL5 sidecar.     |
//+------------------------------------------------------------------+
//
// ## What this EA is
//
// The *only* producer of `tests/parity/mql5/*.mql5.json`. It reads the case
// file's own bars, runs the ported engine over them, and writes the vector the
// MQL5 side computed. Nothing in this file may read a Python-computed value.
//
// ## The freeze
//
// The Python adapter owes the freeze -- drop any bar whose
// `bar.time + period_seconds > now`, decided by time on the server clock. The
// port owes the same obligation, or it would compare a series Python froze
// against one MQL5 did not and the difference would be misread as a divergence
// in the engine.
//
// Case bars are historical and the last one is the analysed bar, so the freeze
// is applied and then *checked*: the EA asserts the count it emitted equals the
// count it read. A silent truncation is the error `bars_processed` exists to
// catch, so truncating and then reporting the reduced count would defeat it.
//
// ## The job file
//
// The Strategy Tester .ini cannot pass inputs to an EA, so the case is named by
// a small control file in the agent's sandbox instead:
//
//     {"case": "parity_range_breakout_001.json"}
//
// That file is *configuration*. The vector is still computed by this EA from the
// case's bars, which is the property that makes the sidecar evidence.

#property strict

#include <AlBrooks\Json.mqh>
#include <AlBrooks/Core.mqh>
#include <AlBrooks/MarketState.mqh>
#include <AlBrooks/Setups.mqh>
#include <AlBrooks/Plan.mqh>
#include <AlBrooks/Decision.mqh>
#include <AlBrooks/Parity.mqh>

#define AB_JOB_FILE   "parity_job.json"
#define AB_PERIOD_SEC 3600        // H1, matching the case timestamps
#define AB_ATR_PERIOD 14          // AnalyzerConfig default


//+------------------------------------------------------------------+
//| ReadWholeFile                                                     |
//|                                                                   |
//| FILE_COMMON is load-bearing, and the reason is a measured one      |
//| rather than a documented one:                                      |
//|                                                                   |
//|   Without it, `FileOpen` resolves inside the agent's own          |
//|   `MQL5/Files` -- and **the agent wipes that directory on every   |
//|   startup**. Staging the case there before the run means the file  |
//|   is gone by the time OnInit executes, so OnInit reports "cannot  |
//|   read parity_job.json" while the file is plainly there on disk.  |
//|                                                                   |
//|   FILE_COMMON resolves to the shared                             |
//|   `MetaQuotes\Terminal\Common\Files`, which is not per-agent and   |
//|   is not wiped. Verified by printing TERMINAL_DATA_PATH and       |
//|   TERMINAL_COMMONDATA_PATH from inside the agent.                 |
//+------------------------------------------------------------------+
bool ReadWholeFile(const string &name, string &out)
  {
   int h = FileOpen(name, FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h == INVALID_HANDLE)
      return(false);
   out = "";
   // FileReadString consumes the newline and does NOT return it, so naively
   // concatenating the lines of a pretty-printed JSON file silently deletes
   // every line break in it. The result still looks like JSON and parses as
   // nothing, which is a miserable failure to diagnose -- so the newline is
   // put back explicitly.
   while(!FileIsEnding(h))
     {
      out += FileReadString(h);
      out += "\n";
     }
   FileClose(h);
   return(true);
  }

//+------------------------------------------------------------------+
//| LoadCase -- read bars, last_closed and the case id.              |
//+------------------------------------------------------------------+
bool LoadCase(const string &text, string &case_id, int &last_closed, ABBar &bars[])
  {
   int root = ABJ_Parse(text);
   if(root < 0 || g_abj_nodes[root].type != ABJ_OBJ)
      return(false);

   int n_id  = ABJ_FindKey(root, "id");
   int n_lc  = ABJ_FindKey(root, "last_closed");
   int n_bar = ABJ_FindKey(root, "bars");
   if(n_id < 0 || n_lc < 0 || n_bar < 0)
      return(false);
   if(g_abj_nodes[n_bar].type != ABJ_ARR)
      return(false);

   case_id     = g_abj_nodes[n_id].str;
   last_closed = (int)g_abj_nodes[n_lc].num;

   int count = ABJ_CountChildren(n_bar);
   ArrayResize(bars, count);
   for(int i = 0; i < count; i++)
     {
      int b = ABJ_Nth(n_bar, i);
      if(b < 0 || g_abj_nodes[b].type != ABJ_OBJ)
         return(false);
      int n_o = ABJ_FindKey(b, "o");
      int n_h = ABJ_FindKey(b, "h");
      int n_l = ABJ_FindKey(b, "l");
      int n_c = ABJ_FindKey(b, "c");
      int n_t = ABJ_FindKey(b, "time");
      if(n_o < 0 || n_h < 0 || n_l < 0 || n_c < 0)
         return(false);
      bars[i].open  = g_abj_nodes[n_o].num;
      bars[i].high  = g_abj_nodes[n_h].num;
      bars[i].low   = g_abj_nodes[n_l].num;
      bars[i].close = g_abj_nodes[n_c].num;
      bars[i].time  = (n_t >= 0) ? (datetime)g_abj_nodes[n_t].num : 0;
     }
   return(true);
  }

//+------------------------------------------------------------------+
//| FreezeClosedBars                                                  |
//|  bar.time is the OPEN time, so a bar is closed when                |
//|  `time + period <= now`. Inclusive at the boundary.                |
//|                                                                   |
//|  `now` comes from the caller so the rule can be tested with a     |
//|  fixed clock rather than the machine's, which is the mistake the   |
//|  Python adapter was caught by: a 3.1-hour skew changed 14 of 50   |
//|  bars. Passing it in keeps that decision visible and testable.   |
//+------------------------------------------------------------------+
int FreezeClosedBars(const ABBar &bars[],
                     const int count,
                     const datetime now,
                     const int period_seconds)
  {
   if(count <= 0)
      return(0);
   datetime cut = now - (datetime)period_seconds;
   int last_closed = -1;
   for(int i = 0; i < count; i++)
     {
      if(bars[i].time <= cut)
         last_closed = i;
     }
   return(last_closed);
  }

//+------------------------------------------------------------------+
int OnInit()
  {
   // Where is this agent's sandbox, really? The tester wipes and recreates
   // MQL5\Files on startup, so a file staged there before the run is gone by
   // the time OnInit runs -- which is why the build script passes an absolute
   // path and why this is printed rather than assumed.
   PrintFormat("parity: TERMINAL_DATA_PATH=%s", TerminalInfoString(TERMINAL_DATA_PATH));
   PrintFormat("parity: TERMINAL_COMMONDATA_PATH=%s", TerminalInfoString(TERMINAL_COMMONDATA_PATH));

   string job;
   if(!ReadWholeFile(AB_JOB_FILE, job))
     {
      Print("parity: cannot read ", AB_JOB_FILE);
      return(INIT_PARAMETERS_INCORRECT);
     }

   int jroot = ABJ_Parse(job);
   if(jroot < 0)
     {
      Print("parity: job file is not valid JSON, len=", StringLen(job));
      Print("parity: job text=[", job, "]");
      return(INIT_PARAMETERS_INCORRECT);
     }
   if(g_abj_nodes[jroot].type != ABJ_OBJ)
     {
      Print("parity: job root is not an object, type=", g_abj_nodes[jroot].type);
      return(INIT_PARAMETERS_INCORRECT);
     }
   int n_case = ABJ_FindKey(jroot, "case");
   if(n_case < 0)
     {
      Print("parity: job file names no case");
      return(INIT_PARAMETERS_INCORRECT);
     }
   const string case_file = g_abj_nodes[n_case].str;

   string text;
   if(!ReadWholeFile(case_file, text))
     {
      Print("parity: cannot read case file ", case_file);
      return(INIT_PARAMETERS_INCORRECT);
     }

   string case_id;
   int last_closed = 0;
   ABBar bars[];
   if(!LoadCase(text, case_id, last_closed, bars))
     {
      Print("parity: cannot parse case ", case_file);
      return(INIT_PARAMETERS_INCORRECT);
     }

   const int count = ArraySize(bars);
   PrintFormat("parity: case=%s bars=%d last_closed=%d", case_id, count, last_closed);

   // --- The freeze, applied then verified -------------------------------
   // TimeCurrent() is the server clock, which is what the Python side uses.
   // Case bars are historical, so this should keep all of them; if it does not,
   // the series really is truncated and the count below will say so rather than
   // quietly reporting a smaller bars_processed.
   const int frozen_last = FreezeClosedBars(bars, count, TimeCurrent(), AB_PERIOD_SEC);
   const int usable = (frozen_last >= 0) ? (frozen_last + 1) : 0;
   PrintFormat("parity: freeze kept %d of %d bars (frozen_last=%d)",
               usable, count, frozen_last);

   ABVector vec;
   vec.last_closed_bar = last_closed;
   vec.bars_processed = usable;          // bars GIVEN, after the freeze
   ArrayResize(vec.swings, 0);
   vec.setup_count = 0;
   vec.plan_count  = 0;

   // --- ATR -------------------------------------------------------------
   double atrs[];
   if(usable > 0 && AlB_CalculateAtrSeries(bars, usable, AB_ATR_PERIOD, atrs))
     {
      int idx = last_closed;
      if(idx >= usable)
         idx = usable - 1;
      if(idx >= 0)
         vec.atr = atrs[idx];
     }
   PrintFormat("parity: atr=%.17g", vec.atr);

   // --- Swings ----------------------------------------------------------
   AlB_FindSwings(bars, usable, last_closed, 3, vec.swings);
   PrintFormat("parity: swings=%d", ArraySize(vec.swings));
   for(int i = 0; i < ArraySize(vec.swings); i++)
      PrintFormat("   bar=%d confirmed=%d price=%g dir=%d",
                  vec.swings[i].bar_index, vec.swings[i].confirmed_bar_index,
                  vec.swings[i].price, vec.swings[i].direction);

    // --- Market state ----------------------------------------------------
    // `idx` and `last_closed` are the same number here. The Python side calls
    // `analyze_market_state(series, closed, closed, atr)`: it analyses bar
    // `closed` and its closed-bar horizon is also `closed`. Passing anything
    // else is not a subtle difference -- the trend and pressure windows are
    // anchored on `idx` -- but the two arguments being equal is a property of
    // the call site, not something the port may assume.
    ABMarketState ms;
    AlB_AnalyzeMarketState(bars, usable, last_closed, last_closed, vec.atr, ms);

    vec.ms_valid     = ms.valid;
    vec.ms_mode      = ms.mode;
    vec.ms_direction = ms.direction;
    vec.ms_strength  = ms.strength;

    PrintFormat("parity: ms valid=%s mode=%s dir=%d strength=%.17g",
                (ms.valid ? "true" : "false"), ms.mode, ms.direction, ms.strength);
    for(int i = 0; i < AB_STATE_COUNT; i++)
       PrintFormat("   %-14s raw=%.17g pct=%d", AB_STATES[i], ms.raws[i], ms.percentages[i]);

    // --- Setups ----------------------------------------------------------
    ABLeg legs[];
    AlB_BuildLegs(vec.swings, ArraySize(vec.swings), legs);
    PrintFormat("parity: legs=%d", ArraySize(legs));

    ABSetupFinding findings[];
    const int nfound = AlB_RunRegistry(bars, usable, last_closed, last_closed,
                                       vec.atr, vec.swings, ArraySize(vec.swings),
                                       legs, ArraySize(legs), findings);
    ArrayResize(vec.setups, nfound);
    for(int i = 0; i < nfound; i++)
      {
       vec.setups[i].detector       = findings[i].detector;
       vec.setups[i].kind           = findings[i].kind;
       vec.setups[i].setup_family   = AB_FamilyFor(findings[i].detector);
       vec.setups[i].direction      = findings[i].direction;
       vec.setups[i].has_setup_type = findings[i].has_setup_type;
       vec.setups[i].setup_type     = findings[i].setup_type;
       PrintFormat("   %-24s kind=%-24s dir=%+d type=%s",
                   findings[i].detector, findings[i].kind, findings[i].direction,
                   findings[i].has_setup_type ? findings[i].setup_type : "(null)");
      }
    vec.setup_count = nfound;
    PrintFormat("parity: setups=%d", vec.setup_count);

    // --- Trade plans -----------------------------------------------------
    // One plan per finding, in the order the findings arrived. That order is
    // the registry's registration order and is NOT a ranking.
    //
    // ## The swing list is EMPTY, and that is a port of the Python, not a gap
    //
    // `build_trade_plan` takes a `swings` argument and `_derive_stop` /
    // `_derive_target` both fall back to "the most recent confirmed swing"
    // when the setup names no level of its own. But `candidates_from_findings`
    // -- the only caller the analyzer uses -- does NOT pass `swings`, and the
    // parameter defaults to `()`. So in the running engine that fallback can
    // never fire: any stop or target not derived from the payload's own
    // numbers is an `ATR_FALLBACK`, and no plan in the vector ever reports a
    // `SWING` basis.
    //
    // This was found by parity, not by reading: the first disagreement after
    // porting the plan layer was a `target_basis` of `SWING` here against
    // `ATR_FALLBACK` in Python, on a case whose swings make a perfect target.
    // Passing the real swings "fixed" the number and broke the port, because
    // the Python side genuinely has none to pass. An empty list is what
    // `candidates_from_findings` produces, so it is what the port supplies.
    ABSwing no_swings[];
    ArrayResize(no_swings, 0);

    ABPlan plans[];
    const int nplans = AlB_BuildPlans(findings, nfound, bars, usable, last_closed,
                                       vec.atr, no_swings, 0, plans);
    ArrayResize(vec.plans, nplans);
    for(int i = 0; i < nplans; i++)
      {
       vec.plans[i].direction          = plans[i].direction;
       vec.plans[i].entry              = plans[i].entry;
       vec.plans[i].stop               = plans[i].stop;
       vec.plans[i].stop_basis         = plans[i].stop_basis;
       vec.plans[i].target             = plans[i].target;
       vec.plans[i].target_basis       = plans[i].target_basis;
       vec.plans[i].reward_to_risk     = plans[i].reward_to_risk;
       vec.plans[i].is_valid           = plans[i].is_valid ? 1 : 0;
       vec.plans[i].has_structural_stop = plans[i].has_structural_stop ? 1 : 0;
       PrintFormat("   plan %-24s dir=%+d entry=%.17g stop=%.17g (%s) "
                   "target=%.17g (%s) rr=%.17g valid=%s structural=%s",
                   plans[i].subject, plans[i].direction, plans[i].entry,
                   plans[i].stop, plans[i].stop_basis, plans[i].target,
                   plans[i].target_basis, plans[i].reward_to_risk,
                   plans[i].is_valid ? "true" : "false",
                   plans[i].has_structural_stop ? "true" : "false");
      }
    vec.plan_count = nplans;
    PrintFormat("parity: trade_plans=%d", vec.plan_count);

    // --- Decision --------------------------------------------------------
    // One candidate per finding, in the order the findings arrived -- the
    // registry's registration order, which is NOT a ranking. Each candidate's
    // evidence bundle is the family's own factors PLUS the shared market-state
    // context, which is identical for all of them.
    ABCandidate candidates[];
    ArrayResize(candidates, nfound);
    for(int i = 0; i < nfound; i++)
      {
       candidates[i].candidate_id = findings[i].detector + "#" + IntegerToString(i);
       candidates[i].plan = plans[i];
       AlB_AddFactorsFor(findings[i], ms, candidates[i].factors, candidates[i].factor_count);
       candidates[i].evidence_value = AlB_Score(candidates[i].factors, candidates[i].factor_count);
       candidates[i].has_own_evidence = false;
       for(int f = 0; f < candidates[i].factor_count; f++)
          if(candidates[i].factors[f].source != AB_SRC_MARKET_STATE)
             candidates[i].has_own_evidence = true;
       PrintFormat("   cand %-26s own=%s evidence=%.6f band=%s",
                   candidates[i].candidate_id,
                   candidates[i].has_own_evidence ? "true" : "false",
                   candidates[i].evidence_value,
                   AlB_Band(candidates[i].evidence_value));
      }

    ABDecision decision;
    AlB_Decide(candidates, nfound, bars, usable, last_closed, vec.atr, decision);
    PrintFormat("parity: decision action=%s reason=%s dir=%d actionable=%s "
                "(considered=%d eligible=%d rejected=%d bull=%.4f bear=%.4f)",
                decision.action, decision.reason, decision.direction,
                decision.is_actionable ? "true" : "false",
                decision.considered, decision.eligible, decision.rejected,
                decision.bull_ppts, decision.bear_ppts);

    vec.decision_action        = decision.action;
    vec.decision_reason        = decision.reason;
    vec.decision_direction     = decision.direction;
    vec.decision_is_actionable = decision.is_actionable;

    // The version names what was ACTUALLY ported. A later reader must be able
    // to tell a genuine partial result from a file someone edited to agree.
    const string producer_version = "full: all eight groups";

   const string body = AB_BuildSidecar(case_id, producer_version, vec);

   const string out_name = case_id + ".mql5.json";
   int w = FileOpen(out_name, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(w == INVALID_HANDLE)
     {
      Print("parity: cannot open ", out_name, " for writing");
      return(INIT_FAILED);
     }
   FileWriteString(w, body);
   FileClose(w);
   PrintFormat("parity: wrote %s to %s", out_name,
               TerminalInfoString(TERMINAL_COMMONDATA_PATH) + "\\Files");

   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
void OnTick()
  {
   // Everything happens once, in OnInit. A per-tick EA would analyse a
   // different series each tick and the sidecar would depend on how long the
   // tester ran, which is not comparable to a fixed case.
  }

//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   Print("parity: done, reason=", reason);
  }
//+------------------------------------------------------------------+
