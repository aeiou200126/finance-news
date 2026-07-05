# -*- coding: utf-8 -*-
import time
import json
import logging
from datetime import datetime
import requests
import feedparser
from bs4 import BeautifulSoup

# 強化版偽裝，讓伺服器以為我們是 Mac 電腦的真實瀏覽器
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Referer": "https://www.google.com/",
    "Sec-Ch-Ua": '"Google Chrome";v="125", "Chromium";v="125", "Not.A/Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
}
REQUEST_TIMEOUT = 10

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def build_sources():
    return {
        "economic_daily": {
            "name": "經濟日報",
            "rss_urls": ["https://money.udn.com/rssfeed/news/1001/5590/5591?ch=money", "http://edn.udn.com/rss.jsp"],
            "fallback_url": "https://money.udn.com/money/cate/10846",
            "parser": "parse_udn_fallback",
        },
        "commercial_times": {
            "name": "工商時報",
            "rss_urls": ["https://www.ctee.com.tw/rss", "https://www.chinatimes.com/rss/realtimenews-money.xml"],
            "fallback_url": "https://www.ctee.com.tw/livenews/aall",
            "parser": "parse_ctee_fallback",
        },
        "bloomberg": {
            "name": "彭博 (Bloomberg)",
            # 換上彭博官方原生 RSS
            "rss_urls": [
                "https://feeds.bloomberg.com/markets/news.rss",
                "https://feeds.bloomberg.com/wealth/news.rss"
            ],
            "fallback_url": "https://www.bloomberg.com/markets",
            "parser": "parse_bloomberg_fallback",
        },
    }

def fetch_via_rss(rss_urls, source_name):
    for url in rss_urls:
        try:
            logger.info(f"[{source_name}] 嘗試抓取 RSS：{url}")
            resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
            if feed.bozo and not feed.entries:
                raise ValueError(f"RSS 解析失敗：{feed.bozo_exception}")
            if not feed.entries:
                raise ValueError("RSS 內容為空")
            news_list = []
            for entry in feed.entries:
                news_list.append({
                    "title": entry.get("title", "（無標題）").strip(),
                    "link": entry.get("link", "").strip(),
                    "published": entry.get("published", entry.get("updated", "")),
                })
            logger.info(f"[{source_name}] RSS 抓取成功，共 {len(news_list)} 則")
            return news_list
        except Exception as e:
            logger.warning(f"[{source_name}] RSS {url} 失敗：{e}")
            continue
    return []

def parse_udn_fallback(html):
    news_list = []
    soup = BeautifulSoup(html, "lxml")
    links = soup.select("a[href*='/money/story/']")
    seen_links = set()
    for a_tag in links:
        title = extract_clean_title(a_tag)
        href = a_tag.get("href", "")
        if not title or len(title) < 6 or not href: continue
        if href.startswith("/"): href = "https://money.udn.com" + href
        if href in seen_links: continue
        seen_links.add(href)
        news_list.append({"title": title, "link": href, "published": ""})
    return news_list

def extract_clean_title(a_tag):
    heading_tag = a_tag.find(["h1", "h2", "h3", "h4", "strong"])
    if heading_tag:
        text = heading_tag.get_text(strip=True)
        if text: return text
    direct_texts = [t.strip() for t in a_tag.find_all(string=True, recursive=False) if t.strip()]
    if direct_texts: return direct_texts[0]
    full_text = a_tag.get_text(strip=True)
    return full_text[:40] + "…" if len(full_text) > 40 else full_text

def parse_ctee_fallback(html):
    news_list = []
    soup = BeautifulSoup(html, "lxml")
    links = soup.select("a[href*='/livenews/'], h3 a, .news-list a")
    seen_links = set()
    for a_tag in links:
        title = extract_clean_title(a_tag)
        href = a_tag.get("href", "")
        if not title or len(title) < 6 or not href: continue
        if href.startswith("/"): href = "https://www.ctee.com.tw" + href
        if href in seen_links: continue
        seen_links.add(href)
        news_list.append({"title": title, "link": href, "published": ""})
    return news_list

def parse_bloomberg_fallback(html):
    news_list = []
    soup = BeautifulSoup(html, "lxml")
    links = soup.select("h3 a")
    seen_links = set()
    for a_tag in links:
        title = extract_clean_title(a_tag)
        href = a_tag.get("href", "")
        if not title or len(title) < 6 or not href: continue
        if href.startswith("/"): href = "https://finance.yahoo.com" + href
        if href in seen_links: continue
        seen_links.add(href)
        news_list.append({"title": title, "link": href, "published": ""})
    return news_list

FALLBACK_PARSERS = {
    "parse_udn_fallback": parse_udn_fallback, 
    "parse_ctee_fallback": parse_ctee_fallback,
    "parse_bloomberg_fallback": parse_bloomberg_fallback
}

def fetch_via_scraping(fallback_url, parser_name, source_name):
    try:
        logger.info(f"[{source_name}] 改用網頁解析備援：{fallback_url}")
        resp = requests.get(fallback_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        parser_func = FALLBACK_PARSERS.get(parser_name)
        news_list = parser_func(resp.text)
        if not news_list: raise ValueError("網頁解析後無資料")
        return news_list
    except Exception as e:
        logger.error(f"[{source_name}] 網頁解析失敗：{e}")
    return []

def fetch_all_news(max_items_per_source=10):
    sources = build_sources()
    result = {"updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "sources": {}}
    for key, cfg in sources.items():
        source_name = cfg["name"]
        news_list = fetch_via_rss(cfg["rss_urls"], source_name)
        if not news_list:
            news_list = fetch_via_scraping(cfg["fallback_url"], cfg["parser"], source_name)
        result["sources"][key] = {
            "name": source_name,
            "news": news_list[:max_items_per_source],
            "count": len(news_list[:max_items_per_source]),
        }
        time.sleep(1)
    return result

def save_to_json(data, filepath="news_data.json"):
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    news_data = fetch_all_news(max_items_per_source=10)
    save_to_json(news_data, "news_data.json")
