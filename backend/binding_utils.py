from __future__ import annotations

import json
import os
from typing import Tuple, List


def extract_motions_expressions(base_dir: str, model_path: str) -> Tuple[List[str], List[str]]:
    if not model_path:
        return [], []
    full_path = os.path.join(base_dir, "web", model_path)
    if not os.path.exists(full_path):
        return [], []
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return [], []
    motions = []
    expressions = []
    try:
        motion_map = data.get("FileReferences", {}).get("Motions", {})
        if isinstance(motion_map, dict):
            motions = list(motion_map.keys())
    except Exception:
        motions = []
    try:
        expr_list = data.get("FileReferences", {}).get("Expressions", [])
        if isinstance(expr_list, list):
            expressions = [item.get("Name") for item in expr_list if isinstance(item, dict) and item.get("Name")]
    except Exception:
        expressions = []
    return motions, expressions


def list_model_paths(base_dir: str) -> List[str]:
    models_dir = os.path.join(base_dir, "web", "model")
    results: List[str] = []
    if not os.path.isdir(models_dir):
        return results
    for root, _, files in os.walk(models_dir):
        for name in files:
            if not name.endswith(".model3.json"):
                continue
            full_path = os.path.join(root, name)
            rel = os.path.relpath(full_path, os.path.join(base_dir, "web"))
            results.append(rel.replace("\\", "/"))
    results.sort()
    return results
