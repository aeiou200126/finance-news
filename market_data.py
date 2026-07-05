# -*- coding: utf-8 -*-
"""
market_data.py
================
每日金融市場資訊聚合網站 —— 市場數據抓取模組

功能說明：
    使用 yfinance（免費、無需 API Key）抓取以下關鍵市場數據：
        - 美股：S&P 500、Nasdaq、道瓊工業指數
        - 台股：加權指數
        - 美債：10 年期美國公債殖利率
        - 匯率：美元/台幣、美元指數

設計原則：
    1. 每個標的獨立抓取、獨立處理例外，單一標的失敗不影響其他標的。
    2. 統一計算「漲跌點數」與「漲跌幅（%）」，方便前端直接顯示紅漲綠跌。
    3. 最終統一輸出成 JSON，方便後端 API / 前端頁面讀取。

⚠️ 注意：
    - yfinance 是透過抓取 Yahoo Finance 網站資料運作，並非官方公開 API，
      Yahoo 端若調整資料結構，可能導致抓取失敗，因此仍需保留完整的錯誤處理。
    - 免費方案的資料通常有 15-20 分鐘左右的延遲，不適合做高頻交易，
      但用於「每日市場摘要」的场景已經足够。
"""

import json
import logging
from datetime import datetime

import yfinance as yf

# -------------------------------------------------------------------
# 基本設定
# -------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# 標的設定表
# key         : 內部代號（給程式/前端用，不會顯示給使用者看）
# symbol      : yfinance 對應的 ticker 代碼
# display_name: 顯示在畫面上的中文名稱
# category    : 分類，方便前端分組顯示（us_stock / tw_stock / bond / fx）
# -------------------------------------------------------------------

WATCHLIST = [
    {"key": "sp500", "symbol": "^GSPC", "display_name": "S&P 500", "category": "us_stock"},
    {"key": "nasdaq", "symbol": "^IXIC", "display_name": "那斯達克指數", "category": "us_stock"},
    {"key": "dowjones", "symbol": "^DJI", "display_name": "道瓊工業指數", "category": "us_stock"},
    {"key": "taiex", "symbol": "^TWII", "display_name": "台股加權指數", "category": "tw_stock"},
    {"key": "us10y", "symbol": "^TNX", "display_name": "美國10年期公債殖利率", "category": "bond"},
    {"key": "usdtwd", "symbol": "USDTWD=X", "display_name": "美元/台幣", "category": "fx"},
    {"key": "dxy", "symbol": "DX-Y.NYB", "display_name": "美元指數", "category": "fx"},
]


def fetch_single_quote(symbol, display_name):
    """
    抓取單一標的的最新價格、漲跌點數、漲跌幅。

    做法說明：
        使用 yf.Ticker(symbol).history() 抓最近兩個交易日的收盤價，
        用「今天」與「昨天」的收盤價相減，計算漲跌。
        （這樣比只抓即時報價更穩定，避免遇到假日或盤前沒有即時價格的狀況）

    參數：
        symbol       (str): yfinance 代碼，例如 "^GSPC"
        display_name (str): 顯示名稱，只用於記錄 log 訊息

    回傳：
        dict：成功時包含 price / change / change_percent / status="ok"
              失敗時 price 等欄位為 None，並附上 status="error" 與錯誤訊息
    """
    try:
        ticker = yf.Ticker(symbol)

        # 抓最近 5 天資料，是為了確保遇到連假時仍能抓到至少兩筆收盤價
        hist = ticker.history(period="5d")

        if hist.empty or len(hist) < 2:
            raise ValueError("抓取到的歷史資料筆數不足，可能是新掛牌標的或代碼錯誤")

        latest_close = hist["Close"].iloc[-1]
        previous_close = hist["Close"].iloc[-2]

        change = latest_close - previous_close
        change_percent = (change / previous_close) * 100

        return {
            "price": round(float(latest_close), 2),
            "change": round(float(change), 2),
            "change_percent": round(float(change_percent), 2),
            "status": "ok",
            "error_message": None,
        }

    except Exception as e:
        # 任何錯誤（網路問題、代碼失效、資料格式異常等）都在這裡被攔截
        logger.warning(f"[{display_name} / {symbol}] 抓取失敗：{e}")
        return {
            "price": None,
            "change": None,
            "change_percent": None,
            "status": "error",
            "error_message": str(e),
        }


def fetch_all_market_data():
    """
    依序抓取 WATCHLIST 中所有標的的數據。

    回傳：
        dict，格式如下：
        {
            "updated_at": "2026-07-05 16:30:00",
            "data": [
                {
                    "key": "sp500",
                    "display_name": "S&P 500",
                    "category": "us_stock",
                    "price": 5487.32,
                    "change": 12.5,
                    "change_percent": 0.23,
                    "status": "ok",
                    "error_message": None
                },
                ...
            ]
        }
    """
    result = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data": [],
    }

    for item in WATCHLIST:
        logger.info(f"正在抓取：{item['display_name']}（{item['symbol']}）")

        quote = fetch_single_quote(item["symbol"], item["display_name"])

        result["data"].append({
            "key": item["key"],
            "display_name": item["display_name"],
            "category": item["category"],
            **quote,
        })

    success_count = sum(1 for d in result["data"] if d["status"] == "ok")
    logger.info(f"市場數據抓取完成：成功 {success_count} / 共 {len(WATCHLIST)} 個標的")

    return result


def save_to_json(data, filepath="market_data.json"):
    """將抓取結果存成 JSON 檔案，方便後端 API / 前端讀取。"""
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"市場數據已成功寫入：{filepath}")
    except Exception as e:
        logger.error(f"寫入 JSON 檔案失敗：{e}")


# -------------------------------------------------------------------
# 程式進入點
# -------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("=== 開始執行市場數據抓取任務 ===")
    market_data = fetch_all_market_data()
    save_to_json(market_data, "market_data.json")

    # 簡單印出結果摘要，方便直接執行時檢查成果
    print("\n=== 市場數據摘要 ===")
    for item in market_data["data"]:
        if item["status"] == "ok":
            arrow = "▲" if item["change"] >= 0 else "▼"
            print(f"{item['display_name']:12s}: {item['price']:>10} "
                  f"{arrow} {item['change']:+.2f} ({item['change_percent']:+.2f}%)")
        else:
            print(f"{item['display_name']:12s}: 抓取失敗 - {item['error_message']}")
    logger.info("=== 市場數據抓取任務結束 ===")
