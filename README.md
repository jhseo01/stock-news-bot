# 주식 뉴스 텔레그램 알림 봇

관심 종목(삼성전자, 현대차, 네이버, LG전자, SK하이닉스)의 뉴스를 텔레그램으로 받아보는 시스템입니다.

- **매일 오전 7시(KST)**: 종목별 최근 24시간 주요 뉴스 5건씩 브리핑
- **10분마다**: "속보·단독·특징주·공시·급등·급락" 키워드가 들어간 새 기사 즉시 알림

GitHub Actions에서 실행되므로 **서버 비용이 없고**, 뉴스는 구글 뉴스 RSS를 사용해 **API 키도 필요 없습니다**.
필요한 것은 텔레그램 봇 토큰뿐입니다.

## 설정 방법 (총 15분 정도)

### 1단계. 텔레그램 봇 만들기

1. 텔레그램에서 **@BotFather** 검색 → 대화 시작
2. `/newbot` 입력 → 봇 이름과 아이디(`~bot`으로 끝나야 함) 입력
3. 발급된 **봇 토큰** 복사 (예: `1234567890:AAH4f3...`)
4. 방금 만든 봇을 검색해서 **아무 메시지나 한 번 전송** (이걸 해야 봇이 나에게 메시지를 보낼 수 있음)
5. 브라우저에서 아래 주소 접속 (토큰 부분 교체):
   ```
   https://api.telegram.org/bot<봇토큰>/getUpdates
   ```
6. 응답 JSON에서 `"chat":{"id":123456789` 부분의 숫자가 **chat_id**

### 2단계. GitHub 저장소 만들고 코드 올리기

1. https://github.com/new 에서 새 저장소 생성
   - 이름: 예) `stock-news-bot`
   - **Public** 선택 (Public이면 Actions 실행 시간이 무제한 무료. 코드에 토큰이 없으므로 공개해도 안전)
2. 이 폴더에서 아래 명령 실행:
   ```
   git init
   git add .
   git commit -m "주식 뉴스 텔레그램 봇"
   git branch -M main
   git remote add origin https://github.com/<내아이디>/stock-news-bot.git
   git push -u origin main
   ```

### 3단계. 토큰을 GitHub Secrets에 등록

저장소 페이지에서 **Settings → Secrets and variables → Actions → New repository secret**:

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | 1단계에서 받은 봇 토큰 |
| `TELEGRAM_CHAT_ID` | 1단계에서 확인한 chat_id |

### 4단계. 테스트

저장소의 **Actions 탭** → `daily-briefing` 선택 → **Run workflow** 버튼 클릭.
잠시 후 텔레그램으로 브리핑이 오면 성공입니다. 이후로는 자동으로 동작합니다.

## 설정 변경

[config.py](config.py)에서 수정 후 git push 하면 바로 반영됩니다:

- `STOCKS` — 종목 추가/삭제/검색어 조정
- `BREAKING_KEYWORDS` — 속보 판정 키워드 (비우면 모든 새 기사 전송)
- `BRIEFING_LIMIT` — 브리핑 시 종목당 뉴스 개수

브리핑 시간을 바꾸려면 [.github/workflows/daily-briefing.yml](.github/workflows/daily-briefing.yml)의 cron을 수정하세요.
cron은 UTC 기준이므로 **한국시간 - 9시간**입니다. (예: 오전 8시 = `0 23 * * *`)

## 로컬 테스트

```
pip install -r requirements.txt
python briefing.py    # 토큰 없이 실행하면 전송 대신 콘솔에 출력됨
python breaking.py
```

## 알아둘 점

- GitHub Actions의 스케줄 실행은 혼잡 시 **몇 분~십수 분 지연**될 수 있습니다. 속보가 "초단위 실시간"은 아니고 보통 10~20분 내 도착한다고 보면 됩니다.
- 저장소에 60일간 활동이 없으면 GitHub가 스케줄 실행을 자동 중지시킬 수 있는데, 이 봇은 속보 상태 파일(`state/seen.json`)을 주기적으로 커밋하므로 해당되지 않습니다.
- 더 빠른 실시간 알림이 필요해지면 Oracle Cloud Free Tier(무료 VM, 카드 등록 필요)로 옮겨 폴링 주기를 1분으로 줄일 수 있습니다.
