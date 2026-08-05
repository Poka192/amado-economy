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

## 배포 — 두 가지 방법

### 추천 구성: PythonAnywhere(앱) + Supabase(DB)

앱은 PythonAnywhere에서, 데이터는 외부 Supabase(Postgres)에 두는 구성. SQLAlchemy라 **`DATABASE_URL` 한 줄만 바꾸면** SQLite ↔ Supabase가 자동 전환됩니다.

1. **Supabase** [supabase.com](https://supabase.com) 가입 → **New project** (무료)
   - **Settings → Database → Connection string → URI** 복사
   - 주소가 `postgresql://postgres.xxxx:비번@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres` 형태
   - 비밀번호는 **Database → Connect → "Reveal"** 로 확인 필요
2. **PythonAnywhere** [pythonanywhere.com](https://pythonanywhere.com) 가입 → 아래 절차로 앱 설정
   - Bash 콘솔: `git clone` + `venv` + `pip install -r requirements.txt`
   - Web 탭: Source code / Virtualenv 지정, WSGI 파일에 `from wsgi import application`
   - **환경변수 설정**: Web 탭 → "Environmental variables" → `DATABASE_URL` = Supabase 연결주소
3. **Reload** → 배포 완료. Supabase 대시보드에서 유저/돈 데이터 조회 가능

> `sslmode=require`는 코드가 자동으로 추가합니다. 로컬 개발은 여전히 SQLite로 동작합니다.

### A) PythonAnywhere (간단) — SQLite 그대로, 항상 켜짐, DB 설정 없음

[pythonanywhere.com](https://www.pythonanywhere.com) 무료 계정 + 아래 6단계.

1. **코드 올리기**: GitHub 저장소(`Poka192/amado-economy`)에서 다운로드 → PythonAnywhere **Files** 탭에 업로드
   (또는 PythonAnywhere 콘솔(Bash)에서 `git clone https://github.com/Poka192/amado-economy.git`)
2. **가상환경 + 의존성**: Bash 콘솔에서
   ```bash
   cd amado-economy
   python3.12 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. **웹 앱 생성**: Web 탭 → **Add a new web app** → **Manual configuration** → Python **3.12**
   - "Source code" = `/home/사용자명/amado-economy`
   - "Virtualenv" = `/home/사용자명/amado-economy/venv`
4. **WSGI 설정**: WSGI configuration file 열어서 전체를 아래로 교체
   ```python
   import sys
   sys.path.insert(0, '/home/사용자명/amado-economy')
   from wsgi import application   # a2wsgi ASGI→WSGI 브리지
   ```
5. **(선택) 정적 파일**: Web 탭 → Static files → `/static/` = `/home/사용자명/amado-economy/app/static/`
6. **Reload** 클릭 → `https://사용자명.pythonanywhere.com` 접속

> **주의**
> - SQLite(`app.db`)는 **repo 폴더가 아닌 안전한 곳**에 두는 게 좋습니다. 원하면 `DATABASE_URL` 환경변수를 `sqlite:////home/사용자명/amado-economy/app.db`로 지정하세요.
> - 무료 티어는 하루 대역폭 제한이 있습니다 (개인용엔 충분).
> - 백그라운드 로또는 웹 앱이 살아있는 동안만 돌고, 꺼졌다 켜지면 접근 시 자동 보정됩니다.

### B) Render (Blueprint) — 외부 Postgres

1. **GitHub**: 이 폴더 push (`git init`, `git add .`, `git commit`, `git push`)
2. **Render**: [render.com](https://render.com) 가입 → **New + → Blueprint** → GitHub 저장소 선택
   - `render.yaml`이 인식되어 `amado-economy`(웹) + `amado-economy-db`(Postgres)가 자동 생성
   - `DATABASE_URL`은 자동 연결, `SECRET_KEY`는 자동 생성됨
3. **완료**: 배포된 URL로 접속 → 첫 부팅 시 테이블 자동 생성

> **주의**: Render 무료 티어는 15분 무활동 시 절전, 무료 Postgres는 30일 후 만료됩니다.

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
