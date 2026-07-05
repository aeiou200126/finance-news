# -*- coding: utf-8 -*-
"""
database.py
================
每日金融市場資訊聚合網站 —— 資料庫存取模組

使用 SQLite（Python 內建 sqlite3，不需要另外安裝資料庫軟體）。
負責兩件事：
    1. 把 scraper 抓到的新聞 / 市場數據「寫入」資料庫
    2. 提供 API 查詢「最新資料」給前端使用

為什麼要存資料庫而不是直接存 JSON 檔案？
    - 新聞用 INSERT OR IGNORE + link 設為 UNIQUE，可以避免重複新聞被重複寫入
    - 市場數據用「有就更新、沒有就新增」(UPSERT)，永遠只保留每個標的的最新一筆
    - 之後要做「歷史查詢」「統計圖表」也會比較方便擴充
"""

import sqlite3
import logging
from contextlib import contextmanager
from datetime import datetime

logger = logging.getLogger(__name__)

DB_PATH = "finance_dashboard.db"


@contextmanager
def get_connection():
    """
    提供一個資料庫連線的「情境管理器」（with 語法會用到）。
    好處：不管中間有沒有發生錯誤，離開 with 區塊時都會自動 commit 並關閉連線，
          不用每個函式自己重複寫開關資料庫的邏輯。
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # 讓查詢結果可以用欄位名稱存取，例如 row["title"]
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    """建立資料表（如果已存在就跳過，不會清空既有資料）。"""
    with get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_key TEXT NOT NULL,
                source_name TEXT NOT NULL,
                title TEXT NOT NULL,
                link TEXT NOT NULL UNIQUE,
                published TEXT,
                fetched_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS market_data (
                key TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                category TEXT NOT NULL,
                price REAL,
                change REAL,
                change_percent REAL,
                status TEXT NOT NULL,
                error_message TEXT,
                updated_at TEXT NOT NULL
            )
        """)
    logger.info("資料庫初始化完成（news / market_data 資料表已就緒）")


def save_news(sources_dict):
    """
    寫入新聞資料。

    參數：
        sources_dict: 格式來自 news_scraper.fetch_all_news()["sources"]，例如：
            {
                "economic_daily": {"name": "經濟日報", "news": [...]},
                "commercial_times": {"name": "工商時報", "news": [...]},
            }

    重複新聞處理：
        link 欄位設為 UNIQUE，用 INSERT OR IGNORE，
        同一則新聞（同樣連結）重複抓到也不會產生重複資料。
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    inserted_count = 0

    with get_connection() as conn:
        for source_key, source_info in sources_dict.items():
            for item in source_info.get("news", []):
                try:
                    cursor = conn.execute(
                        """
                        INSERT OR IGNORE INTO news
                            (source_key, source_name, title, link, published, fetched_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            source_key,
                            source_info.get("name", source_key),
                            item.get("title", ""),
                            item.get("link", ""),
                            item.get("published", ""),
                            now,
                        ),
                    )
                    if cursor.rowcount > 0:
                        inserted_count += 1
                except Exception as e:
                    # 單筆寫入失敗（例如資料格式異常）不影響其他筆
                    logger.warning(f"寫入單筆新聞失敗，已跳過：{e}")
                    continue

    logger.info(f"新聞寫入完成，新增 {inserted_count} 則（重複的已自動略過）")


def save_market_data(data_list):
    """
    寫入 / 更新市場數據。

    每個標的用 key 當主鍵，永遠只保留「最新一筆」：
        - 資料庫沒有這個 key -> 新增
        - 資料庫已經有這個 key -> 更新覆蓋
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with get_connection() as conn:
        for item in data_list:
            try:
                conn.execute(
                    """
                    INSERT INTO market_data
                        (key, display_name, category, price, change,
                         change_percent, status, error_message, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        display_name = excluded.display_name,
                        category = excluded.category,
                        price = excluded.price,
                        change = excluded.change,
                        change_percent = excluded.change_percent,
                        status = excluded.status,
                        error_message = excluded.error_message,
                        updated_at = excluded.updated_at
                    """,
                    (
                        item["key"],
                        item["display_name"],
                        item["category"],
                        item.get("price"),
                        item.get("change"),
                        item.get("change_percent"),
                        item.get("status", "error"),
                        item.get("error_message"),
                        now,
                    ),
                )
            except Exception as e:
                logger.warning(f"寫入市場數據失敗（{item.get('key')}）：{e}")
                continue

    logger.info(f"市場數據更新完成，共 {len(data_list)} 個標的")


def get_latest_news(limit_per_source=15):
    """
    查詢每個來源最新的新聞（依 id 由新到舊排序）。

    回傳格式：
        {
            "economic_daily": {"name": "經濟日報", "news": [...]},
            "commercial_times": {"name": "工商時報", "news": [...]},
        }
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM news ORDER BY id DESC"
        ).fetchall()

    grouped = {}
    for row in rows:
        key = row["source_key"]
        if key not in grouped:
            grouped[key] = {"name": row["source_name"], "news": []}

        if len(grouped[key]["news"]) < limit_per_source:
            grouped[key]["news"].append({
                "title": row["title"],
                "link": row["link"],
                "published": row["published"],
            })

    return grouped


def get_latest_market_data():
    """查詢所有標的的最新市場數據，回傳 list[dict]。"""
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM market_data").fetchall()

    return [dict(row) for row in rows]
