"""매일 아침 7시(KST) 종목별 주요 뉴스 브리핑을 텔레그램으로 전송한다."""
import html
from datetime import datetime
from zoneinfo import ZoneInfo

from config import BRIEFING_LIMIT, STOCKS
from news import fetch_news
from notify import send_message

WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]


def build_briefing() -> str:
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    lines = [
        f"📊 <b>주식 뉴스 브리핑</b>",
        f"{now:%Y-%m-%d} ({WEEKDAYS[now.weekday()]}) 오전 7시",
        "",
    ]

    for name, query in STOCKS.items():
        lines.append(f"🏢 <b>{html.escape(name)}</b>")
        try:
            items = fetch_news(query, when="1d", limit=BRIEFING_LIMIT)
        except Exception as e:
            items = []
            lines.append(f"  (뉴스 조회 실패: {html.escape(str(e))})")

        if not items and "조회 실패" not in lines[-1]:
            lines.append("  최근 24시간 내 주요 뉴스 없음")

        for i, item in enumerate(items, 1):
            title = html.escape(item["title"])
            source = html.escape(item["source"])
            suffix = f" — {source}" if source else ""
            lines.append(f"{i}. <a href=\"{item['link']}\">{title}</a>{suffix}")
        lines.append("")

    return "\n".join(lines).strip()


if __name__ == "__main__":
    send_message(build_briefing())
    print("브리핑 전송 완료")
