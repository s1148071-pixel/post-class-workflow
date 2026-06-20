# utils/__init__.py — 通用工具函数

import json


# ═══════════════════════════════════════════════════════════════
# 知识覆盖度文本 ↔ 结构化数据 转换
# ═══════════════════════════════════════════════════════════════

def _format_coverage_text(coverage_list):
    """将 knowledge_coverage 列表转换为可编辑的文本格式。"""
    lines = []
    for item in coverage_list:
        icon = "✅" if item.get("status", "").startswith("✅") else "⚠️"
        # 使用 ||| 作为分隔符（比 | 更不容易在自然文本中出现）
        lines.append(f"{icon} {item.get('item', '')} ||| {item.get('detail', '')}")
    return "\n".join(lines)


def _parse_coverage_text(text, fallback):
    """将编辑后的文本解析回 knowledge_coverage 列表格式。

    Returns:
        (list, error_message_or_none): 解析成功返回 (list, None)，
        解析失败返回 (fallback, error_message)
    """
    if not text or not text.strip():
        return fallback, None

    items = []
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        status = "✅ 已覆盖" if line.startswith("✅") else "⚠️ 需关注"
        rest = line.lstrip("✅⚠️").strip()
        if " ||| " in rest:
            parts = rest.split(" ||| ", 1)
        elif " | " in rest:
            parts = rest.split(" | ", 1)
        elif " — " in rest:
            parts = rest.split(" — ", 1)
        else:
            parts = [rest, ""]
        items.append({
            "item": parts[0].strip() if len(parts) > 0 else rest,
            "status": status,
            "detail": parts[1].strip() if len(parts) > 1 else "",
        })
    return items, None


# ═══════════════════════════════════════════════════════════════
# 反馈报告编辑合并
# ═══════════════════════════════════════════════════════════════

def merge_feedback_edits(report, edits):
    """将老师在审核台的编辑合并回反馈报告，返回最终版报告。

    编辑映射关系：
      - edits["summary"]                → report["summary"]
      - edits["knowledge_coverage"]     → report["knowledge_coverage"]
      - edits["student_{name}"]         → report["student_performance"][name]["comment"]
      - edits["parent_action_{name}"]   → report["student_performance"][name]["parent_action"]
      - edits["teaching"]               → report["teaching_suggestions"]
      - edits["parent"]                 → report["parent_guide"]

    Args:
        report (dict): AI 生成的原始反馈报告
        edits (dict): 老师的编辑缓存

    Returns:
        dict: 合并后的最终报告（深拷贝，不修改原对象）
    """
    # 深拷贝原始报告，避免污染原对象
    merged = json.loads(json.dumps(report, ensure_ascii=False))

    if not edits:
        merged["_edited"] = False
        return merged

    has_changes = False

    # ── 课堂摘要 ──
    if "summary" in edits and edits["summary"] != report.get("summary", ""):
        merged["summary"] = edits["summary"]
        has_changes = True

    # ── 知识覆盖度 ──
    if "knowledge_coverage" in edits and edits["knowledge_coverage"]:
        original_kc_text = _format_coverage_text(report.get("knowledge_coverage", []))
        if edits["knowledge_coverage"] != original_kc_text:
            parsed, parse_err = _parse_coverage_text(
                edits["knowledge_coverage"], report.get("knowledge_coverage", [])
            )
            if parse_err:
                merged["_knowledge_coverage_parse_error"] = parse_err
            else:
                merged["knowledge_coverage"] = parsed
                has_changes = True

    # ── 学生评语 + 家长行动建议 ──
    students = merged.get("student_performance", {})
    for key, edited_value in edits.items():
        if key.startswith("parent_action_"):
            student_name = key[len("parent_action_"):]
            if student_name in students:
                original = students[student_name].get("parent_action", "")
                if edited_value != original:
                    students[student_name]["parent_action"] = edited_value
                    has_changes = True
        elif key.startswith("student_"):
            student_name = key[len("student_"):]
            if student_name in students:
                original = students[student_name].get("comment", "")
                if edited_value != original:
                    students[student_name]["comment"] = edited_value
                    has_changes = True

    # ── 教学建议 ──
    if "teaching" in edits and edits["teaching"] != report.get("teaching_suggestions", ""):
        merged["teaching_suggestions"] = edits["teaching"]
        has_changes = True

    # ── 家长指引 ──
    if "parent" in edits and edits["parent"] != report.get("parent_guide", ""):
        merged["parent_guide"] = edits["parent"]
        has_changes = True

    merged["_edited"] = has_changes
    return merged


def get_edit_diff(report, edits):
    """对比 AI 原文和老师编辑，返回差异摘要。

    Args:
        report (dict): AI 原始报告
        edits (dict): 老师编辑缓存

    Returns:
        list[dict]: 差异列表，每项 {field, original, edited, changed}
    """
    diffs = []

    # summary
    if "summary" in edits:
        diffs.append({
            "field": "课堂摘要",
            "original": report.get("summary", ""),
            "edited": edits["summary"],
            "changed": edits["summary"] != report.get("summary", ""),
        })

    # knowledge_coverage
    if "knowledge_coverage" in edits:
        original = _format_coverage_text(report.get("knowledge_coverage", []))
        diffs.append({
            "field": "知识覆盖度",
            "original": original,
            "edited": edits["knowledge_coverage"],
            "changed": edits["knowledge_coverage"] != original,
        })

    # students
    students = report.get("student_performance", {})
    for key, edited_value in edits.items():
        if key.startswith("student_"):
            student_name = key[len("student_"):]
            original = students.get(student_name, {}).get("comment", "")
            diffs.append({
                "field": f"{student_name} 的评语",
                "original": original,
                "edited": edited_value,
                "changed": edited_value != original,
            })
        elif key.startswith("parent_action_"):
            student_name = key[len("parent_action_"):]
            original = students.get(student_name, {}).get("parent_action", "")
            diffs.append({
                "field": f"{student_name} 的家长建议",
                "original": original,
                "edited": edited_value,
                "changed": edited_value != original,
            })

    # teaching
    if "teaching" in edits:
        diffs.append({
            "field": "教学建议",
            "original": report.get("teaching_suggestions", ""),
            "edited": edits["teaching"],
            "changed": edits["teaching"] != report.get("teaching_suggestions", ""),
        })

    # parent
    if "parent" in edits:
        diffs.append({
            "field": "家长指引",
            "original": report.get("parent_guide", ""),
            "edited": edits["parent"],
            "changed": edits["parent"] != report.get("parent_guide", ""),
        })

    return diffs


# ═══════════════════════════════════════════════════════════════
# 讲义编辑合并
# ═══════════════════════════════════════════════════════════════

def merge_lecture_edits(notes, edits):
    """将老师在审核台的讲义编辑合并回讲义数据，返回最终版。

    Args:
        notes (dict): AI 生成的原始讲义数据
        edits (dict): 老师的编辑缓存，结构：
            {
                "grammar_points": JSON 字符串,
                "phrases": JSON 字符串,
                "vocabulary_summary": 纯文本,
                "study_tips": 纯文本,
            }

    Returns:
        dict: 合并后的讲义（深拷贝）
    """
    merged = json.loads(json.dumps(notes, ensure_ascii=False))

    if not edits:
        merged["_edited"] = False
        return merged

    has_changes = False

    # ── 语法点列表（JSON 解析后合并）──
    if "grammar_points" in edits and edits["grammar_points"]:
        try:
            parsed = json.loads(edits["grammar_points"])
            if isinstance(parsed, list) and parsed != notes.get("grammar_points", []):
                merged["grammar_points"] = parsed
                has_changes = True
        except (json.JSONDecodeError, TypeError) as e:
            merged["_grammar_parse_error"] = f"语法点 JSON 格式错误（已保留原文）：{e}"

    # ── 短语列表（JSON 解析后合并）──
    if "phrases" in edits and edits["phrases"]:
        try:
            parsed = json.loads(edits["phrases"])
            if isinstance(parsed, list) and parsed != notes.get("phrases", []):
                merged["phrases"] = parsed
                has_changes = True
        except (json.JSONDecodeError, TypeError) as e:
            merged["_phrases_parse_error"] = f"短语 JSON 格式错误（已保留原文）：{e}"

    # ── 词汇总结（纯文本）──
    if "vocabulary_summary" in edits and edits["vocabulary_summary"] != notes.get("vocabulary_summary", ""):
        merged["vocabulary_summary"] = edits["vocabulary_summary"]
        has_changes = True

    # ── 学习建议（纯文本）──
    if "study_tips" in edits and edits["study_tips"] != notes.get("study_tips", ""):
        merged["study_tips"] = edits["study_tips"]
        has_changes = True

    merged["_edited"] = has_changes
    return merged
