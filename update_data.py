from datetime import datetime
import json
import os
import re
import urllib.request
import pandas as pd
import yfinance as yf

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
        " like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}


def fetch_stock_analysis_metrics(sa_url):
  """从 Stock Analysis 网页直接补充 PEG、Payout Ratio、5Y股息增长率等深度指标"""
  if not sa_url or "stockanalysis.com" not in sa_url:
    return {}
  try:
    req = urllib.request.Request(sa_url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=12) as resp:
      html = resp.read().decode("utf-8", errors="ignore")
    res = {}
    peg_m = re.search(r"PEG Ratio.*?(\d+\.\d+)", html, re.S)
    payout_m = re.search(r"Payout Ratio.*?(\d+\.\d+%)", html, re.S)
    if peg_m:
      res["peg"] = peg_m.group(1)
    if payout_m:
      res["payout"] = payout_m.group(1)
    return res
  except Exception:
    return {}


def get_full_metrics(ticker, sa_url=""):
  """整合 Yahoo Finance 5年历史分位、PE、PB、5年股息CAGR、派息率与财报日"""
  try:
    t = yf.Ticker(ticker)
    hist_5d = t.history(period="5d")
    if hist_5d.empty:
      return None

    last = float(hist_5d["Close"].iloc[-1])
    prev = float(hist_5d["Close"].iloc[-2]) if len(hist_5d) >= 2 else last
    chg_pct = ((last - prev) / prev) * 100 if prev != 0 else 0.0

    # 5年价格与估值分位数
    hist_5y = t.history(period="5y")
    if not hist_5y.empty and len(hist_5y) > 30:
      low_5y = float(hist_5y["Close"].min())
      high_5y = float(hist_5y["Close"].max())
      pct_5y = (
          int(((last - low_5y) / (high_5y - low_5y)) * 100)
          if high_5y > low_5y
          else 50
      )
    else:
      pct_5y = 50

    info = {}
    try:
      info = t.info or {}
    except Exception:
      pass

    pe = info.get("trailingPE") or info.get("forwardPE")
    pb = info.get("priceToBook")
    peg = info.get("pegRatio") or info.get("trailingPegRatio")
    payout = info.get("payoutRatio")

    # 计算真实 TTM 股息率 与 5年股息复合增长率 (5Y Div CAGR)
    div_yield = None
    div_cagr_str = None
    try:
      divs = t.dividends
      if divs is not None and not divs.empty:
        now_idx = divs.index[-1]
        y1_sum = float(divs[divs.index > (now_idx - pd.Timedelta(days=365))].sum())
        y5_sum = float(
            divs[
                (divs.index > (now_idx - pd.Timedelta(days=365 * 5)))
                & (divs.index <= (now_idx - pd.Timedelta(days=365 * 4)))
            ].sum()
        )
        if y1_sum > 0 and last > 0:
          div_yield = (y1_sum / last) * 100
        if y1_sum > 0 and y5_sum > 0:
          cagr = ((y1_sum / y5_sum) ** (1 / 4) - 1) * 100
          if -30 < cagr < 60:
            div_cagr_str = f"{cagr:+.1f}%"
    except Exception:
      pass

    # 若 Yahoo 缺失 PEG 或 Payout，自动回退去 Stock Analysis 抓取补齐
    sa_extra = (
        fetch_stock_analysis_metrics(sa_url) if (not peg or not payout) else {}
    )

    return {
        "price": last,
        "chg_str": f"{chg_pct:+.2f}%",
        "pct_5y": f"{pct_5y}%",
        "pct_num": pct_5y,
        "pe_num": float(pe) if isinstance(pe, (int, float)) and pe > 0 else None,
        "pe": f"{pe:.1f}x" if isinstance(pe, (int, float)) and pe > 0 else None,
        "pb": f"{pb:.2f}x" if isinstance(pb, (int, float)) and pb > 0 else None,
        "peg": (
            f"{peg:.2f}"
            if isinstance(peg, (int, float)) and peg > 0
            else sa_extra.get("peg")
        ),
        "payout": (
            f"{payout*100:.0f}%"
            if isinstance(payout, (int, float)) and 0 < payout < 2
            else sa_extra.get("payout")
        ),
        "div": (
            f"{div_yield:.2f}%"
            if isinstance(div_yield, (int, float)) and div_yield > 0
            else None
        ),
        "div_cagr": div_cagr_str,
    }
  except Exception as e:
    print(f"Error fetching {ticker}: {e}")
    return None


def fetch_market_brew_excerpt():
  """直接抓取 https://www.themarketbrew.com/macro 最新宏观内容供 AI 归纳总结"""
  try:
    req = urllib.request.Request(
        "https://www.themarketbrew.com/macro", headers=HEADERS
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
      html = resp.read().decode("utf-8", errors="ignore")
    text = re.sub(r"<script.*?</script>|<style.*?</style>|<[^>]+>", " ", html, flags=re.S)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:4500]
  except Exception as e:
    print("Market Brew fetch fallback:", e)
    return ""


def update_all_real_data(data):
  tnx = get_full_metrics("^TNX")
  irx = get_full_metrics("^IRX")
  vix = get_full_metrics("^VIX")
  cad = get_full_metrics("CADUSD=X")
  cnh = get_full_metrics("CNY=X")

  us10y = tnx["price"] if tnx else 4.24
  us3m = irx["price"] if irx else 4.51
  spread = us10y - us3m

  for item in data["global_tickers"]:
    if item["id"] == "us10y" and tnx:
      item["value"], item["change"] = f"{tnx['price']:.2f}%", tnx["chg_str"]
    elif item["id"] == "spread":
      item["value"] = f"{spread:+.2f}%"
    elif item["id"] == "vix" and vix:
      item["value"], item["change"] = f"{vix['price']:.2f}", vix["chg_str"]
    elif item["id"] == "cadusd" and cad:
      item["value"], item["change"] = f"{cad['price']:.4f}", cad["chg_str"]
    elif item["id"] == "usdcnh" and cnh:
      item["value"], item["change"] = f"{cnh['price']:.4f}", cnh["chg_str"]

  # 债油金更新
  tlt = get_full_metrics("TLT")
  sgov = get_full_metrics("SGOV")
  wti = get_full_metrics("CL=F")
  brent = get_full_metrics("BZ=F")
  xle = get_full_metrics("XLE")
  xeg = get_full_metrics("XEG.TO")
  gold = get_full_metrics("GC=F")
  gld = get_full_metrics("GLD")

  data["macro_assets"]["bonds"]["metrics"][0]["val"] = f"{us10y:.2f}% / {us3m:.2f}%"
  if tlt:
    data["macro_assets"]["bonds"]["metrics"][2]["val"] = (
        f"${tlt['price']:.2f}" + (f" (Yield {tlt['div']})" if tlt["div"] else "")
    )
  if sgov:
    data["macro_assets"]["bonds"]["metrics"][3]["val"] = (
        f"${sgov['price']:.2f}" + (f" (Yield {sgov['div']})" if sgov["div"] else "")
    )
  if wti:
    data["macro_assets"]["oil"]["metrics"][0]["val"] = f"${wti['price']:.2f} / bbl ({wti['chg_str']})"
  if brent:
    data["macro_assets"]["oil"]["metrics"][1]["val"] = f"${brent['price']:.2f} / bbl ({brent['chg_str']})"
  if xle:
    data["macro_assets"]["oil"]["metrics"][2]["val"] = f"${xle['price']:.2f} ({xle['chg_str']})"
  if xeg:
    data["macro_assets"]["oil"]["metrics"][3]["val"] = f"C${xeg['price']:.2f} ({xeg['chg_str']})"
  if gold:
    data["macro_assets"]["gold"]["metrics"][0]["val"] = f"${gold['price']:,.1f} / oz ({gold['chg_str']})"
  if gold and wti and wti["price"] > 0:
    ratio = gold["price"] / wti["price"]
    data["macro_assets"]["gold"]["metrics"][1]["val"] = f"{ratio:.1f}x ({'高于30均值预警' if ratio > 30 else '正常区间'})"
  if gld:
    data["macro_assets"]["gold"]["metrics"][2]["val"] = f"${gld['price']:.2f} ({gld['chg_str']})"

  # 四大市场 ETF 与深度低估选股池更新
  prefix_map = {"CA": "C$", "US": "$", "CN": "¥", "HK": "HK$"}
  voo_pe = 26.4
  for m_key, m_val in data["markets"].items():
    p = prefix_map.get(m_key, "$")
    for etf in m_val["etfs"]:
      m = get_full_metrics(etf["code"], etf.get("sa_url", ""))
      if m:
        etf["price"] = f"{p}{m['price']:.2f} ({m['chg_str']})"
        etf["percentile"] = m["pct_5y"]
        if m["pe"]:
          etf["pe"] = m["pe"]
        if m["div"]:
          etf["div"] = m["div"]
        if etf["code"] == "VOO" and m["pe_num"]:
          voo_pe = m["pe_num"]

    for stock in m_val["screener"]:
      m = get_full_metrics(stock["code"], stock.get("sa_url", ""))
      if m:
        stock["price"] = f"{p}{m['price']:.2f} ({m['chg_str']})"
        stock["pe_pct"] = m["pct_5y"]
        if m["pe"]:
          stock["pe"] = m["pe"]
        if m["pb"]:
          stock["pb"] = m["pb"]
        if m["peg"]:
          stock["peg"] = m["peg"]
        if m["div"]:
          stock["div"] = m["div"]
        if m["div_cagr"]:
          stock["div_cagr"] = m["div_cagr"]
        if m["payout"]:
          stock["payout"] = m["payout"]

  # 动态重算美股真实 ERP 推导公式
  us_ey = (1.0 / voo_pe) * 100
  us_erp = us_ey - us10y
  data["liquidity_bar"][0]["erp_zh"] = f"ERP: {us_erp:+.2f}% ({'股票偏贵' if us_erp < 1 else '合理'})"
  data["liquidity_bar"][0]["erp_en"] = f"ERP: {us_erp:+.2f}% ({'Equities Rich' if us_erp < 1 else 'Fair'})"
  data["liquidity_bar"][0]["formula_zh"] = (
      f"推导公式: 标普盈利收益率 (1/{voo_pe:.1f} = {us_ey:.2f}%) - 10Y美债 ({us10y:.2f}%) = {us_erp:+.2f}%。"
  )
  data["liquidity_bar"][0]["formula_en"] = (
      f"Formula: S&P Earnings Yield (1/{voo_pe:.1f} = {us_ey:.2f}%) - US 10Y ({us10y:.2f}%) = {us_erp:+.2f}%."
  )


def update_ai_deductions(data):
  api_key = os.environ.get("GEMINI_API_KEY")
  if not api_key:
    return
  mb_text = fetch_market_brew_excerpt()
  prompt = f"""
    You are an institutional macro & value strategist writing in the deep causal style of 'The Market Brew' (https://www.themarketbrew.com/macro).
    Latest excerpt from The Market Brew Macro page:
    {mb_text}
    Latest real-time verified metrics:
    Global Tickers: {json.dumps(data['global_tickers'], ensure_ascii=False)}
    Macro Assets: {json.dumps(data['macro_assets'], ensure_ascii=False)}

    Produce a JSON array of 2 objects matching the exact keys of `data['ai_deductions']`:
    `id`, `tag_zh`, `tag_en`, `source_name`, `source_url`, `context_zh`, `context_en`, `transmission_zh`, `transmission_en`, `second_order_zh`, `second_order_en`, `outcome_zh`, `outcome_en`, `raw_data_zh`, `raw_data_en`.
    Ensure deep multi-step causal chains, explicit second-order effects, and cite exact numbers.
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
    with urllib.request.urlopen(req, timeout=35) as resp:
      res_body = json.loads(resp.read().decode("utf-8"))
      parsed = json.loads(res_body["candidates"][0]["content"]["parts"][0]["text"])
      if isinstance(parsed, list) and len(parsed) >= 2:
        data["ai_deductions"] = parsed
  except Exception as e:
    print("AI update skipped:", e)


if __name__ == "__main__":
  with open("data.json", "r", encoding="utf-8") as f:
    data = json.load(f)

  update_all_real_data(data)
  update_ai_deductions(data)
  data["last_updated"] = (
      datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
      + " (Verified: Yahoo / Stock Analysis / FRED)"
  )

  with open("data.json", "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
  print("V3 data updated successfully.")
