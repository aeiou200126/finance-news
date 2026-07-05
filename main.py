# -*- coding: utf-8 -*-
"""
main.py
================
每日金融市場資訊聚合網站 —— 後端主程式

負責整合：
    1. 排程（APScheduler）：每天早上 08:00 自動抓取新聞與市場數據
    2. 資料庫（database.py）：把抓到的資料存起來
    3. API（FastAPI）：提供 /api/news、/api/market 給前端讀取
    4. 靜態網頁：提供 static/index.html 這個前端 Dashboard

啟動方式：
    uvicorn main:app --reload
    然後瀏覽器打開 http://127.0.0.1:8000
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from apscheduler.schedulers.background import BackgroundScheduler

import database
from scraper.news_scraper import fetch_all_news
from scraper.market_data import fetch_all_market_data

# ---------------------------------------------------------------
# 基本設定
# ---------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler(timezone="Asia/Taipei")


def scrape_and_store():
    """
    排程任務主體：抓新聞 + 抓市場數據，並各自寫入資料庫。

    設計重點：
        新聞抓取失敗與市場數據抓取失敗，用兩個獨立的 try/except 包起來，
        確保「新聞抓失敗」不會連帶讓「市場數據」也抓不到，反之亦然。
    """
    logger.info("=== 排程任務開始：抓取新聞與市場數據 ===")

    try:
        news_result = fetch_all_news(max_items_per_source=15)
        database.save_news(news_result["sources"])
    except Exception as e:
        logger.error(f"新聞抓取排程執行失敗：{e}")

    try:
        market_result = fetch_all_market_data()
        database.save_market_data(market_result["data"])
    except Exception as e:
        logger.error(f"市場數據抓取排程執行失敗：{e}")

    logger.info("=== 排程任務結束 ===")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI 的生命週期管理：伺服器啟動時執行一次，關閉時執行一次。
    """
    # --- 啟動時執行 ---
    database.init_db()

    # 設定每天早上 08:00 自動抓取一次
    scheduler.add_job(
        scrape_and_store,
        trigger="cron",
        hour=8,
        minute=0,
        id="daily_scrape",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("排程已啟動：每日 08:00 自動抓取新聞與市場數據")

    # 伺服器剛啟動時，資料庫可能是空的，先手動跑一次，
    # 讓使用者一打開網頁就能馬上看到資料，不用乾等到隔天 08:00
    logger.info("伺服器啟動，先執行一次初始抓取...")
    scrape_and_store()

    yield  # ---- 這裡是 FastAPI 運作期間 ----

    # --- 關閉時執行 ---
    scheduler.shutdown()
    logger.info("排程已停止，伺服器關閉")


app = FastAPI(title="每日金融市場資訊聚合網站", lifespan=lifespan)


# ---------------------------------------------------------------
# API 端點
# ---------------------------------------------------------------

@app.get("/api/news")
def api_get_news():
    """回傳目前資料庫中各來源最新的新聞清單。"""
    return database.get_latest_news()


@app.get("/api/market")
def api_get_market():
    """回傳目前資料庫中所有市場標的的最新數據。"""
    return database.get_latest_market_data()


@app.post("/api/refresh")
def api_manual_refresh():
    """
    手動觸發一次抓取（不用等排程時間到）。
    方便你在瀏覽器打開網頁後，想立即更新資料時使用。
    """
    scrape_and_store()
    return {"status": "ok", "message": "已重新抓取最新資料"}


# ---------------------------------------------------------------
# 掛載前端靜態網頁
# 注意：這一行要放在所有 /api/... 路由「之後」，
#      否則 StaticFiles 會把 /api 這類路徑也攔截掉，導致 API 404
# ---------------------------------------------------------------

app.mount("/", StaticFiles(directory="static", html=True), name="static")
