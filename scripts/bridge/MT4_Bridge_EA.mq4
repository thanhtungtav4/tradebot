//+------------------------------------------------------------------+
//|                                                MT4_Bridge_EA.mq4 |
//|                                  Copyright 2026, tradebot team   |
//|                                             https://tradebot.org |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, tradebot team"
#property link      "https://tradebot.org"
#property version   "1.00"
#property strict

//--- Input Parameters
input string   BackendURL        = "http://localhost:8000/api/v1/bridge";
input string   WebhookToken      = "CHANGE_ME_webhook_token";
input string   BodySecret        = "CHANGE_ME_body_secret";
input string   BrokerSymbolName  = "";       // Leave empty to use current chart symbol automatically
input string   BrokerName        = "ICMarkets";
input string   AccountId         = "123456"; // Your trading account ID
input int      HeartbeatInterval = 60;       // Heartbeat interval in seconds

//--- Global Variables
datetime LastBarTime = 0;
datetime LastHeartbeat = 0;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   Print("MT4 Bridge EA Initialized. Account: ", AccountId, " Broker: ", BrokerName);
   LastBarTime = Time[0];
   LastHeartbeat = TimeCurrent();
   
   // Send initial heartbeat
   SendHeartbeat("OK", "EA initialized successfully");
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   SendHeartbeat("PAUSED", "EA stopped or uninstalled");
   Print("MT4 Bridge EA Deinitialized.");
}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
{
   // Check if a new bar closed
   if(Time[0] != LastBarTime)
   {
      // The closed bar is index 1 (previous bar)
      datetime closedBarTime = Time[1];
      double o = Open[1];
      double h = High[1];
      double l = Low[1];
      double c = Close[1];
      double v = Volume[1];
      
      SendCandle(closedBarTime, o, h, l, c, v);
      LastBarTime = Time[0];
   }
   
   // Check heartbeat timer
   if(TimeCurrent() - LastHeartbeat >= HeartbeatInterval)
   {
      SendHeartbeat("OK", "EA active");
      LastHeartbeat = TimeCurrent();
   }
}

//+------------------------------------------------------------------+
//| Helper to map timeframe to standard names                        |
//+------------------------------------------------------------------+
string GetTimeframeName()
{
   switch(Period())
   {
      case PERIOD_M5:  return "M5";
      case PERIOD_M15: return "M15";
      case PERIOD_H1:  return "H1";
      case PERIOD_H4:  return "H4";
      default:         return "M15"; // fallback default
   }
}

//+------------------------------------------------------------------+
//| Send closed bar candle to API                                    |
//+------------------------------------------------------------------+
void SendCandle(datetime timeVal, double o, double h, double l, double c, double v)
{
   string sym = (BrokerSymbolName == "") ? Symbol() : BrokerSymbolName;
   string tf = GetTimeframeName();
   
   // Convert time to ISO format (e.g. 2026-07-01T15:00:00Z)
   string isoTime = TimeToStr(timeVal, TIME_DATE) + "T" + TimeToStr(timeVal, TIME_MINUTES) + ":00Z";
   isoTime = StringReplaceAll(isoTime, ".", "-");
   
   // Format payload as JSON string
   string payload = "{"
      + "\"secret\":\"" + BodySecret + "\","
      + "\"symbol\":\"" + sym + "\","
      + "\"timeframe\":\"" + tf + "\","
      + "\"time\":\"" + isoTime + "\","
      + "\"open\":" + DoubleToString(o, _Digits) + ","
      + "\"high\":" + DoubleToString(h, _Digits) + ","
      + "\"low\":" + DoubleToString(l, _Digits) + ","
      + "\"close\":" + DoubleToString(c, _Digits) + ","
      + "\"volume\":" + DoubleToString(v, 0) + ","
      + "\"account_id\":\"" + AccountId + "\","
      + "\"broker\":\"" + BrokerName + "\""
      + "}";
      
   string url = BackendURL + "/mt4/candles/" + WebhookToken;
   SendRequest(url, payload);
}

//+------------------------------------------------------------------+
//| Send heartbeat to API                                           |
//+------------------------------------------------------------------+
void SendHeartbeat(string status, string message)
{
   string payload = "{"
      + "\"secret\":\"" + BodySecret + "\","
      + "\"status\":\"" + status + "\","
      + "\"details\":{"
         + "\"message\":\"" + message + "\","
         + "\"account_id\":\"" + AccountId + "\","
         + "\"broker\":\"" + BrokerName + "\""
      + "}"
      + "}";
      
   string url = BackendURL + "/heartbeat/" + WebhookToken;
   SendRequest(url, payload);
}

//+------------------------------------------------------------------+
//| Post HTTP request                                                |
//+------------------------------------------------------------------+
void SendRequest(string url, string payload)
{
   char postData[];
   char resultData[];
   string headers = "Content-Type: application/json\r\n";
   
   StringToCharArray(payload, postData, 0, StringLen(payload));
   
   ResetLastError();
   int res = WebRequest("POST", url, headers, 3000, postData, resultData, headers);
   
   if(res == -1)
   {
      Print("WebRequest failed. Error code: ", GetLastError());
      if(GetLastError() == 4060)
      {
         Print("Please add URL '" + BackendURL + "' to the list of allowed WebRequest URLs in MT4 Options -> Expert Advisors.");
      }
   }
   else
   {
      string responseText = CharArrayToString(resultData);
      Print("Server Response (", res, "): ", responseText);
   }
}

//+------------------------------------------------------------------+
//| Replace substrings helper                                        |
//+------------------------------------------------------------------+
string StringReplaceAll(string text, string from, string to)
{
   string result = text;
   int pos = StringFind(result, from);
   while(pos >= 0)
   {
      result = StringSubstr(result, 0, pos) + to + StringSubstr(result, pos + StringLen(from));
      pos = StringFind(result, from, pos + StringLen(to));
   }
   return result;
}
