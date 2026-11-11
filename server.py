"""موقع أخبار النفط: يجلب الأسعار والأخبار تلقائيًا ويعرضها في صفحة تتحدث وحدها.

التشغيل:  python server.py   ثم افتح  http://localhost:8000
لا يحتاج أي مكتبة خارجية، فقط Python 3.8 أو أحدث.
"""
import json
import os
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).parent
HOST = os.environ.get("HOST", "0.0.0.0" if "PORT" in os.environ else "127.0.0.1")
PORT = int(os.environ.get("PORT", "8000"))

PRICE_EVERY = 30   # ثانية بين كل تحديث للأسعار
NEWS_EVERY = 300   # ثانية بين كل تحديث للأخبار

# CL=F عقد WTI الآجل الأقرب (قريب من سعر MCL)، و BZ=F عقد برنت الآجل الأقرب
SYMBOLS = {"WTI": "CL=F", "BRENT": "BZ=F"}

QUERY = urllib.parse.quote("النفط OR برنت OR أوبك OR خام")
NEWS_FEEDS = [
    ("أخبار Google", f"https://news.google.com/rss/search?q={QUERY}&hl=ar&gl=SA&ceid=SA:ar"),
    ("OilPrice.com", "https://oilprice.com/rss/main"),
]

STATE = {"prices": {}, "news": [], "errors": {}}
LOCK = threading.Lock()


def fetch(url, timeout=10):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (oil-news-dashboard)"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def get_price(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=1m&range=1d"
    meta = json.loads(fetch(url))["chart"]["result"][0]["meta"]
    price = meta["regularMarketPrice"]
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    return {"price": price, "prev": prev, "time": meta.get("regularMarketTime")}


def get_news(default_source, url):
    root = ET.fromstring(fetch(url))
    items = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        source = (item.findtext("source") or default_source).strip()
        try:
            ts = parsedate_to_datetime(item.findtext("pubDate")).timestamp()
        except Exception:
            ts = 0
        if title and link:
            items.append({"title": title, "link": link, "source": source, "ts": ts})
    return items


def price_loop():
    while True:
        for name, symbol in SYMBOLS.items():
            try:
                data = get_price(symbol)
                with LOCK:
                    STATE["prices"][name] = data
                    STATE["errors"].pop(name, None)
            except Exception as exc:
                with LOCK:
                    STATE["errors"][name] = str(exc)
        time.sleep(PRICE_EVERY)


def news_loop():
    while True:
        collected = []
        for name, url in NEWS_FEEDS:
            try:
                collected += get_news(name, url)
                with LOCK:
                    STATE["errors"].pop(name, None)
            except Exception as exc:
                with LOCK:
                    STATE["errors"][name] = str(exc)
        if collected:
            seen, unique = set(), []
            for item in sorted(collected, key=lambda i: i["ts"], reverse=True):
                if item["link"] not in seen:
                    seen.add(item["link"])
                    unique.append(item)
            with LOCK:
                STATE["news"] = unique[:40]
        time.sleep(NEWS_EVERY)


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/":
            self._send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8")
        elif path == "/api/data":
            with LOCK:
                body = json.dumps(STATE, ensure_ascii=False).encode("utf-8")
            self._send(200, body, "application/json; charset=utf-8")
        else:
            self._send(404, b"Not found", "text/plain; charset=utf-8")

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    threading.Thread(target=price_loop, daemon=True).start()
    threading.Thread(target=news_loop, daemon=True).start()
    print(f"الموقع يعمل على http://{HOST}:{PORT}  (للإيقاف: Ctrl+C)")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
