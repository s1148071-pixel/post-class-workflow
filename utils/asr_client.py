"""
ASR 客户端 — Phase 4 新增。

封装本地 Whisper 语音识别 + LLM 说话人分类。
输入视频文件，输出标准化的 ASR segments（与 mock_data.mock_asr_result() 格式一致）。

使用方式：
  from utils.asr_client import transcribe_video

依赖：
  - openai-whisper（已安装）
  - FFmpeg（通过 video_processor 调用）
  - DeepSeek API（通过 llm_client 调用，用于说话人分类）
"""

import os
import re
import time
import json
import tempfile
from typing import Optional, Callable

# ═══════════════════════════════════════════════════════════════
# Whisper 模型管理（延迟加载 + 缓存）
# ═══════════════════════════════════════════════════════════════

_whisper_model = None
_whisper_model_name = None

# 模型推荐：
# tiny   (~1GB)  — 快但中英混合效果差
# base   (~1GB)  — 略好但仍不够
# small  (~2GB)  — 中英混合最低可用
# medium (~5GB)  — 推荐，中英混合效果好
# large  (~10GB) — 最好但慢
DEFAULT_MODEL = "medium"


def _load_whisper_model(model_name: str = DEFAULT_MODEL):
    """延迟加载 Whisper 模型（单例缓存）。"""
    global _whisper_model, _whisper_model_name
    if _whisper_model is not None and _whisper_model_name == model_name:
        return _whisper_model

    import whisper
    print(f"[ASR] 加载 Whisper 模型: {model_name} …")
    t0 = time.time()
    _whisper_model = whisper.load_model(model_name)
    _whisper_model_name = model_name
    print(f"[ASR] 模型加载完成 ({time.time() - t0:.1f}s)")
    return _whisper_model


# ═══════════════════════════════════════════════════════════════
# 转写
# ═══════════════════════════════════════════════════════════════

def transcribe_video(
    video_path: str,
    model_size: str = DEFAULT_MODEL,
    language: Optional[str] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> dict:
    """从视频文件提取音频并转写。

    流程：
      1. FFmpeg 提取音频 (16kHz mono WAV)
      2. Whisper 转写（带时间戳分段）
      3. 结果整理为标准化 segments 格式

    Args:
        video_path: 视频文件路径
        model_size: Whisper 模型大小 (tiny/base/small/medium/large)
        language: 强制指定语言（如 "zh" 或 "en"，不指定则自动检测）
        progress_callback: 进度回调，接收状态字符串

    Returns:
        {"speakers": {...}, "segments": [...]}

    Raises:
        FileNotFoundError: 视频文件不存在
        RuntimeError: 转写失败
    """
    from utils.video_processor import extract_audio

    if not os.path.isfile(video_path):
        raise FileNotFoundError(f"视频文件不存在: {video_path}")

    # Step 1: 提取音频
    if progress_callback:
        progress_callback("正在从视频中提取音频...")
    t0 = time.time()

    audio_path = extract_audio(video_path)
    audio_duration = _get_audio_duration(audio_path)

    if progress_callback:
        progress_callback(
            f"音频提取完成 ({audio_duration:.0f}s) → 开始 Whisper 转写 ({model_size})..."
        )

    # Step 2: Whisper 转写
    model = _load_whisper_model(model_size)

    transcribe_kwargs = {
        "verbose": False,
        "word_timestamps": True,  # 获取词级时间戳以精确切分
    }
    if language:
        transcribe_kwargs["language"] = language

    # 对于中英混合课堂，不指定语言让 Whisper 自动检测
    # whisper 原生支持 language auto-detection

    try:
        result = model.transcribe(audio_path, **transcribe_kwargs)
    except Exception as e:
        # 清理临时音频文件
        try:
            os.unlink(audio_path)
        except OSError:
            pass
        raise RuntimeError(f"Whisper 转写失败: {e}") from e

    # 清理临时音频
    try:
        os.unlink(audio_path)
    except OSError:
        pass

    elapsed = time.time() - t0
    if progress_callback:
        progress_callback(
            f"Whisper 转写完成 → {len(result.get('segments', []))} 个片段 "
            f"({elapsed:.0f}s, {audio_duration / elapsed:.1f}x 实时)"
        )

    # Step 3: 整理为标准格式
    segments = []
    for seg in result.get("segments", []):
        text = seg.get("text", "").strip()
        if not text:
            continue
        segments.append({
            "speaker": "unknown",  # 后续 LLM 分类
            "start": float(seg.get("start", 0)),
            "end": float(seg.get("end", 0)),
            "text": text,
        })

    # 合并过短的相邻片段
    segments = _merge_short_segments(segments, min_duration=3.0)

    return {
        "speakers": {"unknown": "未分类"},
        "segments": segments,
    }


def classify_speakers_with_llm(
    asr_result: dict,
    teacher_hint: Optional[str] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> dict:
    """用 DeepSeek LLM 对转写片段做说话人角色分类。

    将每个片段分类为 teacher 或 student。
    由于纯文本分类无法区分不同学生，所有学生统一标为 s1/s2/...。

    Args:
        asr_result: transcribe_video() 的输出
        teacher_hint: 老师名字提示（如 "王老师"，帮助 LLM 识别）
        progress_callback: 进度回调

    Returns:
        更新后的 asr_result，speakers 和 segments 中的 speaker 已标记
    """
    from utils.prompts import build_speaker_classify_prompt
    from utils.llm_client import _call_llm

    segments = asr_result.get("segments", [])
    if not segments:
        return asr_result

    if progress_callback:
        progress_callback(f"正在进行说话人分类 ({len(segments)} 个片段)...")

    try:
        messages = build_speaker_classify_prompt(segments, teacher_hint)
        data = _call_llm(messages, temperature=0.1, max_tokens=4096)

        # 提取分类结果
        classifications = data if isinstance(data, list) else data.get("classifications", data.get("results", []))

        # 构建 index → role 映射
        role_map = {}
        for item in classifications:
            if isinstance(item, dict) and "index" in item:
                role_map[int(item["index"])] = item.get("role", "unknown")

        # 应用分类结果
        student_count = 0
        for i, seg in enumerate(segments):
            role = role_map.get(i, "unknown")
            if role == "teacher":
                seg["speaker"] = "teacher"
            elif role == "student":
                student_count += 1
                seg["speaker"] = f"s{student_count}"
            else:
                # 回退：根据文本长度和内容猜测
                text = seg.get("text", "")
                if len(text) > 100 or any(
                    kw in text.lower()
                    for kw in ["excellent", "good morning", "today we", "open your", "homework"]
                ):
                    seg["speaker"] = "teacher"
                else:
                    student_count += 1
                    seg["speaker"] = f"s{student_count}"

        # 重建 speakers 映射
        speakers_map = {}
        for seg in segments:
            spk = seg["speaker"]
            if spk not in speakers_map:
                speakers_map[spk] = spk

        if "teacher" in speakers_map:
            speakers_map["teacher"] = teacher_hint or "老师"

        if progress_callback:
            teacher_segs = sum(1 for s in segments if s["speaker"] == "teacher")
            student_segs = len(segments) - teacher_segs
            progress_callback(
                f"说话人分类完成：老师 {teacher_segs} 段, 学生 {student_segs} 段"
            )

        return {
            "speakers": speakers_map,
            "segments": segments,
        }

    except Exception as e:
        if progress_callback:
            progress_callback(f"说话人分类失败，使用启发式回退：{e}")

        # 回退：纯启发式分类
        return _fallback_speaker_classification(asr_result, teacher_hint)


def transcribe_and_classify(
    video_path: str,
    model_size: str = DEFAULT_MODEL,
    teacher_hint: Optional[str] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> dict:
    """一站式：转写 + 说话人分类。

    这是路径 B 的主入口函数。
    """
    # Step 1: Whisper 转写
    result = transcribe_video(video_path, model_size, progress_callback=progress_callback)

    # Step 2: LLM 分类
    result = classify_speakers_with_llm(result, teacher_hint, progress_callback=progress_callback)

    return result


# ═══════════════════════════════════════════════════════════════
# 启发式回退（LLM 不可用时）
# ═══════════════════════════════════════════════════════════════

def _fallback_speaker_classification(asr_result: dict, teacher_hint: Optional[str] = None) -> dict:
    """纯启发式的说话人分类（不依赖 LLM）。

    规则：
    - 长句（> 80 字符）→ 大概率是老师
    - 含 "excellent", "good morning", "today we", "open your" 等 → 老师
    - 含 "?"、指令语气 → 老师
    - 短回应、朗读内容 → 学生
    """
    segments = asr_result.get("segments", [])
    teacher_keywords = [
        "good morning", "good afternoon", "today we", "let's", "please open",
        "read after", "repeat after", "look at", "open your", "turn to",
        "excellent", "wonderful", "brilliant", "great job", "very good",
        "well done", "who can", "can anyone", "does anyone",
        "homework", "remember", "next time", "see you",
        "大家好", "今天", "请打开", "翻到", "跟我读", "看这里",
        "太棒了", "非常好", "很好", "谁能", "有没有人", "作业",
    ]
    student_keywords = [
        "i think", "i see", "maybe", "teacher,", "excuse me",
        "我觉得", "老师,", "老师，", "我想", "可能",
    ]

    speakers_map = {}
    student_count = 0

    for seg in segments:
        text = seg.get("text", "")
        text_lower = text.lower()

        # 评分
        teacher_score = 0
        student_score = 0

        # 长度信号
        if len(text) > 100:
            teacher_score += 2
        elif len(text) < 20:
            student_score += 2
        else:
            teacher_score += 0.5
            student_score += 0.5

        # 关键词信号
        for kw in teacher_keywords:
            if kw in text_lower:
                teacher_score += 1.5
                break
        for kw in student_keywords:
            if kw in text_lower:
                student_score += 1
                break

        # 问句（老师提问 vs 学生提问）
        if "?" in text or "？" in text:
            if len(text) > 40:
                teacher_score += 1  # 长问句 → 老师提问
            else:
                student_score += 0.5  # 短问句 → 可能是学生

        # 确定角色
        if teacher_score >= student_score:
            seg["speaker"] = "teacher"
            if "teacher" not in speakers_map:
                speakers_map["teacher"] = teacher_hint or "老师"
        else:
            student_count += 1
            seg["speaker"] = f"s{student_count}"
            if seg["speaker"] not in speakers_map:
                speakers_map[seg["speaker"]] = f"学生{student_count}"

    return {
        "speakers": speakers_map,
        "segments": segments,
    }


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def _get_audio_duration(audio_path: str) -> float:
    """获取音频文件时长（秒）。"""
    try:
        from utils.video_processor import find_ffmpeg
        ffmpeg_path = find_ffmpeg()
        if ffmpeg_path:
            import subprocess, sys
            ffprobe = ffmpeg_path.replace("ffmpeg", "ffprobe")
            result = subprocess.run(
                [ffprobe, "-v", "quiet", "-show_format", "-print_format", "json", audio_path],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            if result.returncode == 0:
                import json as _json
                data = _json.loads(result.stdout)
                return float(data.get("format", {}).get("duration", 0))
    except Exception:
        pass
    return 0.0


def _merge_short_segments(segments: list, min_duration: float = 3.0) -> list:
    """合并过短的相邻片段（避免碎片化）。"""
    if not segments:
        return segments

    merged = []
    for seg in segments:
        duration = seg["end"] - seg["start"]
        if merged and duration < min_duration:
            # 合并到前一个片段
            prev = merged[-1]
            # 检查间隔是否合理（不能跨太大间隔）
            gap = seg["start"] - prev["end"]
            if gap < 5.0:  # 间隔不超过 5 秒
                prev["end"] = seg["end"]
                prev["text"] += " " + seg.get("text", "")
                continue
        merged.append(seg.copy())

    return merged


# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("ASR 客户端模块加载正常")
    print(f"默认 Whisper 模型: {DEFAULT_MODEL}")
    print("注意：首次加载 Whisper 模型需要下载（~5GB for medium）")
    print("使用方式：")
    print("  from utils.asr_client import transcribe_video, classify_speakers_with_llm")
    print("  result = transcribe_video('path/to/video.mp4')")
    print("  result = classify_speakers_with_llm(result)")
