"""
视频处理器 — Phase 4 新增。

封装 FFmpeg 操作：音频提取、视频裁剪、高光合集合并。
所有操作通过 subprocess 调用 FFmpeg 二进制，零 Python 依赖。

使用方式：
  from utils.video_processor import extract_audio, clip_segment, merge_clips
"""

import os
import sys
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional


# ═══════════════════════════════════════════════════════════════
# FFmpeg 定位
# ═══════════════════════════════════════════════════════════════

# 已知的 FFmpeg 安装位置（Windows）
_KNOWN_FFMPEG_PATHS = [
    # winget 安装
    lambda: _find_winget_ffmpeg(),
    # 常见手动安装路径
    "C:/ffmpeg/bin/ffmpeg.exe",
    "C:/Program Files/ffmpeg/bin/ffmpeg.exe",
    "C:/Program Files (x86)/ffmpeg/bin/ffmpeg.exe",
    # 用户级路径
    lambda: os.path.expandvars(r"%LOCALAPPDATA%\\Microsoft\\WinGet\\Packages\\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\\ffmpeg-*-full_build\\bin\\ffmpeg.exe"),
    # PATH 中查找
    "ffmpeg",
    "ffmpeg.exe",
]

_cached_ffmpeg_path: Optional[str] = None


def _find_winget_ffmpeg() -> Optional[str]:
    """在 winget 包目录下搜索 FFmpeg。"""
    import glob
    base = os.path.expandvars(
        r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe"
    )
    if os.path.isdir(base):
        candidates = glob.glob(os.path.join(base, "ffmpeg-*-full_build", "bin", "ffmpeg.exe"))
        if candidates:
            return sorted(candidates, reverse=True)[0]
    return None


def find_ffmpeg() -> Optional[str]:
    """查找 FFmpeg 可执行文件路径。"""
    global _cached_ffmpeg_path
    if _cached_ffmpeg_path is not None:
        return _cached_ffmpeg_path if _cached_ffmpeg_path else None

    for candidate in _KNOWN_FFMPEG_PATHS:
        if callable(candidate):
            path = candidate()
        else:
            # shutil.which 也接受字符串
            path = candidate if os.path.isfile(str(candidate)) else shutil.which(str(candidate))

        if path and os.path.isfile(str(path)):
            _cached_ffmpeg_path = str(path)
            return _cached_ffmpeg_path

    return None


_cached_ffmpeg_check = None  # 缓存 check_ffmpeg 结果，避免每次 rerun 都 fork 子进程


def check_ffmpeg() -> tuple[bool, str]:
    """检查 FFmpeg 是否可用（结果缓存，避免重复子进程调用）。

    Returns:
        (available, version_string_or_error)
    """
    global _cached_ffmpeg_check
    if _cached_ffmpeg_check is not None:
        return _cached_ffmpeg_check

    ffmpeg_path = find_ffmpeg()
    if not ffmpeg_path:
        _cached_ffmpeg_check = (False, "FFmpeg 未安装或不在 PATH 中。请运行: winget install ffmpeg")
        return _cached_ffmpeg_check

    try:
        result = subprocess.run(
            [ffmpeg_path, "-version"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        version_line = result.stdout.strip().split("\n")[0] if result.stdout else "unknown"
        _cached_ffmpeg_check = (True, version_line)
        return _cached_ffmpeg_check
    except Exception as e:
        _cached_ffmpeg_check = (False, str(e))
        return _cached_ffmpeg_check


# ═══════════════════════════════════════════════════════════════
# FFmpeg 操作
# ═══════════════════════════════════════════════════════════════

def _run_ffmpeg(args: list[str], description: str = "") -> subprocess.CompletedProcess:
    """运行 FFmpeg 命令，统一错误处理。

    Args:
        args: FFmpeg 参数列表（不含 ffmpeg 本身）
        description: 操作描述（用于错误信息）

    Returns:
        subprocess.CompletedProcess

    Raises:
        RuntimeError: FFmpeg 未找到
        subprocess.CalledProcessError: FFmpeg 执行失败
    """
    ffmpeg_path = find_ffmpeg()
    if not ffmpeg_path:
        raise RuntimeError("FFmpeg 未安装。请运行: winget install ffmpeg")

    cmd = [ffmpeg_path, "-y", "-hide_banner", "-loglevel", "error"] + args

    try:
        return subprocess.run(
            cmd,
            capture_output=True, text=True, timeout=300,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        desc = f" ({description})" if description else ""
        error_msg = e.stderr.strip() if e.stderr else "未知错误"
        raise RuntimeError(f"FFmpeg 操作失败{desc}: {error_msg}") from e


def get_video_info(video_path: str) -> dict:
    """获取视频文件信息。

    Returns:
        {"duration": float, "width": int, "height": int, "fps": float, ...}
    """
    ffmpeg_path = find_ffmpeg()
    if not ffmpeg_path:
        raise RuntimeError("FFmpeg 未安装")

    # 使用 ffprobe（与 ffmpeg 同目录）
    ffprobe_path = ffmpeg_path.replace("ffmpeg", "ffprobe")

    try:
        result = subprocess.run(
            [ffprobe_path, "-v", "quiet", "-print_format", "json",
             "-show_format", "-show_streams", video_path],
            capture_output=True, text=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        # ffprobe 不可用时回退到 ffmpeg
        result = subprocess.run(
            [ffmpeg_path, "-i", video_path],
            capture_output=True, timeout=30,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        stderr = result.stderr.decode("utf-8", errors="replace") if result.stderr else ""
        # 从 stderr 解析 duration + resolution
        import re
        dur_match = re.search(r'Duration:\s*(\d+):(\d+):(\d+)\.(\d+)', stderr)
        duration = 0.0
        if dur_match:
            h, m, s, ms = map(int, dur_match.groups())
            duration = h * 3600 + m * 60 + s + ms / 100.0
        # 解析分辨率: Stream #0:0: Video: ... 2160x1080 ...
        res_match = re.search(r'Video:.*?(\d{2,})x(\d{2,})', stderr)
        width, height = 0, 0
        fps = 0.0
        if res_match:
            width, height = int(res_match.group(1)), int(res_match.group(2))
        # 解析帧率: 30 fps, 29.97 fps
        fps_match = re.search(r'(\d+\.?\d*)\s*fps', stderr)
        if fps_match:
            fps = float(fps_match.group(1))
        return {"duration": duration, "width": width, "height": height, "fps": fps}

    import json
    data = json.loads(result.stdout)

    info = {"duration": 0.0, "width": 0, "height": 0, "fps": 0.0}
    if "format" in data:
        info["duration"] = float(data["format"].get("duration", 0))

    for stream in data.get("streams", []):
        if stream.get("codec_type") == "video":
            info["width"] = stream.get("width", 0)
            info["height"] = stream.get("height", 0)
            fps_str = stream.get("r_frame_rate", "0/1")
            if "/" in fps_str:
                num, den = fps_str.split("/")
                info["fps"] = float(num) / float(den) if float(den) != 0 else 0
            break

    return info


def extract_audio(video_path: str, output_path: Optional[str] = None) -> str:
    """从视频文件中提取音频为 16kHz 单声道 WAV。

    Args:
        video_path: 视频文件路径
        output_path: 输出 WAV 路径（不指定则自动生成临时文件）

    Returns:
        输出 WAV 文件路径
    """
    if output_path is None:
        fd, output_path = tempfile.mkstemp(suffix=".wav", prefix="p4audio_")
        os.close(fd)

    _run_ffmpeg([
        "-i", video_path,
        "-vn",                    # 不要视频
        "-acodec", "pcm_s16le",   # PCM 16-bit
        "-ar", "16000",           # 16kHz 采样率
        "-ac", "1",               # 单声道
        output_path,
    ], "提取音频")

    return output_path


def clip_segment(
    video_path: str,
    start: float,
    end: float,
    output_path: str,
    buffer_seconds: float = 2.0,
    re_encode: bool = False,
) -> str:
    """从视频中裁剪一个片段。

    Args:
        video_path: 源视频路径
        start: 开始时间（秒）
        end: 结束时间（秒）
        output_path: 输出文件路径（.mp4）
        buffer_seconds: 前后缓冲时间（秒），默认 2 秒
        re_encode: 是否重新编码（默认 False，使用 copy 模式更快）

    Returns:
        输出文件路径
    """
    # 确保 start 不早于 0
    clipped_start = max(0.0, start - buffer_seconds)
    duration = end - start + 2 * buffer_seconds

    if re_encode:
        _run_ffmpeg([
            "-ss", str(clipped_start),
            "-i", video_path,
            "-t", str(duration),
            "-c:v", "libx264",
            "-c:a", "aac",
            "-preset", "fast",
            "-crf", "23",
            output_path,
        ], f"裁剪片段 {start:.1f}s-{end:.1f}s (重编码)")
    else:
        # copy 模式：快但可能 seek 不精确
        _run_ffmpeg([
            "-ss", str(clipped_start),
            "-i", video_path,
            "-t", str(duration),
            "-c", "copy",
            "-avoid_negative_ts", "make_zero",
            output_path,
        ], f"裁剪片段 {start:.1f}s-{end:.1f}s")

    return output_path


def merge_clips(
    clip_paths: list[str],
    output_path: str,
    gap_seconds: float = 0.5,
) -> str:
    """合并多个视频片段为一个高光合集，片段间插入黑场过渡。

    Args:
        clip_paths: 片段文件路径列表
        output_path: 输出文件路径（.mp4）
        gap_seconds: 片段间黑场秒数（默认 0.5 秒）

    Returns:
        输出文件路径
    """
    if not clip_paths:
        raise ValueError("片段列表为空")

    if len(clip_paths) == 1:
        shutil.copy2(clip_paths[0], output_path)
        return output_path

    # 从第一个片段读取分辨率，生成匹配的黑场过渡
    try:
        probe = get_video_info(clip_paths[0])
        width = probe.get("width", 0) or 1920
        height = probe.get("height", 0) or 1080
        fps = probe.get("fps", 0) or 30
    except Exception:
        width, height, fps = 1920, 1080, 30  # 获取失败用默认值

    gap_path = os.path.join(tempfile.gettempdir(), f"p4gap_{os.getpid()}.mp4")
    _run_ffmpeg([
        "-f", "lavfi",
        "-i", f"color=black:duration={gap_seconds}:size={width}x{height}:rate={fps}",
        "-f", "lavfi",
        "-i", f"anullsrc=channel_layout=stereo:sample_rate=44100:duration={gap_seconds}",
        "-shortest",
        "-pix_fmt", "yuv420p",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-preset", "ultrafast",
        gap_path,
    ], f"生成 {gap_seconds}s 黑场过渡 ({width}x{height})")

    # 构建交错输入: clip1, gap, clip2, gap, clip3, ..., clipN
    all_inputs = []
    for i, clip_path in enumerate(clip_paths):
        all_inputs.append(clip_path)
        if i < len(clip_paths) - 1:
            all_inputs.append(gap_path)

    # 构建 concat filter graph
    total = len(all_inputs)
    filter_parts = [f"[{i}:v][{i}:a]" for i in range(total)]
    filter_graph = f"{' '.join(filter_parts)}concat=n={total}:v=1:a=1[outv][outa]"

    inputs = []
    for p in all_inputs:
        inputs.extend(["-i", p])

    _run_ffmpeg([
        *inputs,
        "-filter_complex", filter_graph,
        "-map", "[outv]",
        "-map", "[outa]",
        "-c:v", "libx264",
        "-c:a", "aac",
        "-preset", "fast",
        "-crf", "23",
        output_path,
    ], f"合并高光合集（{len(clip_paths)} 段，间隔 {gap_seconds}s）")

    return output_path


def generate_highlight_reel(
    video_path: str,
    highlights: list[dict],
    output_dir: Optional[str] = None,
    buffer_seconds: float = 2.0,
) -> dict:
    """一站式：根据高光片段列表生成剪辑和合集。

    Args:
        video_path: 源视频路径
        highlights: 高光片段列表，每项含 {"id": ..., "start": ..., "end": ...}
        output_dir: 输出目录（不指定则使用临时目录）
        buffer_seconds: 片段前后缓冲时间

    Returns:
        {
            "clips": ["/path/to/clip_1.mp4", ...],
            "reel": "/path/to/highlights.mp4",  # 如果片段数 > 1
            "clip_count": 3,
        }
    """
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="p4highlights_")
    os.makedirs(output_dir, exist_ok=True)

    clip_paths = []
    for h in highlights:
        clip_id = h.get("id", h.get("clip_id", len(clip_paths) + 1))
        clip_path = os.path.join(output_dir, f"clip_{clip_id:02d}.mp4")
        clip_segment(
            video_path,
            h["start"], h["end"],
            clip_path,
            buffer_seconds=buffer_seconds,
        )
        clip_paths.append(clip_path)

    result = {
        "clips": clip_paths,
        "clip_count": len(clip_paths),
    }

    # 生成合辑
    if len(clip_paths) > 1:
        reel_path = os.path.join(output_dir, "highlights_reel.mp4")
        merge_clips(clip_paths, reel_path)
        result["reel"] = reel_path

    return result


def cleanup_temp_files(*paths: str):
    """清理临时文件。"""
    for p in paths:
        try:
            if os.path.isfile(p):
                os.unlink(p)
            elif os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass


# ═══════════════════════════════════════════════════════════════
# 快速测试
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    available, info = check_ffmpeg()
    print(f"FFmpeg 可用: {available}")
    print(f"版本: {info}")

    if available:
        ffmpeg_path = find_ffmpeg()
        print(f"路径: {ffmpeg_path}")
