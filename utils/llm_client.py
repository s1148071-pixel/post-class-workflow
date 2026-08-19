"""
DeepSeek LLM 客户端模块 — Phase 2 核心。

封装 DeepSeek v4 API 调用（OpenAI 兼容端点），输出结构化数据。

使用方式：
  from utils.llm_client import generate_feedback_report, generate_homework_questions

设计原则：
  1. 直连 DeepSeek API（api.deepseek.com/v1），不经过 Cursor proxy
  2. JSON mode 强制结构化输出，减少 parse 失败
  3. API 失败直接抛异常，不做 mock 降级——由调用方决定如何处理错误
  4. 所有网络调用带超时和重试

环境变量：
  DEEPSEEK_API_KEY — DeepSeek API 密钥
  DEEPSEEK_BASE_URL — 自定义 API 地址（默认 https://api.deepseek.com/v1）
"""

import os
import json
import time
from openai import OpenAI

# ── 配置 ──────────────────────────────────────────────────────

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-v4-pro"  # Phase 2 暂不启用 thinking（减少 token 消耗和延迟）

# API key 必须通过环境变量设置，不设默认值（防止密钥泄露到 Git）
_REQUIRED_ENV_VAR = "DEEPSEEK_API_KEY"

_client = None


def _get_client():
    """延迟初始化 OpenAI 客户端（单例）。

    API key 从环境变量 DEEPSEEK_API_KEY 读取，未设置时抛出明确错误。
    """
    global _client
    if _client is None:
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError(
                "未设置 DEEPSEEK_API_KEY 环境变量。\n"
                "请运行: export DEEPSEEK_API_KEY='sk-...'\n"
                "或创建 .env 文件（参考 .env.example）"
            )
        _client = OpenAI(
            api_key=api_key,
            base_url=os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL),
            timeout=120.0,
            max_retries=2,
        )
    return _client


# ── 工具函数 ──────────────────────────────────────────────────

def _call_llm(messages, temperature=0.3, max_tokens=4096):
    """调用 DeepSeek Chat Completion，返回解析后的 JSON dict。

    Args:
        messages: OpenAI 格式的 messages 列表
        temperature: 生成温度
        max_tokens: 最大输出 token

    Returns:
        dict: 解析后的 JSON

    Raises:
        ValueError: JSON 解析失败
        Exception: API 调用失败
    """
    client = _get_client()

    response = client.chat.completions.create(
        model=DEFAULT_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content
    finish_reason = response.choices[0].finish_reason

    # 防护：API 返回空内容（DeepSeek 偶发空响应）
    if not raw:
        raise ValueError(
            f"DeepSeek API 返回空内容（finish_reason={finish_reason}）。"
            f"请重试或稍等片刻再试。"
        )

    # 调试：检查是否被截断
    if finish_reason == "length":
        print(f"[LLM] 警告：响应被截断（finish_reason=length），max_tokens={max_tokens} 可能不够")

    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"[LLM] JSON 解析失败：{e}")
        print(f"[LLM] 响应长度：{len(raw)} 字符")
        print(f"[LLM] 响应前 200 字符：{raw[:200]}")
        print(f"[LLM] 响应后 200 字符：{raw[-200:]}")
        print(f"[LLM] finish_reason：{finish_reason}")
        raise


# ── 公开 API ──────────────────────────────────────────────────

def generate_feedback_report(article, vocabulary, asr_segments=None, grade_level=None):
    """生成课后反馈报告（调用 DeepSeek LLM）。

    Args:
        article: 课堂文章文本
        vocabulary: 词汇表列表 [{"word": "...", "meaning": "..."}, ...]
        asr_segments: 逐字稿片段（可选）
        grade_level: 学生年级，如 "小学三年级" / "初中一年级"（可选）

    Returns:
        dict: 结构化反馈报告，_source 固定为 "llm"

    Raises:
        Exception: API 调用或 JSON 解析失败
    """
    from utils.prompts import build_feedback_prompt

    # 输入截断保护：逐字稿太长会占满上下文窗口，导致输出被截断（finish_reason=length）
    MAX_ASR_CHARS = 8000  # 约 2000 token（中文 ~4 chars/token）
    safe_segments = asr_segments
    if asr_segments:
        total_chars = sum(len(s.get("text", "")) for s in asr_segments)
        if total_chars > MAX_ASR_CHARS:
            # 只保留前 N 个片段，优先保留学生发言（短且信息密度高）
            kept = []
            chars = 0
            for s in asr_segments:
                text = s.get("text", "")
                if chars + len(text) <= MAX_ASR_CHARS:
                    kept.append(s)
                    chars += len(text)
                else:
                    break
            safe_segments = kept
            print(f"[LLM] 逐字稿截断：{len(asr_segments)}→{len(kept)} 片段（{total_chars}→{chars} 字符）")

    messages = build_feedback_prompt(article, vocabulary, safe_segments, grade_level)
    result = _call_llm(messages, temperature=0.3, max_tokens=8192)
    result["_source"] = "llm"
    return result


def generate_homework_questions(article, vocabulary, grade_level=None):
    """生成课后游戏作业（调用 DeepSeek LLM）— Phase 5 v3 格式。

    Args:
        article: 课堂文章文本
        vocabulary: 词汇表列表 [{"word": "...", "meaning": "..."}, ...]
        grade_level: 学生年级，如 "小学三年级" / "初中一年级"（可选）

    Returns:
        dict: v3 游戏数据 schema，_source 固定为 "llm"

    Raises:
        Exception: API 调用或 JSON 解析失败
    """
    from utils.prompts import build_homework_prompt

    messages = build_homework_prompt(article, vocabulary, grade_level)
    result = _call_llm(messages, temperature=0.5, max_tokens=16384)
    result["_source"] = "llm"
    return result


def generate_exercises(lecture_material, vocabulary=None, grade_level=None):
    """生成课后练习题（调用 DeepSeek LLM）— Phase 6 练习模式。

    根据教学材料生成 20 题测试卷（10 词汇选择 + 10 语法选择）。

    Args:
        lecture_material: 教学材料文本（讲义内容/课堂文章/逐字稿）
        vocabulary: 词汇表列表（可选）
        grade_level: 学生年级（可选）

    Returns:
        dict: 测试卷 schema，_source 固定为 "llm"

    Raises:
        Exception: API 调用或 JSON 解析失败
    """
    from utils.prompts import build_exercise_prompt

    messages = build_exercise_prompt(lecture_material, vocabulary, grade_level)
    result = _call_llm(messages, temperature=0.3, max_tokens=8192)
    result["_source"] = "llm"
    return result


def generate_lecture_notes(article, vocabulary, asr_segments=None, grade_level=None):
    """生成课堂讲义（调用 DeepSeek LLM）— Phase 6 全新独立板块。

    从课堂逐字稿和文章中提取语法点和常用搭配，生成结构化讲义。

    Args:
        article: 课堂文章文本
        vocabulary: 词汇表列表
        asr_segments: 逐字稿片段（可选）
        grade_level: 学生年级（可选）

    Returns:
        dict: 讲义 schema，_source 固定为 "llm"

    Raises:
        Exception: API 调用或 JSON 解析失败
    """
    from utils.prompts import build_lecture_notes_prompt

    messages = build_lecture_notes_prompt(article, vocabulary, asr_segments, grade_level)
    result = _call_llm(messages, temperature=0.3, max_tokens=8192)
    result["_source"] = "llm"
    return result


def identify_highlight_clips(article, vocabulary, asr_segments, enable_llm_scoring=True):
    """识别学生高光片段。

    Phase 4：规则引擎（40%）+ LLM 语义评分（60%）双层加权。
    内置多重过滤器 + MAX_HIGHLIGHTS 上限，防止 200+ 条低质片段。
    """
    from utils.prompts import build_highlight_clips_prompt

    # ── 配置 ──
    MAX_HIGHLIGHTS = 10       # 最终返回上限（一对一课 5-10 个真正亮点）
    MAX_LLM_INPUT = 60        # 送给 LLM 评分的最大片段数
    MIN_DURATION = 3.0        # 最短发言秒数
    MIN_WORDS = 4             # 最少词数
    # ⚠️ 不能用 "老师"——腾讯会议昵称里太常见（如"沈老师"是学生）
    TEACHER_MARKERS = {"teacher", "ms.", "mr.", "小木", "ms ", "mr "}

    # ── 构建教师启发式检测 ──
    # 策略：讲话最多/最长的说话人是教师
    speaker_talk_time = {}
    for seg in (asr_segments or []):
        spk = seg.get("speaker", "")
        dur = seg.get("end", 0) - seg.get("start", 0)
        speaker_talk_time[spk] = speaker_talk_time.get(spk, 0) + dur
    # 总讲话时长最长的 → 教师
    teacher_by_heuristic = max(speaker_talk_time, key=speaker_talk_time.get) if speaker_talk_time else ""

    # ── 过滤学生发言 ──
    praise_keywords = {
        "good", "great", "excellent", "wonderful", "brilliant", "amazing",
        "fantastic", "perfect", "well done", "very good", "good job",
        "很棒", "非常好", "厉害", "太棒了", "不错", "很好", "wow",
    }

    student_segments = []
    for seg in (asr_segments or []):
        speaker = seg.get("speaker", "")
        speaker_lower = speaker.lower()

        # 方式1: speaker_type 显式标记（来自 classify_speakers_with_llm）
        speaker_type = seg.get("speaker_type", seg.get("type", ""))
        # 同时兼容旧格式：speaker 字段直接是 "teacher"
        if speaker_type == "teacher" or speaker == "teacher":
            continue

        # 方式2: speaker 名含英文 teacher 标记
        if any(m in speaker_lower for m in TEACHER_MARKERS):
            continue

        # 方式3: 启发式——总讲话时长最长的说话人是教师
        if teacher_by_heuristic and speaker == teacher_by_heuristic:
            # 教师也可能被学生称呼，但如果只有一个学生+一个老师，启发式有效
            # 多人时优先信任 speaker_type
            if not speaker_type:
                continue

        # 质量预筛选
        text = seg.get("text", "")
        duration = seg.get("end", 0) - seg.get("start", 0)
        word_count = len(text.split())
        if duration < MIN_DURATION and word_count < MIN_WORDS:
            continue

        student_segments.append(seg)

    if not student_segments:
        return []  # 无学生发言片段，无高光可识别

    # ── 内容丰富的优先保留 ──
    if len(student_segments) > MAX_LLM_INPUT * 2:
        student_segments.sort(
            key=lambda s: (len(s.get("text", "")) + (s.get("end", 0) - s.get("start", 0)) * 2),
            reverse=True,
        )
        student_segments = student_segments[:MAX_LLM_INPUT * 2]

    # ── 第一层：规则评分 ──
    vocab_words = {v['word'].lower() for v in vocabulary} if vocabulary else set()

    clips = []
    for i, seg in enumerate(student_segments):
        text_lower = seg['text'].lower()
        duration = seg['end'] - seg['start']

        has_praise = any(kw in text_lower for kw in praise_keywords)
        duration_ok = 5 <= duration <= 60
        vocab_used = [w for w in vocab_words if w in text_lower]

        rule_score = 0.3
        if has_praise:
            rule_score += 0.2
        if duration_ok:
            rule_score += 0.1
        if vocab_used:
            rule_score += min(0.2, 0.1 * len(vocab_used))

        clips.append({
            "id": i + 1,
            "start": seg['start'],
            "end": seg['end'],
            "student": seg.get('speaker', 'Unknown'),
            "description": seg['text'][:60] + ("..." if len(seg['text']) > 60 else ""),
            "transcript": seg['text'],
            "reason": f"学生发言{'，包含目标词汇: ' + ', '.join(vocab_used) if vocab_used else ''}",
            "signals": {
                "teacher_praise": has_praise,
                "duration_ok": duration_ok,
                "llm_score": 0.0,
            },
            "rule_score": round(rule_score, 2),
            "auto_score": round(rule_score, 2),
            "selected": False,
        })

    # ── 第二层：LLM 高光原型判断（只送 top MAX_LLM_INPUT 片段）──
    if enable_llm_scoring:
        llm_candidates = sorted(clips, key=lambda c: c["rule_score"], reverse=True)
        llm_candidates = llm_candidates[:MAX_LLM_INPUT]

        llm_input_segments = [
            student_segments[c["id"] - 1] for c in llm_candidates
            if c["id"] - 1 < len(student_segments)
        ]

        try:
            messages = build_highlight_clips_prompt(article, vocabulary, llm_input_segments)
            llm_result = _call_llm(messages, temperature=0.3, max_tokens=8192)

            llm_scores = llm_result if isinstance(llm_result, list) else llm_result.get("scores", llm_result.get("results", []))

            for llm_item in llm_scores:
                llm_idx = llm_item.get("index", -1)
                llm_overall = llm_item.get("overall_score", 0.5)
                llm_start = llm_item.get("start", -1)
                llm_type = llm_item.get("highlight_type", "")

                matched = False
                if isinstance(llm_idx, int) and 1 <= llm_idx <= len(llm_candidates):
                    target = llm_candidates[llm_idx - 1]
                    target["signals"]["llm_score"] = round(llm_overall, 2)
                    target["signals"]["llm_highlight_type"] = llm_type
                    target["reason"] = llm_item.get("reason", target["reason"])
                    matched = True

                if not matched and llm_start >= 0:
                    for clip in llm_candidates:
                        if abs(clip["start"] - llm_start) < 2.0:
                            clip["signals"]["llm_score"] = round(llm_overall, 2)
                            clip["signals"]["llm_highlight_type"] = llm_type
                            clip["reason"] = llm_item.get("reason", clip["reason"])
                            matched = True
                            break

                if not matched:
                    print(f"[LLM] Warning: unmatched LLM score (idx={llm_idx})")

            # 加权融合：LLM 的高光原型判断权重提升到 80%
            for clip in llm_candidates:
                rule = clip.get("rule_score", 0.3)
                llm = clip["signals"].get("llm_score", 0.0)
                if llm > 0:
                    # LLM 识别为高光 → 80% LLM + 20% 规则
                    clip["auto_score"] = round(rule * 0.2 + llm * 0.8, 2)
                else:
                    # LLM 未识别 → 纯规则（降权）
                    clip["auto_score"] = round(rule * 0.6, 2)
                clip["selected"] = clip["auto_score"] >= 0.60

        except Exception as e:
            print(f"[LLM] 语义评分失败，使用纯规则评分：{e}")
            for clip in clips:
                clip["selected"] = clip["rule_score"] >= 0.5

    # ── 最终截断：LLM 识别到的优先，同分按 auto_score 降序 ──
    # 排序规则：LLM 打分过的排前面（不管分数高低），纯规则分的排后面
    clips.sort(key=lambda c: (
        c["signals"].get("llm_score", 0) > 0,  # LLM 识别到的置顶
        c["auto_score"]  # 同组内按分数降序
    ), reverse=True)
    clips = clips[:MAX_HIGHLIGHTS]

    for i, clip in enumerate(clips):
        clip["id"] = i + 1

    return clips


def classify_speakers(asr_segments, teacher_hint=None):
    """用 LLM 对转写片段做说话人角色分类（teacher vs student）。

    供 asr_client.py 调用的便捷函数。

    Args:
        asr_segments: 转写片段列表 [{"speaker": "unknown", "start": ..., "end": ..., "text": ...}]
        teacher_hint: 老师名字提示

    Returns:
        list[dict]: 更新了 speaker 字段的 segments
    """
    from utils.prompts import build_speaker_classify_prompt

    if not asr_segments:
        return asr_segments

    messages = build_speaker_classify_prompt(asr_segments, teacher_hint)

    try:
        result = _call_llm(messages, temperature=0.1, max_tokens=4096)
        classifications = result if isinstance(result, list) else result.get("classifications", [])

        student_count = 0
        role_map = {}
        for item in classifications:
            if isinstance(item, dict) and "index" in item:
                role_map[int(item["index"])] = item.get("role", "unknown")

        for i, seg in enumerate(asr_segments):
            role = role_map.get(i, "unknown")
            if role == "teacher":
                seg["speaker_type"] = "teacher"
            elif role == "student":
                student_count += 1
                seg["speaker_type"] = "student"
            # unknown 保持原样
    except Exception as e:
        print(f"[LLM] 说话人分类失败：{e}")

    return asr_segments


# ── 便捷函数 ──────────────────────────────────────────────────

def check_connectivity():
    """快速检查 DeepSeek API 连通性。TCP 层直连（无需 LLM 推理），<200ms。

    返回 (bool, latency_ms_or_error)。
    先用 TCP socket 测试 api.deepseek.com:443 是否可达，
    如果可达再用 models API 验证认证密钥有效性。
    """
    import socket
    from urllib.parse import urlparse

    base_url = os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL)
    host = urlparse(base_url).hostname
    port = urlparse(base_url).port or 443

    # 第一层：TCP 连通性（~100-300ms，不触发 LLM 推理）
    t0 = time.time()
    try:
        sock = socket.create_connection((host, port), timeout=2)
        sock.close()
        tcp_latency = (time.time() - t0) * 1000

        # 第二层：API 认证验证（用 models.list() 不走推理，~500ms）
        try:
            t1 = time.time()
            client = _get_client()
            client.models.list()
            api_latency = (time.time() - t1) * 1000
            total_latency = tcp_latency + api_latency
            return True, total_latency
        except Exception:
            # models API 不可用但 TCP 通了——仍然算连通（可能是权限限制）
            return True, tcp_latency

    except Exception as e:
        return False, str(e)
