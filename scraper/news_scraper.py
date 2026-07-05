# -*- coding: utf-8 -*-
"""
news_scraper.py
================
每日金融市場資訊聚合網站 —— 新聞抓取模組（Scraper）

功能說明：
    抓取「經濟日報」與「工商時報」的當日焦點新聞（標題 + 連結）。

設計原則（重要）：
    1. 優先使用 RSS Feed（穩定、格式固定、不容易因網站改版而壞掉）。
    2. 如果 RSS 抓不到資料（例如網站關閉了該 RSS、URL 失效），
       會自動「降級」改用 BeautifulSoup 解析新聞列表頁面當作備援方案。
    3. 任何一個來源出錯，都不會讓整支程式當掉，只會記錄錯誤訊息，
       並繼續處理下一個來源（Graceful Degradation，優雅降級）。

⚠️ 注意：
    - 台灣新聞網站偶爾會調整 RSS 網址或改版頁面結構（CSS 選擇器）。
      若某天發現抓不到資料，請優先檢查下方 SOURCES 設定中的
      rss_urls（RSS 網址）與 fallback 解析函式裡的 CSS 選擇器是否仍然正確。
    - 請勿抓取過於頻繁（建議至少間隔數分鐘~數小時一次），
      並在 headers 中偽裝正常瀏覽器 User-Agent，尊重對方網站資源。
"""

import time
import json
import logging
from datetime import datetime

import requests
import feedparser
from bs4 import BeautifulSoup

# -------------------------------------------------------------------
# 基本設定
# -------------------------------------------------------------------

# 偽裝成一般瀏覽器，降低被網站阻擋的機率
# 只有 User-Agent 有時不夠（工商時報等網站會檢查更多欄位並回傳 403），
# 這裡補齊瀏覽器實際會送出的常見 headers，讓請求看起來更像真人操作
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Connection": "keep-alive",
    "Referer": "https://www.google.com/",
    "Upgrade-Insecure-Requests": "1",
}

# 網路請求逾時秒數，避免程式因對方伺服器沒回應而卡住
REQUEST_TIMEOUT = 10

# 設定日誌（Log），方便之後除錯，知道是哪個來源、哪個步驟出錯
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# -------------------------------------------------------------------
# 各新聞來源設定
# 每個來源包含：
#   name        : 顯示名稱
#   rss_urls    : 候選 RSS 網址清單（會依序嘗試，成功一個就停止）
#   fallback_url: RSS 都失敗時，改抓這個新聞列表頁面
#   parser      : 對應的 HTML 備援解析函式（見下方定義）
# -------------------------------------------------------------------

def build_sources():
    return {
        "economic_daily": {
            "name": "經濟日報",
            "rss_urls": [
                # 經濟日報官方 RSS（若失效，程式會自動改用網頁解析備援）
                "https://money.udn.com/rssfeed/news/1001/5590/5591?ch=money",
                "http://edn.udn.com/rss.jsp",
            ],
            "fallback_url": "https://money.udn.com/money/cate/10846",  # 要聞版
            "parser": "parse_udn_fallback",
        },
        "commercial_times": {
            "name": "工商時報",
            "rss_urls": [
                # 工商時報 / 中時新聞網財經頻道 RSS 候選網址
                "https://www.ctee.com.tw/rss",
                "https://www.chinatimes.com/rss/realtimenews-money.xml",
            ],
            "fallback_url": "https://www.ctee.com.tw/livenews/aall",  # 即時新聞列表
            "parser": "parse_ctee_fallback",
        },
    }


# -------------------------------------------------------------------
# 第一層：RSS 抓取（優先策略）
# -------------------------------------------------------------------

def fetch_via_rss(rss_urls, source_name):
    """
    嘗試依序解析候選 RSS 網址，只要有一個成功解析出新聞項目就回傳結果。

    參數：
        rss_urls   (list[str]): 候選 RSS 網址清單
        source_name (str)     : 來源名稱（用於記錄 log）

    回傳：
        list[dict]：解析成功回傳新聞清單；全部失敗則回傳空清單 []
        每筆新聞格式：{"title": 標題, "link": 連結, "published": 發布時間}
    """
    for url in rss_urls:
        try:
            logger.info(f"[{source_name}] 嘗試抓取 RSS：{url}")
            feed = feedparser.parse(url)

            # feedparser 遇到網路錯誤或格式錯誤時，會把錯誤放在 feed.bozo
            # bozo = 1 代表這份 feed 格式有問題或抓取失敗
            if feed.bozo and not feed.entries:
                raise ValueError(f"RSS 解析失敗或格式異常：{feed.bozo_exception}")

            if not feed.entries:
                raise ValueError("RSS 回傳內容為空，可能該網址已失效")

            news_list = []
            for entry in feed.entries:
                news_list.append({
                    "title": entry.get("title", "（無標題）").strip(),
                    "link": entry.get("link", "").strip(),
                    "published": entry.get("published", entry.get("updated", "")),
                })

            logger.info(f"[{source_name}] RSS 抓取成功，共 {len(news_list)} 則新聞")
            return news_list

        except Exception as e:
            # 這裡只記錄錯誤，不中斷程式，繼續嘗試下一個候選網址
            logger.warning(f"[{source_name}] RSS 網址 {url} 抓取失敗：{e}")
            continue

    # 所有候選 RSS 網址都失敗
    logger.warning(f"[{source_name}] 所有 RSS 網址皆失敗，將改用網頁解析備援方案")
    return []


# -------------------------------------------------------------------
# 第二層：網頁解析備援（Fallback，當 RSS 完全失效時才會用到）
# -------------------------------------------------------------------

def parse_udn_fallback(html):
    """
    備援方案：解析經濟日報（money.udn.com）新聞列表頁面。

    ⚠️ 若日後抓不到資料，請打開瀏覽器檢查該頁面的 HTML 結構，
       確認新聞標題連結的 CSS class 是否已改變，並更新下方選擇器。
    """
    news_list = []
    soup = BeautifulSoup(html, "lxml")

    # 經濟日報新聞列表通常是 <a> 標籤包住標題文字，且帶有 story 連結
    links = soup.select("a[href*='/money/story/']")

    seen_links = set()  # 用來避免同一則新聞因版面重複出現而重複收錄
    for a_tag in links:
        title = extract_clean_title(a_tag)
        href = a_tag.get("href", "")

        # 過濾掉標題太短（可能是圖片連結、非新聞元素）或空連結的雜訊
        if not title or len(title) < 6 or not href:
            continue

        # 補齊完整網址
        if href.startswith("/"):
            href = "https://money.udn.com" + href

        if href in seen_links:
            continue
        seen_links.add(href)

        news_list.append({"title": title, "link": href, "published": ""})

    return news_list


def extract_clean_title(a_tag):
    """
    從 <a> 標籤中，只取出「標題」文字，過濾掉可能一起被包住的摘要內文。

    背景問題：
        有些新聞列表的 <a> 標籤，裡面同時包住標題與摘要兩段文字，
        如果直接用 a_tag.get_text() 撈全部文字，會把摘要也黏在標題後面，
        變成一長串不像標題的文字。

    解法（依序嘗試，越前面優先權越高）：
        1. 如果 <a> 內有明確的標題子標籤（h1~h6/strong），優先取該子標籤的文字
        2. 如果沒有子標籤，取 <a> 內「第一個直接文字節點」
           （也就是不含子標籤包裹、緊貼在 <a> 開頭的文字），
           這通常就是標題本身，摘要多半會被包在後面的 <p> 或 <span> 裡
        3. 上述都取不到才退回抓全部文字，並依標題常見長度做截斷保護，
           避免把整段摘要誤當成標題
    """
    # 策略 1：優先找標題常用的子標籤
    heading_tag = a_tag.find(["h1", "h2", "h3", "h4", "strong"])
    if heading_tag:
        text = heading_tag.get_text(strip=True)
        if text:
            return text

    # 策略 2：取 <a> 標籤「直接」擁有、未被子標籤包住的文字節點
    # recursive=False 代表只看第一層，不會往下挖進子標籤裡面抓摘要文字
    direct_texts = [
        t.strip() for t in a_tag.find_all(string=True, recursive=False) if t.strip()
    ]
    if direct_texts:
        return direct_texts[0]

    # 策略 3：保底方案，抓全部文字，但做長度截斷保護
    # 一般中文新聞標題很少超過 40 個字，超過就很可能混入了摘要，直接截斷
    full_text = a_tag.get_text(strip=True)
    MAX_TITLE_LENGTH = 40
    if len(full_text) > MAX_TITLE_LENGTH:
        full_text = full_text[:MAX_TITLE_LENGTH] + "…"
    return full_text


def parse_ctee_fallback(html):
    """
    備援方案：解析工商時報（ctee.com.tw）即時新聞列表頁面。

    ⚠️ 同上，若抓不到資料請檢查實際頁面結構並更新選擇器。
    """
    news_list = []
    soup = BeautifulSoup(html, "lxml")

    links = soup.select("a[href*='/livenews/'], h3 a, .news-list a")

    seen_links = set()
    for a_tag in links:
        title = extract_clean_title(a_tag)
        href = a_tag.get("href", "")

        if not title or len(title) < 6 or not href:
            continue

        if href.startswith("/"):
            href = "https://www.ctee.com.tw" + href

        if href in seen_links:
            continue
        seen_links.add(href)

        news_list.append({"title": title, "link": href, "published": ""})

    return news_list


# 對應表：字串名稱 -> 實際解析函式（方便用設定檔驅動邏輯）
FALLBACK_PARSERS = {
    "parse_udn_fallback": parse_udn_fallback,
    "parse_ctee_fallback": parse_ctee_fallback,
}


def fetch_via_scraping(fallback_url, parser_name, source_name):
    """
    當 RSS 完全失效時，改抓網頁 HTML 並用對應的解析函式處理。

    參數：
        fallback_url (str): 要抓取的新聞列表頁面網址
        parser_name  (str): 對應解析函式的名稱（查 FALLBACK_PARSERS）
        source_name  (str): 來源名稱（用於記錄 log）

    回傳：
        list[dict]：解析成功回傳新聞清單；失敗回傳空清單 []
    """
    try:
        logger.info(f"[{source_name}] 改用網頁解析備援：{fallback_url}")
        resp = requests.get(fallback_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()  # 若狀態碼非 200，主動拋出例外

        parser_func = FALLBACK_PARSERS.get(parser_name)
        if parser_func is None:
            raise ValueError(f"找不到對應的解析函式：{parser_name}")

        news_list = parser_func(resp.text)

        if not news_list:
            raise ValueError("網頁解析後沒有取得任何新聞，可能選擇器已失效")

        logger.info(f"[{source_name}] 網頁解析成功，共 {len(news_list)} 則新聞")
        return news_list

    except requests.exceptions.Timeout:
        logger.error(f"[{source_name}] 網頁請求逾時（超過 {REQUEST_TIMEOUT} 秒）")
    except requests.exceptions.RequestException as e:
        logger.error(f"[{source_name}] 網頁請求失敗：{e}")
    except Exception as e:
        logger.error(f"[{source_name}] 網頁解析發生未預期錯誤：{e}")

    # 走到這裡代表全部失敗，回傳空清單，讓主流程可以繼續跑其他來源
    return []


# -------------------------------------------------------------------
# 主流程：整合 RSS + 備援，並輸出成 JSON
# -------------------------------------------------------------------

def fetch_all_news(max_items_per_source=10):
    """
    依序處理每一個新聞來源：
        1. 先試 RSS
        2. RSS 失敗才用網頁解析備援
        3. 兩者皆失敗，該來源回傳空清單（但不影響其他來源）

    回傳：
        dict，格式如下：
        {
            "updated_at": "2026-07-05 10:00:00",
            "sources": {
                "economic_daily": {"name": "經濟日報", "news": [...]},
                "commercial_times": {"name": "工商時報", "news": [...]}
            }
        }
    """
    sources = build_sources()
    result = {
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "sources": {},
    }

    for key, cfg in sources.items():
        source_name = cfg["name"]
        news_list = []

        try:
            # 第一層：RSS
            news_list = fetch_via_rss(cfg["rss_urls"], source_name)

            # 第二層：RSS 沒抓到才走備援
            if not news_list:
                news_list = fetch_via_scraping(
                    cfg["fallback_url"], cfg["parser"], source_name
                )

        except Exception as e:
            # 最外層再包一層防護網：無論如何都不能讓單一來源的錯誤中斷整支程式
            logger.error(f"[{source_name}] 發生未預期的嚴重錯誤：{e}")
            news_list = []

        # 只取前 N 則，避免資料量過大
        result["sources"][key] = {
            "name": source_name,
            "news": news_list[:max_items_per_source],
            "count": len(news_list[:max_items_per_source]),
        }

        # 禮貌性延遲，避免對同一批網站短時間內發送過多請求
        time.sleep(1)

    return result


def save_to_json(data, filepath="news_data.json"):
    """將抓取結果存成 JSON 檔案，方便後端 API 或前端直接讀取。"""
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"新聞資料已成功寫入：{filepath}")
    except Exception as e:
        logger.error(f"寫入 JSON 檔案失敗：{e}")


# -------------------------------------------------------------------
# 程式進入點
# -------------------------------------------------------------------

if __name__ == "__main__":
    logger.info("=== 開始執行新聞抓取任務 ===")
    news_data = fetch_all_news(max_items_per_source=10)
    save_to_json(news_data, "news_data.json")

    # 簡單印出結果摘要，方便直接執行時檢查成果
    for key, source_data in news_data["sources"].items():
        print(f"\n【{source_data['name']}】共 {source_data['count']} 則新聞")
        for item in source_data["news"][:3]:
            print(f"  - {item['title']}")
            print(f"    {item['link']}")
    logger.info("=== 新聞抓取任務結束 ===")
