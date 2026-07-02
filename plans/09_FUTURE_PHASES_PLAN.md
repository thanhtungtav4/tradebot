# 09_FUTURE_PHASES_PLAN - Future Phases

## 1. Mục tiêu

Giữ ranh giới future rõ để MVP không phình ra, nhưng vẫn có đường mở rộng sạch sau khi bot chạy ổn định.

## 2. Future phases

### Phase Future A - TradingView signal/confirmation mode

- Add `POST /api/v1/webhooks/tradingview/signals`.
- Support confirmation or external signal modes.
- Do not let Pine Script replace backend strategy when mode is backend-analysis.

### Phase Future B - MT5 connector

- Requires Windows VPS/host with MT5 terminal.
- Connector pushes candles/ticks to backend.
- Uses same canonical candle model.
- Does not modify Strategy Engine core.

### Phase Future C - MT4 bridge

- MQL4 EA sends candles/ticks to backend.
- Uses source secret/account/broker mapping.
- Updates `data_sources` and `data_source_feeds`.

### Phase Future D - AI filter

- Runs after rule strategy and risk pre-check.
- Cannot create BUY/SELL or edit prices.
- Only validates, adjusts confidence and adds risk note.

### Phase Future E - Backtest/report

- Add outcome tracking.
- Manual outcome first.
- Auto TP/SL scan later.
- Report winrate by group/strategy/symbol/timeframe.

### Phase Future F - Auto-trade

- Add Execution Engine separate from Signal Engine.
- Requires kill switch, max loss, max exposure, manual approval mode.
- Strategy Engine never sends orders directly.

## 3. Acceptance criteria for any future phase

- Existing MVP tests still pass.
- No change breaks TradingView bar webhook MVP.
- No change bypasses Admin Console audit.
- New source/strategy does not require hardcoding group-specific logic.

