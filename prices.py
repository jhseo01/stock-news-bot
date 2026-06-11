"""네이버 금융 공개 데이터로 현재가를 조회한다. (무료, API 키 불필요)"""
import requests

HEADERS = {"User-Agent": "Mozilla/5.0"}


def lookup_code(name: str) -> tuple[str | None, str | None]:
    """종목명으로 종목코드를 찾는다. (코드, 공식 종목명) 반환."""
    r = requests.get(
        "https://ac.stock.naver.com/ac",
        params={"q": name, "target": "stock"},
        headers=HEADERS,
        timeout=10,
    )
    r.raise_for_status()
    items = [it for it in r.json().get("items", []) if it.get("nationCode") == "KOR"]
    for it in items:  # 정확히 일치하는 이름 우선
        if it["name"] == name:
            return it["code"], it["name"]
    if items:
        return items[0]["code"], items[0]["name"]
    return None, None


def get_price(code: str) -> dict:
    """현재가, 등락폭, 등락률 등을 반환한다."""
    r = requests.get(
        f"https://m.stock.naver.com/api/stock/{code}/basic",
        headers=HEADERS,
        timeout=10,
    )
    r.raise_for_status()
    d = r.json()
    return {
        "name": d.get("stockName", code),
        "price": d.get("closePrice", "?"),
        "diff": d.get("compareToPreviousClosePrice", ""),
        "rate": d.get("fluctuationsRatio", ""),
        "direction": (d.get("compareToPreviousPrice") or {}).get("name", ""),
        "market": d.get("marketStatus", ""),  # OPEN / CLOSE
        "traded_at": d.get("localTradedAt", ""),  # "2026-06-11T15:30:00+09:00"
    }


def price_arrow(direction: str) -> str:
    if "RISING" in direction or "UPPER" in direction:
        return "🔺"
    if "FALLING" in direction or "LOWER" in direction:
        return "🔻"
    return "➖"
