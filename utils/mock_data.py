"""
测试用例加载器 — 加载真实课堂数据用于测试。

只保留媛媛的真实测试数据，不再包含任何 Demo 示例数据或 Mock 降级函数。
"""

import json as _json
from pathlib import Path as _Path

TEST_CASES_DIR = _Path(__file__).parent.parent / "test_data"


def list_test_cases():
    """列出所有可用的测试用例。返回 [{name, path, description, ...}]。"""
    cases = []
    if TEST_CASES_DIR.exists():
        for f in sorted(TEST_CASES_DIR.glob("*.json")):
            try:
                data = _json.loads(f.read_text(encoding="utf-8"))
                cases.append({
                    "name": f.stem,
                    "path": str(f),
                    "description": data.get("_description", ""),
                    "teacher": data.get("teacher", ""),
                    "grade": data.get("grade_label", ""),
                })
            except Exception:
                pass
    return cases


def load_test_case(case_name):
    """加载指定测试用例，返回完整 dict。"""
    case_path = TEST_CASES_DIR / f"{case_name}.json"
    if not case_path.exists():
        raise FileNotFoundError(f"测试用例不存在: {case_path}")

    data = _json.loads(case_path.read_text(encoding="utf-8"))

    # 加载逐字稿文本
    transcript_file = data.get("transcript_file", "")
    if transcript_file:
        transcript_path = _Path(__file__).parent.parent / transcript_file
        if transcript_path.exists():
            data["transcript_text"] = transcript_path.read_text(encoding="utf-8")

    return data
