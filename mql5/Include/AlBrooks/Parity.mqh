//+------------------------------------------------------------------+
//|                                                  Parity.mqh       |
//|  Assembles the canonical vector and writes the sidecar.           |
//+------------------------------------------------------------------+
#ifndef ALBROOKS_PARITY_MQH
#define ALBROOKS_PARITY_MQH

// ## The envelope
//
// schema / case_id / producer / scope / vector. The Python side refuses a
// reduced scope, a foreign schema, a case_id that is not the case being run,
// and any producer other than "mql5" -- those four refusals are what make the
// file evidence rather than a claim, so all four are written correctly here
// rather than relying on the loader's defaults.
//
// ## Sorting
//
// Python compares the three list groups as multisets, so the order emitted
// here is not part of the contract. They are written in the order found, and
// the top-level keys are written in sorted order so a diff of two sidecars is
// readable by a human.

#define AB_SCHEMA "albrooks-parity/1"
#define AB_PRODUCER "mql5"

// The groups this build ACTUALLY implements, as a machine-checkable claim.
//
// This is not documentation, it is the gate. A partial port is allowed to
// disagree with Python on the groups it has not written yet, and is not allowed
// to disagree on the ones it has. Without a declared list, "the port is
// incomplete" and "the port is broken" are the same FAILED verdict, and CI
// cannot tell them apart -- so the honest option would be to not ship the
// sidecar at all, which throws away the real evidence this produces.
//
// Every group in `SCOPE` is now implemented by this build, so the list
// is the whole scope. That makes it the regression tripwire in its
// strongest form: there is no longer any group a disagreement can hide
// in, and `--allow-partial` has nothing left to suppress.
#define AB_PORTED_GROUPS "[\"atr\", \"bars_processed\", \"decision\", \"last_closed_bar\", \"market_state\", \"setups\", \"swings\", \"trade_plans\"]"


struct ABSetupEntry
  {
   string         detector;
   string         kind;
   string         setup_family;
   int            direction;
   // `setup_type` is genuinely nullable and MQL5 has no null, so presence is
   // carried beside the value. Emitting the string "NONE" for an absent type
   // would be a *value*, and `CODE_OR_NULL` compares null and "NONE"
   // differently -- so a port that did that fails every case, which is the
   // right outcome and a much better one than a port that passed.
   bool           has_setup_type;
   string         setup_type;
  };

struct ABPlanEntry
  {
   int            direction;
   double         entry;
   double         stop;
   string         stop_basis;
   double         target;
   string         target_basis;
   double         reward_to_risk;
   int            is_valid;            // 0/1, written as a JSON bool
   int            has_structural_stop;  // 0/1, written as a JSON bool
  };

struct ABVector
  {
   int            last_closed_bar;
   int            bars_processed;
   double         atr;
   int            ms_valid;            // 0/1, written as a JSON bool
   string         ms_mode;
   int            ms_direction;
   double         ms_strength;
   ABSwing        swings[];
   ABSetupEntry   setups[];
   int            setup_count;
   ABPlanEntry    plans[];
   int            plan_count;
   // The decision: action, reason, direction, is_actionable.
   string         decision_action;
   string         decision_reason;
   int            decision_direction;
   int            decision_is_actionable;
  };

//+------------------------------------------------------------------+
//| AB_FmtNum -- enough significant digits for a 1e-9 relative compare.
//|                                                                   |
//| 16 decimals is at least 18 significant digits across the price range |
//| these cases use, so a value that matches Python bit-for-bit also      |
//| matches after the round trip through text. Emitting fewer digits     |
//| would fail a comparison the arithmetic actually passed.             |
//+------------------------------------------------------------------+
string AB_FmtNum(const double v)
  {
   if(v == DBL_MAX || v == -DBL_MAX)
      return("0.0");
   return(DoubleToString(v, 16));
  }

//+------------------------------------------------------------------+
string AB_FmtInt(const int v)
  {
   return(IntegerToString(v));
  }

//+------------------------------------------------------------------+
string AB_Quote(const string &s)
  {
   string out = "\"";
   for(int i = 0; i < StringLen(s); i++)
     {
      ushort c = StringGetCharacter(s, i);
      if(c == '"')       out += "\\\"";
      else if(c == '\\') out += "\\\\";
      else               out += StringSubstr(s, i, 1);
     }
   out += "\"";
   return(out);
  }

//+------------------------------------------------------------------+
//| AB_BuildVector -- the JSON body, sorted by key at every level.    |
//+------------------------------------------------------------------+
string AB_BuildVector(const ABVector &v)
  {
   // Indentation is 4 spaces here, not 2: this object is nested under
   // "vector" in the sidecar, and building it at its own top level produced a
   // file whose braces were right but whose layout read as if it were not.
   // The contract only requires valid JSON, but a diff nobody can read is a
   // diff nobody will read -- and the sidecar's whole purpose is to be read.
   string s = "";
   s += "{\n";

   s += "    \"atr\": " + AB_FmtNum(v.atr) + ",\n";
   s += "    \"bars_processed\": " + AB_FmtInt(v.bars_processed) + ",\n";

    s += "    \"decision\": {\n";
    s += "      \"action\": " + AB_Quote(v.decision_action) + ",\n";
    s += "      \"direction\": " + AB_FmtInt(v.decision_direction) + ",\n";
    s += "      \"is_actionable\": " + (v.decision_is_actionable ? "true" : "false") + ",\n";
    s += "      \"reason\": " + AB_Quote(v.decision_reason) + "\n";
    s += "    },\n";


   s += "    \"last_closed_bar\": " + AB_FmtInt(v.last_closed_bar) + ",\n";

   s += "    \"market_state\": {\n";
   s += "      \"direction\": " + AB_FmtInt(v.ms_direction) + ",\n";
   s += "      \"mode\": " + AB_Quote(v.ms_mode) + ",\n";
   s += "      \"strength\": " + AB_FmtNum(v.ms_strength) + ",\n";
   s += "      \"valid\": " + (v.ms_valid ? "true" : "false") + "\n";
   s += "    },\n";

    s += "    \"setups\": [";
    if(ArraySize(v.setups) > 0)
      {
       s += "\n";
       for(int i = 0; i < ArraySize(v.setups); i++)
         {
          s += "      {";
          s += "\"detector\": " + AB_Quote(v.setups[i].detector);
          s += ", \"direction\": " + AB_FmtInt(v.setups[i].direction);
          s += ", \"kind\": " + AB_Quote(v.setups[i].kind);
          s += ", \"setup_family\": " + AB_Quote(v.setups[i].setup_family);
          // JSON null, not "NONE" and not "". The harness compares this leaf
          // under CODE_OR_NULL, where null and "NONE" are different answers.
          s += ", \"setup_type\": " + (v.setups[i].has_setup_type ? AB_Quote(v.setups[i].setup_type) : "null");
          s += "}";
          if(i < ArraySize(v.setups) - 1)
             s += ",";
          s += "\n";
         }
       s += "    ";
      }
    s += "],\n";


   s += "    \"swings\": [";
   if(ArraySize(v.swings) > 0)
     {
      s += "\n";
      for(int i = 0; i < ArraySize(v.swings); i++)
        {
         s += "      {";
         s += "\"bar_index\": " + AB_FmtInt(v.swings[i].bar_index);
         s += ", \"confirmed_bar_index\": " + AB_FmtInt(v.swings[i].confirmed_bar_index);
         s += ", \"direction\": " + AB_FmtInt(v.swings[i].direction);
         s += ", \"price\": " + AB_FmtNum(v.swings[i].price);
         s += "}";
         if(i < ArraySize(v.swings) - 1)
            s += ",";
         s += "\n";
        }
      s += "    ";
     }
   s += "],\n";

    s += "    \"trade_plans\": [";
    if(ArraySize(v.plans) > 0)
      {
       s += "\n";
       for(int i = 0; i < ArraySize(v.plans); i++)
         {
          s += "      {";
          s += "\"direction\": " + AB_FmtInt(v.plans[i].direction);
          s += ", \"entry\": " + AB_FmtNum(v.plans[i].entry);
          s += ", \"has_structural_stop\": " + (v.plans[i].has_structural_stop ? "true" : "false");
          s += ", \"is_valid\": " + (v.plans[i].is_valid ? "true" : "false");
          s += ", \"reward_to_risk\": " + AB_FmtNum(v.plans[i].reward_to_risk);
          s += ", \"stop\": " + AB_FmtNum(v.plans[i].stop);
          s += ", \"stop_basis\": " + AB_Quote(v.plans[i].stop_basis);
          s += ", \"target\": " + AB_FmtNum(v.plans[i].target);
          s += ", \"target_basis\": " + AB_Quote(v.plans[i].target_basis);
          s += "}";
          if(i < ArraySize(v.plans) - 1)
             s += ",";
          s += "\n";
         }
       s += "    ";
      }
    s += "]\n";


   s += "  }";
   return(s);
  }

//+------------------------------------------------------------------+
//| AB_BuildSidecar                                                   |
//+------------------------------------------------------------------+
string AB_BuildSidecar(const string &case_id,
                       const string &producer_version,
                       const ABVector &v)
  {
   string s = "";
   s += "{\n";
   s += "  \"case_id\": " + AB_Quote(case_id) + ",\n";
   s += "  \"producer\": " + AB_Quote(AB_PRODUCER) + ",\n";
   s += "  \"producer_version\": " + AB_Quote(producer_version) + ",\n";
   s += "  \"schema\": " + AB_Quote(AB_SCHEMA) + ",\n";
   s += "  \"scope\": [\n";
   s += "    \"atr\",\n";
   s += "    \"bars_processed\",\n";
   s += "    \"decision\",\n";
   s += "    \"last_closed_bar\",\n";
   s += "    \"market_state\",\n";
   s += "    \"setups\",\n";
   s += "    \"swings\",\n";
   s += "    \"trade_plans\"\n";
   s += "  ],\n";
   s += "  \"ported\": " + AB_PORTED_GROUPS + ",\n";
   s += "  \"vector\": " + AB_BuildVector(v) + "\n";
   s += "}\n";
   return(s);
  }

#endif // ALBROOKS_PARITY_MQH
//+------------------------------------------------------------------+
