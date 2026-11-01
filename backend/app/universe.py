"""Default symbol lists shown by terminal functions (WEI, FX, CRYP, CMDTY, W).

Symbols use TradingView notation "EXCHANGE:TICKER". Edit freely — the frontend
fetches these from GET /api/universe. Symbols marked "unverified" in
docs/DATA_SOURCES.md have not been confirmed against the live TradingView feed.
"""
from __future__ import annotations

UNIVERSE: dict[str, list[dict[str, str]]] = {
    # World Equity Indices
    "WEI": [
        {"symbol": "SP:SPX", "label": "S&P 500", "region": "Americas"},
        {"symbol": "NASDAQ:NDX", "label": "NASDAQ 100", "region": "Americas"},
        {"symbol": "DJ:DJI", "label": "Dow Jones Industrial", "region": "Americas"},
        {"symbol": "TVC:RUT", "label": "Russell 2000", "region": "Americas"},
        {"symbol": "TVC:VIX", "label": "CBOE VIX", "region": "Americas"},
        {"symbol": "TVC:SX5E", "label": "Euro Stoxx 50", "region": "EMEA"},
        {"symbol": "TVC:UKX", "label": "FTSE 100", "region": "EMEA"},
        {"symbol": "XETR:DAX", "label": "DAX", "region": "EMEA"},
        {"symbol": "TVC:CAC40", "label": "CAC 40", "region": "EMEA"},
        {"symbol": "TVC:NI225", "label": "Nikkei 225", "region": "APAC"},
        {"symbol": "TVC:TOPIX", "label": "TOPIX", "region": "APAC"},
        {"symbol": "TVC:HSI", "label": "Hang Seng", "region": "APAC"},
        {"symbol": "SSE:000001", "label": "Shanghai Composite", "region": "APAC"},
        {"symbol": "TVC:KOSPI", "label": "KOSPI", "region": "APAC"},
    ],
    "FX": [
        {"symbol": "FX:USDJPY", "label": "USD/JPY"},
        {"symbol": "FX:EURUSD", "label": "EUR/USD"},
        {"symbol": "FX:GBPUSD", "label": "GBP/USD"},
        {"symbol": "FX:EURJPY", "label": "EUR/JPY"},
        {"symbol": "FX:AUDUSD", "label": "AUD/USD"},
        {"symbol": "FX:USDCHF", "label": "USD/CHF"},
        {"symbol": "FX:USDCAD", "label": "USD/CAD"},
        {"symbol": "FX_IDC:USDCNH", "label": "USD/CNH"},
        {"symbol": "TVC:DXY", "label": "Dollar Index"},
    ],
    "RATES": [
        {"symbol": "TVC:US02Y", "label": "US 2Y"},
        {"symbol": "TVC:US10Y", "label": "US 10Y"},
        {"symbol": "TVC:US30Y", "label": "US 30Y"},
        {"symbol": "TVC:DE10Y", "label": "Germany 10Y"},
        {"symbol": "TVC:GB10Y", "label": "UK 10Y"},
        {"symbol": "TVC:JP10Y", "label": "Japan 10Y"},
    ],
    "CMDTY": [
        {"symbol": "TVC:GOLD", "label": "Gold"},
        {"symbol": "TVC:SILVER", "label": "Silver"},
        {"symbol": "TVC:USOIL", "label": "WTI Crude"},
        {"symbol": "TVC:UKOIL", "label": "Brent Crude"},
        {"symbol": "COMEX:HG1!", "label": "Copper"},
        {"symbol": "NYMEX:NG1!", "label": "Natural Gas"},
    ],
    "CRYP": [
        {"symbol": "BINANCE:BTCUSDT", "label": "Bitcoin"},
        {"symbol": "BINANCE:ETHUSDT", "label": "Ethereum"},
        {"symbol": "BINANCE:SOLUSDT", "label": "Solana"},
        {"symbol": "BINANCE:XRPUSDT", "label": "XRP"},
        {"symbol": "BINANCE:BNBUSDT", "label": "BNB"},
        {"symbol": "BINANCE:DOGEUSDT", "label": "Dogecoin"},
    ],
    # Default watchlist
    "W": [
        {"symbol": "NASDAQ:AAPL", "label": "Apple"},
        {"symbol": "NASDAQ:MSFT", "label": "Microsoft"},
        {"symbol": "NASDAQ:NVDA", "label": "NVIDIA"},
        {"symbol": "NASDAQ:AMZN", "label": "Amazon"},
        {"symbol": "NASDAQ:GOOGL", "label": "Alphabet"},
        {"symbol": "NASDAQ:META", "label": "Meta"},
        {"symbol": "NASDAQ:TSLA", "label": "Tesla"},
        {"symbol": "NYSE:JPM", "label": "JPMorgan"},
        {"symbol": "TSE:7203", "label": "Toyota"},
        {"symbol": "TSE:6758", "label": "Sony"},
        {"symbol": "TSE:8306", "label": "MUFG"},
        {"symbol": "TSE:9984", "label": "SoftBank Group"},
    ],
}

# Ticker tape at the top of the terminal
TAPE: list[str] = [
    "SP:SPX", "NASDAQ:NDX", "DJ:DJI", "TVC:NI225", "TVC:VIX", "TVC:US10Y",
    "FX:USDJPY", "FX:EURUSD", "TVC:GOLD", "TVC:USOIL", "BINANCE:BTCUSDT",
]


def all_symbols() -> list[str]:
    seen: dict[str, None] = {}
    for items in UNIVERSE.values():
        for it in items:
            seen[it["symbol"]] = None
    for s in TAPE:
        seen[s] = None
    return list(seen)


def label_for(symbol: str) -> str | None:
    for items in UNIVERSE.values():
        for it in items:
            if it["symbol"] == symbol:
                return it["label"]
    return None
