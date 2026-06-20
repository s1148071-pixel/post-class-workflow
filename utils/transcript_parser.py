"""
腾讯会议转写稿解析器 — Phase 4 新增。

解析老师粘贴的腾讯会议转写稿文本，输出标准化的 ASR segments 格式。
支持多种常见导出格式，自动检测并解析。

输出格式与 mock_data.mock_asr_result() 完全一致：
  {"speakers": {"role_id": "display_name", ...}, "segments": [...]}
"""

import re
import json
from typing import Optional


def parse_transcript(text: str) -> dict:
    """解析转写稿文本，自动检测格式并返回标准化结果。

    Args:
        text: 转写稿原始文本

    Returns:
        {"speakers": {...}, "segments": [...]}

    Raises:
        ValueError: 无法识别格式或解析失败
    """
    text = text.strip()
    if not text:
        raise ValueError("转写稿文本为空")

    # 尝试 JSON 格式
    if text.startswith("{"):
        return _parse_json_format(text)

    # 检测格式并解析（腾讯会议括号格式优先——最常见）
    if _detect_bracket_format(text):
        return _parse_bracket_format(text)
    elif _detect_inline_format(text):
        return _parse_inline_format(text)
    elif _detect_srt_format(text):
        return _parse_srt_format(text)
    elif _detect_speaker_line_format(text):
        return _parse_speaker_line_format(text)
    else:
        raise ValueError(
            "无法识别转写稿格式。支持的格式：\n"
            "1. 腾讯会议格式（如：高木学习(00:01:08): 发言内容…）\n"
            "2. 说话人 + 时间戳分行（如：王老师 00:01:20\\n发言内容…）\n"
            "3. 内联格式（如：[00:01:20] 王老师：发言内容）\n"
            "4. SRT 字幕格式\n"
            "5. JSON 格式"
        )


# ═══════════════════════════════════════════════════════════════
# 格式检测
# ═══════════════════════════════════════════════════════════════

def _detect_speaker_line_format(text: str) -> bool:
    """检测是否为"说话人 时间戳"分行格式。

    示例：
      王老师 00:00:00
      大家好，今天我们来学习...
    """
    lines = text.strip().split("\n")
    speaker_time_count = 0
    for line in lines[:20]:
        if re.match(r'^.+?\s+\d{1,2}:\d{2}(?::\d{2})?\s*$', line.strip()):
            speaker_time_count += 1
    return speaker_time_count >= 2


def _detect_inline_format(text: str) -> bool:
    """检测是否为内联格式。

    示例：
      [00:00:00] 王老师：大家好，今天我们来学习...
    """
    lines = text.strip().split("\n")
    inline_count = 0
    for line in lines[:20]:
        if re.match(r'^\[[\d:.]+\]\s*.+', line.strip()):
            inline_count += 1
    return inline_count >= 2


def _detect_bracket_format(text: str) -> bool:
    """检测是否为腾讯会议括号格式。

    示例：
      高木学习(00:01:08): 媛媛他可以听到吗？
      許嘉欣(00:04:55): 可以。
    """
    lines = text.strip().split("\n")
    bracket_count = 0
    for line in lines[:20]:
        if re.match(r'^.+?\(\d{1,2}:\d{2}(?::\d{2})?\)[：:]\s*.+', line.strip()):
            bracket_count += 1
    return bracket_count >= 2


def _detect_srt_format(text: str) -> bool:
    """检测是否为 SRT 字幕格式。

    示例：
      1
      00:00:00,000 --> 00:00:12,500
      大家好，今天我们来学习...
    """
    srt_block_count = 0
    lines = text.strip().split("\n")
    for i, line in enumerate(lines[:30]):
        if re.match(r'^\d+$', line.strip()) and i + 2 < len(lines):
            if re.match(r'^[\d:,]+\s*-->\s*[\d:,]+', lines[i + 1].strip()):
                srt_block_count += 1
    return srt_block_count >= 2


# ═══════════════════════════════════════════════════════════════
# 格式解析器
# ═══════════════════════════════════════════════════════════════

def _parse_speaker_line_format(text: str) -> dict:
    """解析"说话人 时间戳"分行格式。

    输入：
      王老师 00:00:00
      Good morning everyone! Today we're going to learn...
      王老师 00:00:15
      Please open your books to page 42.
      Alice 00:01:20
      Teacher, I have a question about the homework.

    解析规则：
      - 匹配"说话人 时间戳"行，后续行（非时间戳行）为发言内容
      - 连续同一说话人的相邻段落自动合并
    """
    lines = text.strip().split("\n")
    raw_entries = []  # [(speaker, start_seconds, text_lines)]

    current_speaker = None
    current_start = None
    current_text_lines = []

    speaker_time_re = re.compile(r'^(.+?)\s+(\d{1,2}:\d{2}(?::\d{2})?)\s*$')

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue

        m = speaker_time_re.match(line_stripped)
        if m:
            # 保存前一个 entry
            if current_speaker and current_text_lines:
                raw_entries.append((current_speaker, current_start, current_text_lines))

            current_speaker = m.group(1).strip()
            current_start = _parse_timestamp(m.group(2))
            current_text_lines = []
        else:
            # 发言内容
            current_text_lines.append(line_stripped)

    # 保存最后一个 entry
    if current_speaker and current_text_lines:
        raw_entries.append((current_speaker, current_start, current_text_lines))

    return _build_standard_result(raw_entries)


def _parse_bracket_format(text: str) -> dict:
    """解析腾讯会议括号格式。

    输入：
      高木学习(00:01:08): 媛媛他可以听到吗？
      許嘉欣(00:04:55): 可以。
      高木学习(00:04:58): 好的可以了。

    格式规则：
      - 说话人名称 + (时间戳) + : 或 ： + 发言内容
      - 时间戳可以是 MM:SS 或 HH:MM:SS
    """
    lines = text.strip().split("\n")
    raw_entries = []

    # 匹配：名字(时间戳): 内容
    pattern = re.compile(r'^(.+?)\((\d{1,2}:\d{2}(?::\d{2})?)\)[：:]\s*(.+)$')

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue

        m = pattern.match(line_stripped)
        if m:
            speaker = m.group(1).strip()
            start = _parse_timestamp(m.group(2))
            text = m.group(3).strip()
            raw_entries.append((speaker, start, [text]))

    return _build_standard_result(raw_entries)


def _parse_inline_format(text: str) -> dict:
    """解析内联格式。

    输入：
      [00:00:00] 王老师：Good morning everyone! Today we're going to learn...
      [00:00:15] 王老师：Please open your books to page 42.
      [00:01:20] Alice：Teacher, I have a question about the homework.

    也支持不带方括号的简化格式：
      00:00 王老师：Good morning everyone!
    """
    lines = text.strip().split("\n")
    raw_entries = []

    # 模式 1: [timestamp] Speaker: text
    pattern1 = re.compile(r'^\[([\d:,\.]+)\]\s*(.+?)[：:]\s*(.+)$')
    # 模式 2: timestamp Speaker: text (无方括号)
    pattern2 = re.compile(r'^(\d{1,2}:\d{2}(?::\d{2})?)\s+(.+?)[：:]\s+(.+)$')

    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            continue

        m = pattern1.match(line_stripped) or pattern2.match(line_stripped)
        if m:
            start = _parse_timestamp(m.group(1))
            speaker = m.group(2).strip()
            text = m.group(3).strip()
            raw_entries.append((speaker, start, [text]))

    return _build_standard_result(raw_entries)


def _parse_srt_format(text: str) -> dict:
    """解析 SRT 字幕格式。

    支持标准 SRT：
      1
      00:00:00,000 --> 00:00:12,500
      大家好，今天我们来学习...

    也支持带说话人标签的 SRT：
      1
      00:00:00,000 --> 00:00:12,500
      <v 王老师>大家好，今天我们来学习...
    """
    blocks = re.split(r'\n\s*\n', text.strip())
    raw_entries = []

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        lines = block.split("\n")
        # 跳过序号行
        start_idx = 0
        for i, line in enumerate(lines):
            if re.match(r'^[\d:,\.]+\s*-->\s*[\d:,\.]+', line.strip()):
                start_idx = i
                break

        if start_idx == 0 and len(lines) >= 2:
            # 有序号或无序号 SRT：line[0] 可能是序号或时间戳
            if re.match(r'^\d+$', lines[0].strip()):
                # 有序号：line[0]=序号, line[1]=时间戳, line[2:]=文本
                time_line = lines[1]
                text_lines = lines[2:]
            else:
                # 无序号：line[0]=时间戳, line[1:]=文本
                time_line = lines[0]
                text_lines = lines[1:]
        elif start_idx > 0:
            time_line = lines[start_idx]
            text_lines = lines[start_idx + 1:]
        else:
            continue

        # 解析时间戳
        time_match = re.match(r'^([\d:,\.]+)\s*-->\s*([\d:,\.]+)', time_line.strip())
        if not time_match:
            continue
        start = _parse_timestamp(time_match.group(1))
        end = _parse_timestamp(time_match.group(2))

        text = " ".join(text_lines).strip()
        if not text:
            continue

        # 尝试提取说话人标签 <v Speaker>
        speaker = "Unknown"
        speaker_tag = re.match(r'<v\s+(.+?)>(.*)', text)
        if speaker_tag:
            speaker = speaker_tag.group(1).strip()
            text = speaker_tag.group(2).strip()

        raw_entries.append((speaker, start, [text]))

    return _build_standard_result(raw_entries)


def _parse_json_format(text: str) -> dict:
    """解析 JSON 格式转写稿。

    支持格式：
    {
      "speakers": [{"id": "s1", "name": "Alice"}, ...],
      "transcripts": [
        {"speaker": "s1", "start": 120.0, "end": 135.0, "text": "..."},
        ...
      ]
    }
    或者腾讯会议 API 返回的原始格式。
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 格式解析失败：{e}")

    segments = []
    speakers_map = {}

    # 尝试多种 JSON schema
    if "speakers" in data:
        if isinstance(data["speakers"], list):
            for s in data["speakers"]:
                sid = s.get("id", s.get("speaker_id", str(len(speakers_map))))
                name = s.get("name", s.get("display_name", sid))
                speakers_map[sid] = name
        elif isinstance(data["speakers"], dict):
            speakers_map = data["speakers"]

    # 查找 transcripts/segments
    raw_segs = data.get("transcripts", data.get("segments", data.get("results", [])))
    if not raw_segs and isinstance(data, list):
        raw_segs = data  # 整个 JSON 就是个数组

    for seg in raw_segs:
        speaker = seg.get("speaker", seg.get("speaker_id", "unknown"))
        start = seg.get("start", seg.get("start_time", seg.get("begin_time", 0)))
        end = seg.get("end", seg.get("end_time", seg.get("finish_time", start + 5)))
        text = seg.get("text", seg.get("content", seg.get("transcript", "")))

        if isinstance(start, str):
            start = _parse_timestamp(start)
        if isinstance(end, str):
            end = _parse_timestamp(end)

        # 记录说话人
        if speaker not in speakers_map:
            speakers_map[speaker] = speaker

        segments.append({
            "speaker": speaker,
            "start": float(start),
            "end": float(end),
            "text": text,
        })

    return {
        "speakers": speakers_map,
        "segments": segments,
    }


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def _parse_timestamp(ts: str) -> float:
    """解析时间戳字符串为秒数。

    支持格式：
      - MM:SS       → 秒
      - HH:MM:SS    → 秒
      - HH:MM:SS.ms → 秒（浮点）
      - 纯数字字符串 → 秒
    """
    ts = ts.strip()
    # 尝试直接转换纯数字
    try:
        return float(ts)
    except ValueError:
        pass

    # 替换中文冒号
    ts = ts.replace("：", ":")

    # HH:MM:SS[.ms] 或 MM:SS[.ms]
    parts = ts.split(":")
    if len(parts) == 2:
        m, s = parts
        return int(m) * 60 + float(s.replace(",", "."))
    elif len(parts) == 3:
        h, m, s = parts
        return int(h) * 3600 + int(m) * 60 + float(s.replace(",", "."))
    else:
        return 0.0


def _build_standard_result(raw_entries: list) -> dict:
    """从原始条目构建标准化结果。

    处理：
      - 合并连续同一说话人的相邻段落
      - 生成 speakers 映射（role_id → display_name）
      - 将 segments 中的 speaker 映射为 role_id

    Args:
        raw_entries: [(speaker, start_seconds, [text_lines]), ...]

    Returns:
        {"speakers": {...}, "segments": [...]}
    """
    if not raw_entries:
        raise ValueError("解析后无有效条目，请检查转写稿格式")

    # 合并相邻同一说话人
    merged = []
    for speaker, start, text_lines in raw_entries:
        text = " ".join(text_lines).strip()
        if not text:
            continue

        if merged and merged[-1]["_raw_speaker"] == speaker:
            # 同一说话人相邻 → 追加文本
            merged[-1]["text"] += " " + text
        else:
            merged.append({
                "_raw_speaker": speaker,  # 原始名称
                "start": start,
                "text": text,
            })

    # 计算 end 时间（用下一段的 start，最后一段 +10 秒）
    for i, seg in enumerate(merged):
        if i + 1 < len(merged):
            seg["end"] = merged[i + 1]["start"]
        else:
            seg["end"] = seg["start"] + max(5.0, min(30.0, len(seg["text"]) * 0.15))

    # 构建 speakers 映射：原始名 → role_id
    name_to_role = {}
    speakers_map = {}
    seen_names = []

    for seg in merged:
        raw_name = seg["_raw_speaker"]
        if raw_name not in seen_names:
            seen_names.append(raw_name)
            raw_lower = raw_name.lower().strip()

            # 判断是否为老师
            teacher_keywords = ("teacher", "ms.", "mr.", "老师", "王老师", "李老师",
                               "张老师", "陈老师", "刘老师", "ms ", "mr ")
            is_teacher = (
                raw_lower in ("teacher", "ms.", "mr.") or
                any(kw in raw_lower for kw in ("老师", "teacher"))
            )

            if is_teacher:
                name_to_role[raw_name] = "teacher"
                speakers_map["teacher"] = raw_name
            elif len(seen_names) == 1:
                # 第一个说话人 → 假设是老师
                name_to_role[raw_name] = "teacher"
                speakers_map["teacher"] = raw_name
            else:
                role_id = f"s{len(speakers_map)}"
                name_to_role[raw_name] = role_id
                speakers_map[role_id] = raw_name

    # 将 segment 的 speaker 从原始名映射为 role_id
    for seg in merged:
        raw_name = seg.pop("_raw_speaker")
        seg["speaker"] = name_to_role.get(raw_name, raw_name)

    return {
        "speakers": speakers_map,
        "segments": merged,
    }


# ═══════════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════════

def is_transcript_available(text: Optional[str]) -> bool:
    """检查转写稿文本是否可用（非空且有足够内容）。"""
    if not text or not text.strip():
        return False
    stripped = text.strip()
    # 至少包含时间戳模式或足够长的内容
    if re.search(r'\d{1,2}:\d{2}', stripped):
        return True
    return len(stripped) > 50


def get_parse_summary(result: dict) -> str:
    """获取解析结果摘要，供日志显示。"""
    speakers = result.get("speakers", {})
    segments = result.get("segments", [])
    total_duration = segments[-1]["end"] if segments else 0
    speaker_names = ", ".join(speakers.values())
    return (
        f"解析完成：{len(segments)} 个片段, "
        f"{len(speakers)} 位说话人 ({speaker_names}), "
        f"总时长 {total_duration:.0f}s"
    )


# ═══════════════════════════════════════════════════════════════
# 腾讯会议转写稿 Mock 示例（用于 Demo 演示）
# ═══════════════════════════════════════════════════════════════

SAMPLE_TENCENT_TRANSCRIPT = """王老师 00:00:00
Good morning everyone! Today we're going to learn a very interesting story called "The Bee and the Sheep's Street Sweep".

王老师 00:00:15
Please open your books to page 42. Let's look at the new words first. bee 蜜蜂, sheep 绵羊, street 街道, sweep 打扫.

王老师 00:00:48
Who can tell me what sound does 'ee' make in these words?

Alice 00:01:02
Teacher, 'ee' makes the long E sound, like in bee and sheep and tree!

王老师 00:01:15
Excellent, Alice! That's exactly right. The double E makes the long E sound. Now, Bob, can you read the first paragraph for us?

Bob 00:01:25
The bee is busy on the street. The bee sweeps and sweeps. The sheep comes to help the bee. They sweep the street together.

王老师 00:01:50
Wonderful reading, Bob! Your pronunciation is very clear. Now, does anyone notice something interesting about the story?

Cathy 00:02:05
The bee and the sheep are friends! The sheep helps the bee even though they are different animals. It's like... teamwork?

王老师 00:02:20
Brilliant observation, Cathy! You found the deeper meaning of the story. Yes, it's about helping each other no matter who we are.

Alice 00:02:42
I also noticed that 'sweep' has two E's too! So it's part of the 'ee' family even though it has an extra letter.

王老师 00:02:55
Wow, Alice! That's a fantastic connection. You're absolutely right. sweep has the ee sound even with the 'w' in between. That's very advanced thinking.

Bob 00:03:20
Can I try to make a sentence with all the ee words? Bee, sheep, street, sweep, green, tree, free, deep, sleepy, sweet... The sleepy bee and the sweet sheep sweep the green street under the deep tree for free!

王老师 00:03:48
That's amazing, Bob! You used all ten words in one creative sentence. Give him a big round of applause! That's exactly the kind of creative thinking I want to see.

Cathy 00:04:10
I think the story teaches us that working together makes everything more fun. Just like the bee and the sheep—sweeping alone is boring, but together it's an adventure.

王老师 00:04:28
What a beautiful way to end our lesson, Cathy. You all did fantastic today. Remember to practice your ee words at home. See you next time!
"""


if __name__ == "__main__":
    # 快速测试
    result = parse_transcript(SAMPLE_TENCENT_TRANSCRIPT)
    print(get_parse_summary(result))
    print("\n--- Segments ---")
    for seg in result["segments"]:
        print(f"[{seg['start']:.1f}s-{seg['end']:.1f}s] {seg['speaker']}: {seg['text'][:60]}...")
