# -*- coding: utf-8 -*-
import os
import json
import logging
import http.server
import socketserver
from concurrent.futures import ThreadPoolExecutor
from google import genai

from news_scraper import fetch_all_news, save_to_json as save_news
from market_data import fetch_all_market_data, save_to_json as save_market

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

PORT = 8000

def generate_ai_summary():
    """讀取抓好的新聞，並呼叫 Gemini 產生專屬早報"""
    # 自動清除金鑰前後可能不小心複製到的空白或換行
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    
    if not api_key:
        logger.warning("⚠️ 未設定 GEMINI_API_KEY，跳過 AI 摘要生成。")
        return

    try:
        with open("news_data.json", "r", encoding="utf-8") as f:
            news_data = json.load(f)

        news_titles = []
        for source, data in news_data.get("sources", {}).items():
            for item in data.get("news", []):
                news_titles.append(f"- {item['title']}")
        news_text = "\n".join(news_titles)

        # 使用正統的 Google 官方工具包
        client = genai.Client(api_key=api_key)
        prompt = f"""
        你是一位資深的金融市場分析師。請根據以下今日最新的財經新聞標題，整理一份「3分鐘市場早報」。
        請特別針對「國泰銀行儲備理專」的日常實務視角來撰寫，並聚焦於：如何透過這些資訊協助客戶尋找「擴大現金流部位、穩健收息」的投資機會與避險方向。

        請輸出一段 300 字以內的精華摘要，請直接使用 HTML 格式輸出（可包含 <h3>, <ul>, <li>, <strong> 等標籤，但不要包含 <html>, <body>，也不要輸出 Markdown 的 ```html 標記）。

        今日新聞標題：
        {news_text}
        """
        
        # 🛑 真正的關鍵修正：使用目前世界上真實存在的 gemini-1.5-flash 模型！
        response = client.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt,
        )

        summary_html = response.text.replace("```html", "").replace("```", "").strip()

        with open("ai_summary.json", "w", encoding="utf-8") as f:
            json.dump({"summary_html": summary_html, "status": "ok"}, f, ensure_ascii=False, indent=2)
        logger.info("✅ [AI 摘要] 生成並儲存成功 (ai_summary.json)")

    except Exception as e:
        logger.error(f"❌ [AI 摘要] 生成失敗: {e}")

def update_data_job():
    logger.info("========================================")
    logger.info("🔄 開始執行資料抓取與 AI 分析任務...")
    
    with ThreadPoolExecutor(max_workers=2) as executor:
        future_news = executor.submit(fetch_all_news, max_items_per_source=10)
        future_market = executor.submit(fetch_all_market_data)

        try:
            save_news(future_news.result(), "news_data.json")
            logger.info("✅ [新聞數據] 抓取完成")
        except Exception as e:
            logger.error(f"❌ [新聞數據] 失敗: {e}")

        try:
            save_market(future_market.result(), "market_data.json")
            logger.info("✅ [市場行情] 抓取完成")
        except Exception as e:
            logger.error(f"❌ [市場行情] 失敗: {e}")

    generate_ai_summary()
    logger.info("✨ 資料更新與 AI 任務執行完畢！")
    logger.info("========================================")

def start_web_server():
    socketserver.TCPServer.allow_reuse_address = True
    Handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        logger.info(f"🌐 本地網頁伺服器已啟動！")
        logger.info(f"🔗 請打開瀏覽器造訪: http://localhost:{PORT}/index.html")
        logger.info("💡 提示：按 Ctrl + C 可以關閉伺服器。")
        httpd.serve_forever()

if __name__ == "__main__":
    update_data_job()
    if os.environ.get("GITHUB_ACTIONS") == "true":
        logger.info("☁️ 偵測到 GitHub Actions 雲端環境，資料更新完畢，自動登出。")
    else:
        logger.info("💻 偵測到本機環境，準備啟動網頁伺服器供您預覽...")
        try:
            start_web_server()
        except KeyboardInterrupt:
            logger.info("\n🛑 偵測到關閉指令，安全關閉。")
