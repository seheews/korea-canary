#!/usr/bin/env python3
"""Korea Canary 점검 실행: 웹검색으로 점검하고 data/reports.json 맨 앞에 새 항목을 추가한다.

실패하면(검색 실패, JSON 오류, 검증 실패) 파일을 건드리지 않고 종료 코드 1로 끝난다.
그러면 사이트는 '점검 지연' 표시로 오래된 결과임을 스스로 알린다.
"""
import copy
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import anthropic

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "reports.json"
PROMPT = (Path(__file__).resolve().parent / "prompt.md").read_text(encoding="utf-8")

MODEL = os.environ.get("CANARY_MODEL", "claude-sonnet-5")
MAX_SEARCHES = int(os.environ.get("CANARY_MAX_SEARCHES", "20"))
KEEP = int(os.environ.get("CANARY_KEEP", "240"))  # 보관할 점검 수(약 10일치)
KST = timezone(timedelta(hours=9))

STATES = {"정상", "주의해서 볼 변화 있음", "강한 신호"}
KINDS = {"none", "moved", "unknown", "watching"}
CONFS = {"high", "medium", "low"}


def load():
    return json.loads(DATA.read_text(encoding="utf-8"))["reports"]


def call_model(previous, now):
    client = anthropic.Anthropic()
    user = (
        f"현재 시각: {now.strftime('%Y-%m-%d %H:%M')} (KST)\n\n"
        "직전 점검 결과(JSON):\n"
        f"{json.dumps(previous, ensure_ascii=False)}\n\n"
        "직전 점검 이후 새로 바뀐 것을 웹 검색으로 확인하고, 지침의 형식대로 새 점검 결과 JSON 하나만 출력하세요."
    )
    messages = [{"role": "user", "content": user}]
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": MAX_SEARCHES}]

    # 서버 도구가 긴 턴을 잠시 멈출 수 있어(pause_turn) 이어서 실행한다.
    for _ in range(6):
        resp = client.messages.create(
            model=MODEL, max_tokens=8000, system=PROMPT, tools=tools, messages=messages
        )
        if resp.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": resp.content})
            continue
        return "".join(b.text for b in resp.content if b.type == "text")
    raise RuntimeError("점검이 끝나지 않았습니다(pause_turn 반복)")


def extract_json(text):
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("응답에서 JSON을 찾지 못했습니다")
    return json.loads(text[start : end + 1])


def clean_str(x, limit=1200):
    if not isinstance(x, str) or not x.strip():
        raise ValueError("빈 문자열")
    return x.strip()[:limit]


def validate(r):
    """모델 출력은 신뢰하지 않는다. 형식을 검증하고 필요한 필드만 남긴다."""
    stage = r.get("stage")
    if not isinstance(stage, int) or not 0 <= stage <= 4:
        raise ValueError(f"stage 값 오류: {stage!r}")
    state = r.get("state")
    if state not in STATES:
        raise ValueError(f"state 값 오류: {state!r}")

    out = {
        "state": state,
        "stage": stage,
        "headline": clean_str(r.get("headline"), 400),
        "changes": [clean_str(x) for x in r.get("changes", [])][:8],
        "absent": [clean_str(x, 200) for x in r.get("absent", [])][:10],
        "action": clean_str(r.get("action"), 800),
    }
    if not out["changes"]:
        raise ValueError("changes가 비어 있습니다")

    sensors = []
    for g in r.get("sensors", [])[:4]:
        rows = []
        for row in g.get("rows", [])[:12]:
            if len(row) < 3 or row[1] not in KINDS:
                raise ValueError(f"센서 행 오류: {row!r}")
            memo = clean_str(row[3], 240) if len(row) > 3 and row[3] else ""
            item = [clean_str(row[0], 120), row[1], clean_str(row[2], 20), memo]
            meta = row[4] if len(row) > 4 and isinstance(row[4], dict) else None
            if meta:
                m = {}
                if meta.get("conf") in CONFS:
                    m["conf"] = meta["conf"]
                for k in ("event", "detected"):
                    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(meta.get(k, ""))):
                        m[k] = meta[k]
                if isinstance(meta.get("src"), str) and meta["src"].strip():
                    m["src"] = meta["src"].strip()[:80]
                if m:
                    item.append(m)
            rows.append(item)
        sensors.append({"group": clean_str(g.get("group"), 80), "note": (g.get("note") or "")[:300], "rows": rows})
    if len(sensors) < 3:
        raise ValueError("sensors는 A/B/C 세 그룹이 필요합니다")
    out["sensors"] = sensors

    # 화면의 WHAT CHANGED 카드용 요약. 없으면 화면이 changes로 대체한다.
    d = r.get("delta")
    if isinstance(d, dict):
        def cnt(x):
            return max(0, min(99, int(x))) if isinstance(x, (int, float)) else 0
        out["delta"] = {
            "a": cnt(d.get("a")), "b": cnt(d.get("b")), "c": cnt(d.get("c")),
            "summary": clean_str(d.get("summary") or "중요한 변화 없음", 80),
            "new": [{"tier": (x.get("tier") if x.get("tier") in ("A", "B", "C") else ""), "text": clean_str(x.get("text"), 300)}
                    for x in d.get("new", []) if isinstance(x, dict)][:6],
            "unchanged": [clean_str(x, 200) for x in d.get("unchanged", [])][:6],
        }

    # 화면의 WHAT TO DO 카드용. 없으면 화면이 단계별 기본 문구를 쓴다.
    a = r.get("actions")
    if isinstance(a, dict) and a.get("summary"):
        out["actions"] = {
            "summary": clean_str(a["summary"], 120),
            "do": [clean_str(x, 40) for x in a.get("do", [])][:5],
            "skip": [clean_str(x, 40) for x in a.get("skip", [])][:5],
        }

    sources = []
    for s in r.get("sources", [])[:12]:
        url = s.get("url", "") if isinstance(s, dict) else ""
        if urlparse(url).scheme in ("http", "https"):
            item = {"title": (s.get("title") or url)[:160], "url": url}
            if isinstance(s.get("publisher"), str):
                item["publisher"] = s["publisher"][:60]
            for k in ("event_date", "first_detected"):
                if re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(s.get(k, ""))):
                    item[k] = s[k]
            if s.get("confidence") in CONFS:
                item["confidence"] = s["confidence"]
            sources.append(item)
    out["sources"] = sources
    return out


def main():
    reports = load()
    now = datetime.now(KST)
    previous = reports[0]

    text = call_model(previous, now)
    new = validate(extract_json(text))
    new["ts"] = now.strftime("%Y-%m-%dT%H:%M:00+09:00")

    # 직전 최신 점검의 센서 표는 기록용으로 줄인다.
    older = copy.deepcopy(reports)
    if older:
        older[0].pop("sensors", None)

    jump = new["stage"] - previous.get("stage", 0)
    if jump >= 2:
        print(f"[주의] 단계가 {jump}단계 상승했습니다: {previous.get('stage')} -> {new['stage']}", file=sys.stderr)

    merged = [new] + older
    DATA.write_text(json.dumps({"reports": merged[:KEEP]}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {new['ts']} stage={new['stage']} {new['headline']}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # 실패 시 파일은 그대로 두고 워크플로를 실패 처리
        print(f"점검 실패: {e}", file=sys.stderr)
        sys.exit(1)
