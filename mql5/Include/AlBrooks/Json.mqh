//+------------------------------------------------------------------+
//|                                                    Json.mqh       |
//|  A minimal JSON reader and writer for the parity exchange.        |
//+------------------------------------------------------------------+
#ifndef ALBROOKS_JSON_MQH
#define ALBROOKS_JSON_MQH

// ## Why a hand-written parser rather than nothing
//
// The sidecar is written by the MQL5 side and read by Python, and the case is
// read the other way. Neither direction may go through a shortcut that lets the
// two sides agree without MQL5 having computed the vector: the case file is the
// *input*, and parsing it is what makes the sidecar evidence.
//
// ## Why a node pool
//
// MQL5 structures cannot contain an array of their own type -- the size is not
// finite. So a tree is a flat array of nodes linked by index, with the root at
// index 0. This is the standard workaround and it is not an optimisation.

#define ABJ_NULL 0
#define ABJ_BOOL 1
#define ABJ_NUM  2
#define ABJ_STR  3
#define ABJ_ARR  4
#define ABJ_OBJ  5

struct ABJsonNode
  {
   int            type;
   bool           bval;
   double         num;
   string         str;            // string value, or object key when ABJ_OBJ
   string         key;            // this node's key inside its parent object
   int            first_child;    // index, or -1
   int            next_sibling;   // index, or -1
  };

ABJsonNode g_abj_nodes[];
int       g_abj_count = 0;

//+------------------------------------------------------------------+
int ABJ_NewNode(const int type)
  {
   int idx = g_abj_count;
   g_abj_count++;
   ArrayResize(g_abj_nodes, g_abj_count);
   g_abj_nodes[idx].type         = type;
   g_abj_nodes[idx].bval         = false;
   g_abj_nodes[idx].num          = 0.0;
   g_abj_nodes[idx].first_child  = -1;
   g_abj_nodes[idx].next_sibling = -1;
   return(idx);
  }

//+------------------------------------------------------------------+
void ABJ_Reset()
  {
   g_abj_count = 0;
   ArrayResize(g_abj_nodes, 0);
  }

//+------------------------------------------------------------------+
//| ABJ_SkipWhitespace                                                |
//+------------------------------------------------------------------+
int ABJ_SkipWhitespace(const string &s, int i)
  {
   while(i < StringLen(s))
     {
      ushort c = StringGetCharacter(s, i);
      if(c == ' ' || c == '\t' || c == '\n' || c == '\r')
         i++;
      else
         break;
     }
   return(i);
  }

//+------------------------------------------------------------------+
//| ABJ_ParseString                                                   |
//|  Handles the escapes JSON actually requires. The case files are    |
//|  machine-written, but an unhandled escape would corrupt a bar     |
//|  silently rather than loudly, so the common set is covered.       |
//+------------------------------------------------------------------+
bool ABJ_ParseString(const string &s, int &i, string &out)
  {
   out = "";
   if(i >= StringLen(s) || StringGetCharacter(s, i) != '"')
      return(false);
   i++;
   while(i < StringLen(s))
     {
      ushort c = StringGetCharacter(s, i);
      if(c == '"')
        {
         i++;
         return(true);
        }
      if(c == '\\')
        {
         i++;
         if(i >= StringLen(s))
            return(false);
         ushort e = StringGetCharacter(s, i);
         if(e == 'n')       out += "\n";
         else if(e == 't')  out += "\t";
         else if(e == 'r')  out += "\r";
         else if(e == 'b')  out += " ";
         else if(e == 'f')  out += "\f";
         else if(e == 'u')
           {
            // Not expected in these files. Skipping the escape and the four
            // hex digits keeps the cursor honest without pretending to decode.
            i += 4;
           }
         else               out += StringSubstr(s, i, 1);
         i++;
         continue;
        }
      out += StringSubstr(s, i, 1);
      i++;
     }
   return(false);   // unterminated
  }

//+------------------------------------------------------------------+
int ABJ_ParseValue(const string &s, int &i);

//+------------------------------------------------------------------+
int ABJ_ParseObject(const string &s, int &i)
  {
   int self = ABJ_NewNode(ABJ_OBJ);
   int last_child = -1;
   // `i` points at '{' (ABJ_ParseValue skipped the leading whitespace). Step
   // over the brace, then skip again -- pretty-printed JSON puts a newline and
   // indentation between the brace and the first key, and a key reader that
   // does not skip whitespace will fail on every multi-line object.
   i++;
   i = ABJ_SkipWhitespace(s, i);
   if(i < StringLen(s) && StringGetCharacter(s, i) == '}')
     {
      i++;
      return(self);
     }
   while(i < StringLen(s))
     {
      // The key must be read into a local first: ABJ_ParseValue is what
      // allocates the node the key belongs to, so it has to run first.
      string key = "";
      if(!ABJ_ParseString(s, i, key))
         return(-1);
      i = ABJ_SkipWhitespace(s, i);
      if(i >= StringLen(s) || StringGetCharacter(s, i) != ':')
         return(-1);
      i++;
      int child = ABJ_ParseValue(s, i);
      if(child < 0)
         return(-1);
      g_abj_nodes[child].key = key;
      if(last_child < 0)
         g_abj_nodes[self].first_child = child;
      else
         g_abj_nodes[last_child].next_sibling = child;
      last_child = child;
      i = ABJ_SkipWhitespace(s, i);
      if(i < StringLen(s) && StringGetCharacter(s, i) == ',')
        {
         i++;
         i = ABJ_SkipWhitespace(s, i);   // next key may be on a new line
         continue;
        }
      if(i < StringLen(s) && StringGetCharacter(s, i) == '}')
        {
         i++;
         return(self);
        }
      return(-1);
     }
   return(-1);
  }

//+------------------------------------------------------------------+
int ABJ_ParseArray(const string &s, int &i)
  {
   int self = ABJ_NewNode(ABJ_ARR);
   int last_child = -1;
   i++;                                // step over '['
   i = ABJ_SkipWhitespace(s, i);
   if(i < StringLen(s) && StringGetCharacter(s, i) == ']')
     {
      i++;
      return(self);
     }
   while(i < StringLen(s))
     {
      int child = ABJ_ParseValue(s, i);
      if(child < 0)
         return(-1);
      if(last_child < 0)
         g_abj_nodes[self].first_child = child;
      else
         g_abj_nodes[last_child].next_sibling = child;
      last_child = child;
      i = ABJ_SkipWhitespace(s, i);
      if(i < StringLen(s) && StringGetCharacter(s, i) == ',')
        {
         i++;
         continue;
        }
      if(i < StringLen(s) && StringGetCharacter(s, i) == ']')
        {
         i++;
         return(self);
        }
      return(-1);
     }
   return(-1);
  }

//+------------------------------------------------------------------+
int ABJ_ParseValue(const string &s, int &i)
  {
   i = ABJ_SkipWhitespace(s, i);
   if(i >= StringLen(s))
      return(-1);
   ushort c = StringGetCharacter(s, i);
   if(c == '{')
      return(ABJ_ParseObject(s, i));
   if(c == '[')
      return(ABJ_ParseArray(s, i));
   if(c == '"')
     {
      int self = ABJ_NewNode(ABJ_STR);
      if(!ABJ_ParseString(s, i, g_abj_nodes[self].str))
         return(-1);
      return(self);
     }
   if(StringSubstr(s, i, 4) == "null")
     {
      int self = ABJ_NewNode(ABJ_NULL);
      i += 4;
      return(self);
     }
   if(StringSubstr(s, i, 4) == "true")
     {
      int self = ABJ_NewNode(ABJ_BOOL);
      g_abj_nodes[self].bval = true;
      i += 4;
      return(self);
     }
   if(StringSubstr(s, i, 5) == "false")
     {
      int self = ABJ_NewNode(ABJ_BOOL);
      g_abj_nodes[self].bval = false;
      i += 5;
      return(self);
     }
   // number
   int start = i;
   if(i < StringLen(s) && (StringGetCharacter(s, i) == '-' || StringGetCharacter(s, i) == '+'))
      i++;
   while(i < StringLen(s))
     {
      ushort d = StringGetCharacter(s, i);
      bool digit = (d >= '0' && d <= '9');
      if(d == '.' || d == 'e' || d == 'E' || d == '-' || d == '+')
         i++;
      else if(digit)
         i++;
      else
         break;
     }
   if(i == start)
      return(-1);
   int self = ABJ_NewNode(ABJ_NUM);
   g_abj_nodes[self].num = StringToDouble(StringSubstr(s, start, i - start));
   return(self);
  }

//+------------------------------------------------------------------+
//| ABJ_Parse                                                         |
//+------------------------------------------------------------------+
int ABJ_Parse(const string &text)
  {
   ABJ_Reset();
   int i = 0;
   return(ABJ_ParseValue(text, i));
  }

//+------------------------------------------------------------------+
//| ABJ_FindKey -- first child of `parent` with the given key.        |
//+------------------------------------------------------------------+
int ABJ_FindKey(const int parent, const string &key)
  {
   if(parent < 0)
      return(-1);
   int c = g_abj_nodes[parent].first_child;
   while(c >= 0)
     {
      if(g_abj_nodes[c].key == key)
         return(c);
      c = g_abj_nodes[c].next_sibling;
     }
   return(-1);
  }

//+------------------------------------------------------------------+
//| ABJ_Nth -- the n-th child of an array.                           |
//+------------------------------------------------------------------+
int ABJ_Nth(const int parent, const int n)
  {
   if(parent < 0)
      return(-1);
   int c = g_abj_nodes[parent].first_child;
   for(int k = 0; k < n && c >= 0; k++)
      c = g_abj_nodes[c].next_sibling;
   return(c);
  }

//+------------------------------------------------------------------+
int ABJ_CountChildren(const int parent)
  {
   if(parent < 0)
      return(0);
   int n = 0;
   int c = g_abj_nodes[parent].first_child;
   while(c >= 0)
     {
      n++;
      c = g_abj_nodes[c].next_sibling;
     }
   return(n);
  }

#endif // ALBROOKS_JSON_MQH
//+------------------------------------------------------------------+
