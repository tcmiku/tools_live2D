from __future__ import annotations


def compute_mood(focus_seconds: int, favor: int, interactions: int, idle_ms: int) -> int:
    focus_seconds = max(0, int(focus_seconds))
    favor = max(0, min(100, int(favor)))
    interactions = max(0, int(interactions))
    idle_ms = max(0, int(idle_ms))

    score = 20.0
    score += min(focus_seconds / 7200.0, 1.0) * 30.0
    score += min(interactions / 20.0, 1.0) * 20.0
    score += (favor / 100.0) * 30.0

    idle_hours = (idle_ms / 1000.0) / 3600.0
    score -= min(idle_hours * 20.0, 30.0)

    return int(max(0, min(100, round(score))))


def mood_bucket(score: int) -> tuple[str, str]:
    score = max(0, min(100, int(score)))
    if score >= 80:
        return "开心", "😊"
    if score >= 60:
        return "愉快", "🙂"
    if score >= 40:
        return "平静", "😐"
    if score >= 20:
        return "低落", "😔"
    return "孤独", "😢"


def mood_interval_factor(score: int) -> float:
    score = max(0, min(100, int(score)))
    return 1.2 - (score / 100.0) * 0.4
