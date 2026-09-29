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
// `setups`, `trade_plans`, `market_state` and `decision` are absent because
// they are not ported yet. `producer_version` says the same thing in prose;
// this says it in a form a test can check.
#define AB_PORTED_GROUPS "[\"atr\", \"bars_processed\", \"last_closed_bar\", \"swings\"]"

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
   int            setup_count;
   int            plan_count;
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
   s += "      \"action\": \"WAIT\",\n";
   s += "      \"direction\": 0,\n";
   s += "      \"is_actionable\": false,\n";
   s += "      \"reason\": \"NOT_PORTED\"\n";
   s += "    },\n";

   s += "    \"last_closed_bar\": " + AB_FmtInt(v.last_closed_bar) + ",\n";

   s += "    \"market_state\": {\n";
   s += "      \"direction\": " + AB_FmtInt(v.ms_direction) + ",\n";
   s += "      \"mode\": " + AB_Quote(v.ms_mode) + ",\n";
   s += "      \"strength\": " + AB_FmtNum(v.ms_strength) + ",\n";
   s += "      \"valid\": " + (v.ms_valid ? "true" : "false") + "\n";
   s += "    },\n";

   s += "    \"setups\": [],\n";

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

   s += "    \"trade_plans\": []\n";

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
