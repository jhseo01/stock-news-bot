"""구글 뉴스 RSS에서 종목 뉴스를 가져온다. API 키 불필요."""
from urllib.parse import quote

import feedparser

RSS_URL = "https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"


def fetch_news(query: str, when: str = "1d", limit: int = 10) -> list[dict]:
    """검색어에 해당하는 최신 뉴스 목록을 반환한다.

    when: 검색 기간 (예: "1d" = 최근 1일, "2h" = 최근 2시간)
    """
    url = RSS_URL.format(query=quote(f"{query} when:{when}"))
    feed = feedparser.parse(url)

    items = []
    for entry in feed.entries[:limit]:
        raw_title = (entry.get("title") or "").strip()
        # 구글 뉴스 제목은 "기사제목 - 언론사" 형식
        if " - " in raw_title:
            title, source = raw_title.rsplit(" - ", 1)
        else:
            title, source = raw_title, ""

        items.append({
            "id": entry.get("id") or entry.get("link"),
            "title": title.strip(),
            "source": source.strip(),
            "link": entry.get("link", ""),
            "published": entry.get("published", ""),
        })
    return items
