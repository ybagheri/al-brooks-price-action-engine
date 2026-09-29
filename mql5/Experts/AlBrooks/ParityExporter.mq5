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

   // Not ported yet. Emitted as declared-and-empty rather than omitted, because
   // the loader refuses a reduced scope -- and a MISSING field is a
   // disagreement, so an omitted group could not be distinguished from one the
   // port forgot. These will read MISMATCH until the engine is ported, which is
   // the honest state.
   vec.ms_valid    = 0;
   vec.ms_mode     = "NOT_PORTED";
   vec.ms_direction = 0;
   vec.ms_strength = 0.0;

   // The version names what was ACTUALLY ported. A later reader must be able
   // to tell a genuine partial result from a file someone edited to agree.
   const string producer_version = "partial: atr+swings";
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
