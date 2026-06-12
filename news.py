"""구글 뉴스 RSS에서 종목 뉴스를 가져온다. API 키 불필요."""
from urllib.parse import quote

import feedparser

RSS_URL = "https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"


def query_terms(query: str) -> list[str]:
    """검색어를 OR 단위로 쪼갠다. 예: "네이버 OR NAVER" -> ["네이버", "NAVER"]"""
    return [t.strip() for t in query.split(" OR ") if t.strip()]


def fetch_news(query: str, when: str = "1d", limit: int = 10) -> list[dict]:
    """검색어에 해당하는 최신 뉴스 목록을 반환한다.

    when: 검색 기간 (예: "1d" = 최근 1일, "2h" = 최근 2시간)

    구글 뉴스 검색은 본문까지 매칭해서 무관한 종목 기사가 섞이므로,
    기사 '제목'에 검색어 중 하나가 실제로 포함된 기사만 통과시킨다.
    """
    url = RSS_URL.format(query=quote(f"{query} when:{when}"))
    feed = feedparser.parse(url)
    terms = [t.lower() for t in query_terms(query)]

    items = []
    for entry in feed.entries:
        raw_title = (entry.get("title") or "").strip()
        # 구글 뉴스 제목은 "기사제목 - 언론사" 형식
        if " - " in raw_title:
            title, source = raw_title.rsplit(" - ", 1)
        else:
            title, source = raw_title, ""
        title = title.strip()

        if terms and not any(t in title.lower() for t in terms):
            continue  # 제목에 종목명이 없으면 다른 종목 기사일 가능성이 높음

        items.append({
            "id": entry.get("id") or entry.get("link"),
            "title": title,
            "source": source.strip(),
            "link": entry.get("link", ""),
            "published": entry.get("published", ""),
        })
        if len(items) >= limit:
            break
    return items
