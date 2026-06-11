"""새 속보 기사를 찾아 텔레그램으로 전송한다.

- 이미 보낸 기사는 state/seen.json에 기록해 중복 전송을 막는다.
- state 파일이 없는 최초 실행 시에는 과거 기사를 전부 쏟아내지 않도록
  현재 기사들을 '본 것'으로만 기록하고 전송하지 않는다.
"""
import hashlib
import html
import json
import time
from pathlib import Path

from news import fetch_news
from notify import send_message
from settings import load_settings

STATE_FILE = Path(__file__).parent / "state" / "seen.json"
STATE_TTL = 7 * 24 * 3600  # 7일 지난 기록은 정리


def article_key(item: dict) -> str:
    # 같은 기사가 다른 URL로 잡히는 경우가 있어 제목 기준으로 중복 판정
    return hashlib.sha1(item["title"].encode("utf-8")).hexdigest()


def is_breaking(title: str, keywords: list[str]) -> bool:
    if not keywords:
        return True
    return any(kw in title for kw in keywords)


def load_seen() -> tuple[dict, bool]:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8")), False
    return {}, True


def save_seen(seen: dict) -> None:
    now = time.time()
    seen = {k: v for k, v in seen.items() if now - v < STATE_TTL}
    STATE_FILE.parent.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(seen, indent=1), encoding="utf-8")


def main() -> None:
    s = load_settings()
    seen, first_run = load_seen()
    now = time.time()
    sent = 0

    for name, query in s["stocks"].items():
        try:
            items = fetch_news(query, when=f"{s['breaking_window_hours']}h", limit=20)
        except Exception as e:
            print(f"{name}: 뉴스 조회 실패 - {e}")
            continue

        for item in items:
            key = article_key(item)
            if key in seen:
                continue
            seen[key] = now

            if first_run or not is_breaking(item["title"], s["breaking_keywords"]):
                continue

            title = html.escape(item["title"])
            source = html.escape(item["source"])
            suffix = f" — {source}" if source else ""
            send_message(
                f"🚨 <b>{html.escape(name)}</b> 속보\n"
                f"<a href=\"{item['link']}\">{title}</a>{suffix}"
            )
            sent += 1

    save_seen(seen)
    if first_run:
        print("최초 실행: 기존 기사를 기록만 하고 전송하지 않았습니다.")
    print(f"속보 {sent}건 전송 완료")


if __name__ == "__main__":
    main()
