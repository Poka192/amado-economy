# 아마도 경제 웹

디스코드 봇의 경제 시스템을 FastAPI + SQLite/Postgres로 웹에서 그대로 구현한 프로젝트입니다.

## 기능

| 시스템 | 내용 |
|---|---|
| 🔑 계정 | 자체 회원가입/로그인 (PBKDF2 해시 + 서명 쿠키) |
| 💵 돈 | 소지금 / 전재산 / 구걸 / 알바 / 송금 |
| 🏦 은행 | 예치(이자 0.02%/분) / 출금 / 대출(0.05%/분) / 상환 |
| 💼 직업 | 직업선택 / 출근(5분 쿨다운) / 레벨업 월급 |
| 📋 퀘스트 | 일일 퀘스트 7종, 보상 수령 |
| 🛒 상점 | 소망력 구매/판매 (최대 420개), 하이롤러 (100만×2^레벨) |
| 🎰 카지노 | 룰렛(2~25배+소망력) / 홀짝 / 하이로우 / 주사위 / 슬롯 |
| 🎫 로또 | 티켓 10만원, 5분 추첨, 당첨금 1억+10% 복리 |
| 📈 주식 | 12종목 24/7 가격변동, 매매/지정가/배당/뉴스/차트 |
| 🏢 부동산 | 8종, 임대수익/리모델링/인력고용/플레이어 거래 |
| 🏅 업적 | 45종 업적 시스템 |
| 🏆 랭킹 | 소지금 / 전재산 리더보드 |

## 로컬 실행

```bash
pip install -r requirements.txt
python run.py            # → http://127.0.0.1:8000
```

기본 DB는 `app.db` (SQLite)입니다.

## 배포 (Render + GitHub) — 3단계

GitHub는 정적 호스팅만 지원하므로, **동적 웹+DB는 Render 같은 백엔드 호스팅**이 필요합니다. 이 저장소의 `render.yaml`(Blueprint)이 웹 서비스와 Postgres를 **한 번에 자동 생성**해줍니다.

1. **GitHub**: 저장소 생성 → 이 폴더 push (`git init`, `git add .`, `git commit`, `git push`)
2. **Render**: [render.com](https://render.com) 가입 → **New + → Blueprint** → GitHub 저장소 선택
   - `render.yaml`이 인식되어 `amado-economy`(웹) + `amado-economy-db`(Postgres)가 자동 생성
   - `DATABASE_URL`은 자동 연결, `SECRET_KEY`는 자동 생성됨
3. **완료**: 배포된 URL로 접속 → 첫 부팅 시 테이블 자동 생성

> **주의**
> - Render 무료 티어는 **15분 무활동 시 절전**됩니다 (다시 접속하면 깨어남). 주식/부동산/로또는 접근 시 자동으로 오프라인 시간을 보정합니다.
> - Render 무료 Postgres는 **30일 후 만료**됩니다. 오래 쓰려면 유료 Postgres로 바꾸거나 다른 무료 DB(Neon 등)로 `DATABASE_URL`을 교체하세요.
> - 로컬 개발은 SQLite(`app.db`)로 동작하므로 `DATABASE_URL`이 필요 없습니다.

## 구조

```
app/
  main.py          # FastAPI 앱 + 백그라운드 로또
  models.py        # SQLAlchemy ORM (SQLite/Postgres 겸용)
  logic.py         # 돈/은행/직업/퀘스트
  casino_logic.py  # 카지노
  lotto_logic.py   # 로또
  stocks_logic.py  # 주식
  realestate_logic.py # 부동산
  routers/         # 페이지/폼 라우터
  templates/       # Jinja2
  static/          # CSS
```
