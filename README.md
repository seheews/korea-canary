# Korea Canary

공개정보로 한국의 전쟁 위험 신호를 약 1시간마다 점검하는 비공식 조기경보 페이지.

## 구성
- `index.html` 화면. `data/reports.json`을 읽어 그립니다(5분마다 새 점검 확인).
- `data/reports.json` 점검 기록. 맨 앞이 최신입니다.
- `scripts/prompt.md` 점검 기준(신호 A/B/C, 단계 판정, 세지 않는 것). 기준을 바꾸려면 이 파일을 고칩니다.
- `scripts/update.py` Claude API와 웹검색으로 점검하고 `reports.json`에 추가합니다.
- `.github/workflows/hourly.yml` 매시간 실행.

## 설정
1. GitHub에 새 저장소를 만들고 이 폴더를 올립니다.
2. Settings > Secrets and variables > Actions > New repository secret 에서 `ANTHROPIC_API_KEY`를 등록합니다.
3. Settings > Pages 에서 Source를 `Deploy from a branch`, Branch를 `main` / `(root)`로 설정합니다.
4. Actions 탭에서 `hourly-check`를 `Run workflow`로 한 번 수동 실행해 확인합니다.

## 운영 메모
- 점검이 실패하면 파일을 바꾸지 않고 워크플로가 실패로 표시됩니다. 사이트는 마지막 점검이 90분을 넘으면 스스로 `점검 지연`을 띄웁니다.
- 단계가 2단계 이상 오르면 워크플로 로그에 `[주의]`가 남습니다. 자동 게시 전에 사람이 확인하고 싶다면 `update.py`에서 그 경우 저장하지 않고 실패 처리하도록 바꾸세요.
- 비용은 점검 1회에 웹검색 최대 20회입니다. `CANARY_MAX_SEARCHES`, `CANARY_MODEL` 환경변수로 조절합니다.
- 기본 모델은 `claude-sonnet-5`입니다. 웹검색 도구 버전(`web_search_20250305`)은 API 문서에서 최신 여부를 확인하세요.
- Pages 대신 Cloudflare Pages나 Netlify에 이 저장소를 연결해도 됩니다. 커밋할 때마다 자동 배포됩니다.

## 데이터 스키마 (reports.json)
맨 앞 항목이 최신입니다. 필수: `ts, state, stage(0~4), headline, changes[]`. 나머지는 모두 선택이며, 없으면 화면이 알아서 대체합니다.
- `delta` `{a,b,c,summary,new:[{tier,text}],unchanged[]}` WHAT CHANGED 카드. 없으면 `changes`를 그대로 보여주고 숫자는 `–`로 표시.
- `actions` `{summary,do[],skip[]}` WHAT TO DO 카드. 없으면 단계별 기본 문구.
- `sensors[].rows[]` `[이름, kind, 라벨, 메모, {conf,event,detected,src}]` kind는 `none|moved|watching|unknown`. 5번째 메타는 선택.
- `sources[]` `{title,url,publisher,event_date,first_detected,confidence}`
- 옛 항목에 `stage`가 없으면 `state`로 단계를 환산합니다.

## 미리보기
`index.html?asof=2026-09-24T17:00:00+09:00` 처럼 붙이면 그 시각을 현재로 가정해 최신/지연 상태를 확인할 수 있습니다.

## 업로드할 때 주의 (숨김 폴더)
`.github/workflows/hourly.yml`은 점(.)으로 시작하는 숨김 폴더 안에 있습니다. 파인더·탐색기에서 안 보일 수 있고,
GitHub 웹의 드래그 앤 드롭 업로드는 이 폴더를 빼먹는 경우가 있습니다. 아래 중 하나로 올리세요.
1. 터미널: `cd korea-canary-site && git init && git add -A && git commit -m init && git remote add origin <저장소주소> && git push -u origin main`
2. 웹에서 나머지를 올린 뒤, `Add file > Create new file`에서 파일명에 `.github/workflows/hourly.yml`을 입력하고 내용을 붙여넣기
올린 뒤 저장소의 Actions 탭에 `hourly-check`가 보이면 정상입니다.
