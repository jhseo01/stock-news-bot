"""설정된 시간(기본 매일 7시 KST)에 종목별 주요 뉴스 브리핑을 전송한다."""
import html
from datetime import datetime
from zoneinfo import ZoneInfo

from news import fetch_news
from notify import send_message
from settings import load_bot_state, load_settings, save_bot_state

WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]
KST = ZoneInfo("Asia/Seoul")


def build_briefing(s: dict) -> str:
    now = datetime.now(KST)
    lines = [
        "📊 <b>주식 뉴스 브리핑</b>",
        f"{now:%Y-%m-%d} ({WEEKDAYS[now.weekday()]})",
        "",
    ]

    for name, query in s["stocks"].items():
        lines.append(f"🏢 <b>{html.escape(name)}</b>")
        try:
            items = fetch_news(query, when="1d", limit=s["briefing_limit"])
        except Exception as e:
            lines.append(f"  (뉴스 조회 실패: {html.escape(str(e))})")
            lines.append("")
            continue

        if not items:
            lines.append("  최근 24시간 내 주요 뉴스 없음")

        for i, item in enumerate(items, 1):
            title = html.escape(item["title"])
            source = html.escape(item["source"])
            suffix = f" — {source}" if source else ""
            lines.append(f"{i}. <a href=\"{item['link']}\">{title}</a>{suffix}")
        lines.append("")

    return "\n".join(lines).strip()


def send_if_due(force: bool = False) -> bool:
    """브리핑 시간이 지났고 오늘 아직 안 보냈으면 전송한다."""
    s = load_settings()
    state = load_bot_state()
    now = datetime.now(KST)
    today = f"{now:%Y-%m-%d}"

    if not force:
        if now.hour < s["briefing_hour"] or state.get("last_briefing_date") == today:
            return False

    send_message(build_briefing(s))
    state["last_briefing_date"] = today
    save_bot_state(state)
    return True


if __name__ == "__main__":
    send_if_due(force=True)
    print("브리핑 전송 완료")
