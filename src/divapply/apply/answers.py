"""Local answer bank for repeat application questions."""

from __future__ import annotations

import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import yaml

from divapply.config import ANSWERS_PATH


_TOKEN_RE = re.compile(r"[a-z][a-z0-9+#.\-]{1,}", re.IGNORECASE)


def _tokens(text: str) -> Counter:
    return Counter(token.casefold() for token in _TOKEN_RE.findall(text or "") if len(token) > 2)


def _cosine(left: Counter, right: Counter) -> float:
    if not left or not right:
        return 0.0
    dot = sum(left[key] * right.get(key, 0) for key in left)
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def load_answer_bank(path: Path | None = None) -> list[dict]:
    """Load ~/.divapply/answers.yaml without failing on missing files."""
    bank_path = path or ANSWERS_PATH
    if not bank_path.exists():
        return []
    data = yaml.safe_load(bank_path.read_text(encoding="utf-8")) or {}
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = data.get("answers", [])
    else:
        rows = []

    cleaned: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        question = str(row.get("question") or row.get("key") or "").strip()
        answer = str(row.get("answer") or "").strip()
        if question and answer:
            cleaned.append({
                "question": question,
                "answer": answer,
                "tags": row.get("tags") or [],
                "updated_at": row.get("updated_at"),
            })
    return cleaned


def save_answer_bank(entries: list[dict], path: Path | None = None) -> None:
    bank_path = path or ANSWERS_PATH
    bank_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"answers": entries}
    bank_path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=False), encoding="utf-8")


def add_answer(question: str, answer: str, *, tags: list[str] | None = None, path: Path | None = None) -> dict:
    """Add or replace an answer-bank row by exact question text."""
    entries = load_answer_bank(path)
    now = datetime.now(timezone.utc).isoformat()
    normalized = question.strip().casefold()
    row = {
        "question": question.strip(),
        "answer": answer.strip(),
        "tags": tags or [],
        "updated_at": now,
    }
    replaced = False
    for idx, existing in enumerate(entries):
        if existing["question"].strip().casefold() == normalized:
            entries[idx] = row
            replaced = True
            break
    if not replaced:
        entries.append(row)
    save_answer_bank(entries, path)
    return {"entry": row, "replaced": replaced}


def match_answers(question: str, *, limit: int = 3, path: Path | None = None) -> list[dict]:
    """Return fuzzy matches for a form question."""
    qvec = _tokens(question)
    matches: list[dict] = []
    for entry in load_answer_bank(path):
        score = _cosine(qvec, _tokens(entry["question"]))
        if score > 0:
            matches.append({**entry, "score": round(score, 4)})
    matches.sort(key=lambda item: item["score"], reverse=True)
    return matches[:limit]


def render_answer_bank_for_prompt(path: Path | None = None) -> str:
    """Render the full bank compactly for the apply agent prompt."""
    entries = load_answer_bank(path)
    if not entries:
        return "No saved answer-bank entries yet. Compose factual answers from the profile and resume."
    lines = []
    for idx, entry in enumerate(entries, start=1):
        lines.append(f"{idx}. Q: {entry['question']}\n   A: {entry['answer']}")
    return "\n".join(lines)
