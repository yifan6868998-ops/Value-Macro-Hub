from datetime import datetime
import json
import os
import urllib.request
import yfinance as yf


def fetch_price(ticker, fmt="{:.2f}"):
  try:
    t = yf.Ticker(ticker)
    hist = t.history(period="5d")
    if len(hist) >= 2:
      last = hist["Close"].iloc[-1]
      prev = hist["Close"].iloc[-2]
      chg = ((last - prev) / prev) * 100
      return fmt.format(last), f"{chg:+.2f}%"
    elif len(hist) == 1:
      return fmt.format(hist["Close"].iloc[-1]), "0.00%"
  except Exception:
    pass
  return None, None


def update_market_snapshot(data):
  # 1. 更新顶部宏观定价锚
  us10y, us10y_chg = fetch_price("^TNX", "{:.2f}%")
  vix, vix_chg = fetch_price("^VIX", "{:.1f}")
  cad, cad_chg = fetch_price("CADUSD=X", "{:.3f}")
  cnh, cnh_chg = fetch_price("CNH=X", "{:.3f}")

  ticker_map = {
      "us10y": (us10y, us10y_chg),
      "vix": (vix, vix_chg),
      "cadusd": (cad, cad_chg),
      "usdcnh": (cnh, cnh_chg),
  }
  for item in data["global_tickers"]:
    if item["id"] in ticker_map and ticker_map[item["id"]][0]:
      item["value"], item["change"] = ticker_map[item["id"]]

  # 2. 更新债油金板块实时价格
  wti, _ = fetch_price("CL=F", "${:.2f} / bbl")
  brent, _ = fetch_price("BZ=F", "${:.2f} / bbl")
  gold, _ = fetch_price("GC=F", "${:,.0f} / oz")
  tlt, _ = fetch_price("TLT", "${:.2f}")
  gld, _ = fetch_price("GLD", "${:.2f}")

  if wti:
    data["macro_assets"]["oil"]["metrics"][0]["val"] = wti
  if brent:
    data["macro_assets"]["oil"]["metrics"][1]["val"] = brent
  if gold:
    data["macro_assets"]["gold"]["metrics"][0]["val"] = gold
  if tlt:
    data["macro_assets"]["bonds"]["metrics"][2]["val"] = tlt
  if gld:
    data["macro_assets"]["gold"]["metrics"][2]["val"] = gld

  # 3. 更新四大市场核心 ETF 与低估股票最新价
  prefix_map = {"CA": "C$", "US": "$", "CN": "¥", "HK": "HK$"}
  for m_key, m_val in data["markets"].items():
    p = prefix_map.get(m_key, "$")
    for etf in m_val["etfs"]:
      price, _ = fetch_price(etf["code"], p + "{:.2f}")
      if price:
        etf["price"] = price
    for stock in m_val["screener"]:
      price, _ = fetch_price(stock["code"], p + "{:.2f}")
      if price:
        stock["price"] = price


def update_ai_deductions(data):
  api_key = os.environ.get("GEMINI_API_KEY")
  if not api_key:
    print("No GEMINI_API_KEY configured, keeping existing AI deductions.")
    return

  prompt = f"""
    You are a veteran global macro & value investing strategist.
    Based on today's latest snapshot:
    Global Tickers: {json.dumps(data['global_tickers'], ensure_ascii=False)}
    Macro Assets: {json.dumps(data['macro_assets'], ensure_ascii=False)}
     Output STRICTLY valid JSON array of 2 objects matching the exact schema of `ai_deductions`:
    [
      {{
        "id": "deduction_1",
        "tag_zh": "...", "tag_en": "...",
        "event_zh": "...", "event_en": "...",
        "logic_zh": "...", "logic_en": "...",
        "outcome_zh": "...", "outcome_en": "...",
        "raw_data_zh": "...", "raw_data_en": "..."
      }},
      ...
    ]
    """
  url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
  payload = json.dumps({
      "contents": [{"parts": [{"text": prompt}]}],
      "generationConfig": {"responseMimeType": "application/json"},
  }).encode("utf-8")

  try:
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
      res_body = json.loads(resp.read().decode("utf-8"))
      text = res_body["candidates"][0]["content"]["parts"][0]["text"]
      parsed = json.loads(text)
      if isinstance(parsed, list) and len(parsed) >= 2:
        data["ai_deductions"] = parsed
  except Exception as e:
    print("AI update skipped:", e)


if __name__ == "__main__":
  with open("data.json", "r", encoding="utf-8") as f:
    data = json.load(f)

  update_market_snapshot(data)
  update_ai_deductions(data)
  data["last_updated"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

  with open("data.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
  print("data.json updated successfully.")
