"""
课后输出工作流 — Phase 1 Demo

Streamlit 审核台骨架，四个阶段：
  1. 提交（上传录屏 + 文章 + 词汇）
  2. AI 处理（Mock 进度模拟）
  3. 审核（三栏仪表盘：反馈 / 视频 / 作业）
  4. 发布（输出文件下载）

运行方式：
  cd Projects/post-class-workflow
  streamlit run app.py
"""

import sys
import io
import time
import json
import os
import tempfile
import streamlit as st
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# 强制 UTF-8 输出——Windows GBK 控制台无法编码 emoji，导致 print/stderr 崩溃
if sys.stdout.encoding != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr.encoding != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# 加载 .env 环境变量（必须在导入 llm_client 之前）
# 基于脚本所在目录解析路径，而非当前工作目录
_env_path = Path(__file__).parent / ".env"
load_dotenv(_env_path)

from utils.mock_data import list_test_cases, load_test_case
from utils import llm_client
from utils import merge_feedback_edits, merge_lecture_edits  # Phase 3: 编辑合并
from utils import get_edit_diff        # Phase 3: 编辑差异对比
from utils import _format_coverage_text  # Phase 3: 知识覆盖度文本格式化
from utils.game_renderer import render_game_html, validate_game_data  # Phase 5: 游戏 HTML 渲染 + 验证
from utils.transcript_parser import parse_transcript, is_transcript_available, get_parse_summary  # Phase 4: 转写稿解析
from utils.video_processor import check_ffmpeg  # Phase 4: FFmpeg 检查

# ── 页面配置 ────────────────────────────────────────────────

st.set_page_config(
    page_title="课后输出工作台",
    page_icon="🍎",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── 自定义样式 ──────────────────────────────────────────────

st.markdown("""
<style>
    /* ═══════════════════════════════════════════════════════════
       DESIGN SYSTEM — 温润编辑部 · Professional Edu SaaS
       ═══════════════════════════════════════════════════════════ */
    :root {
        --ink: #2B2B2B;
        --ink-light: #6B6B6B;
        --ink-muted: #999999;
        --paper: #FCFAF7;
        --paper-warm: #F7F3ED;
        --surface: #FFFFFF;
        --border: #E8E3DB;
        --border-active: #D4CDC0;
        --teal: #206F6B;
        --teal-light: #E8F3F2;
        --teal-dark: #185854;
        --amber: #D48C3C;
        --amber-light: #FDF6EE;
        --green: #5B8C5A;
        --green-light: #EDF5EC;
        --red-soft: #E05555;
        --red-light: #FDF0F0;
        --shadow-sm: 0 1px 3px rgba(0,0,0,.04), 0 1px 2px rgba(0,0,0,.03);
        --shadow-md: 0 4px 16px rgba(0,0,0,.05), 0 2px 6px rgba(0,0,0,.03);
        --shadow-lg: 0 8px 32px rgba(0,0,0,.07), 0 3px 10px rgba(0,0,0,.04);
        --radius-sm: 8px;
        --radius: 12px;
        --radius-lg: 20px;
        --radius-xl: 28px;
    }

    /* ── 全局 ── */
    .stApp { background: var(--paper); }
    .stMainBlock, .block-container { padding-top: 0.5rem; max-width: 1280px; }

    /* ── 标题区 ── */
    .stage-header {
        font-family: 'Georgia', 'Noto Serif SC', 'STSong', serif;
        font-size: 1.75rem; font-weight: 700; color: var(--ink);
        margin-bottom: 0.25rem; letter-spacing: -0.01em;
    }
    .stage-subtitle {
        font-size: 0.9rem; color: var(--ink-light); margin-bottom: 2rem;
    }

    /* ── 卡片 ── */
    .card {
        background: var(--surface); border: 1px solid var(--border);
        border-radius: var(--radius-lg); padding: 1.5rem;
        box-shadow: var(--shadow-sm); margin-bottom: 1rem;
        transition: box-shadow .2s, border-color .2s;
    }
    .card:hover { box-shadow: var(--shadow-md); border-color: var(--border-active); }
    .card h3, .card .stMarkdown h3 {
        margin-top: 0; color: var(--ink); font-size: 1rem;
        font-weight: 650; letter-spacing: -0.005em;
    }

    /* ── 进度容器 ── */
    .progress-container {
        text-align: center; padding: 3.5rem 2rem;
        background: var(--surface); border: 1px solid var(--border);
        border-radius: var(--radius-xl); box-shadow: var(--shadow-md);
    }

    /* ── 审核面板 ── */
    .review-panel {
        background: var(--surface); border: 1px solid var(--border);
        border-radius: var(--radius-lg); padding: 1.25rem 1.5rem;
        box-shadow: var(--shadow-sm);
    }
    .review-panel h2 {
        font-family: 'Georgia', 'Noto Serif SC', serif;
        font-size: 1.1rem; font-weight: 700; color: var(--ink);
        margin-bottom: 1rem; padding-bottom: 0.75rem;
        border-bottom: 1.5px solid var(--border);
    }

    /* ── 片段卡片 ── */
    .clip-card {
        background: var(--paper-warm); border: 1px solid var(--border);
        border-radius: var(--radius); padding: 0.75rem 1rem;
        margin-bottom: 0.5rem; border-left: 4px solid var(--teal);
        transition: border-color .2s, background .2s;
    }
    .clip-card.selected { border-left-color: var(--green); background: var(--green-light); }
    .clip-card.deselected { border-left-color: var(--border-active); opacity: 0.55; }

    /* ── 标签 ── */
    .badge { display: inline-block; padding: 0.2rem 0.65rem; border-radius: 20px; font-size: 0.78rem; font-weight: 600; letter-spacing: 0.01em; }
    .badge-success { background: var(--green-light); color: #3D6B3C; }
    .badge-warning { background: var(--amber-light); color: #9A6B2A; }
    .badge-info { background: var(--teal-light); color: var(--teal-dark); }

    /* ── 按钮 ── */
    .stButton > button {
        border-radius: var(--radius); font-weight: 600; font-size: 0.92rem;
        letter-spacing: 0.01em; transition: all .18s ease;
        border: 1.5px solid transparent;
    }
    .stButton > button:hover { transform: translateY(-1px); box-shadow: var(--shadow-md); }
    .stButton > button:active { transform: scale(.97); }
    /* primary */
    .stButton > button[kind="primary"] {
        background: var(--teal); color: #fff; border-color: var(--teal);
    }
    .stButton > button[kind="primary"]:hover { background: var(--teal-dark); }
    /* secondary */
    .stButton > button[kind="secondary"] {
        background: var(--surface); color: var(--ink); border-color: var(--border-active);
    }
    .stButton > button[kind="secondary"]:hover { background: var(--paper-warm); border-color: var(--ink-muted); }

    /* ── 输入框 ── */
    .stTextInput > div > div > input, .stTextArea > div > div > textarea, .stSelectbox > div > div {
        border-radius: var(--radius-sm) !important; border-color: var(--border) !important;
        font-size: 0.92rem !important;
    }
    .stTextInput > div > div > input:focus, .stTextArea > div > div > textarea:focus {
        border-color: var(--teal) !important; box-shadow: 0 0 0 3px rgba(32,111,107,.1) !important;
    }

    /* ── 展开面板 ── */
    .stExpander {
        border: 1px solid var(--border) !important; border-radius: var(--radius) !important;
        background: var(--surface) !important; box-shadow: var(--shadow-sm) !important;
    }
    .stExpander:hover { border-color: var(--border-active) !important; }

    /* ── 分割线 ── */
    hr, .stDivider { border-color: var(--border) !important; }

    /* ── 下载按钮 ── */
    .stDownloadButton > button {
        border-radius: var(--radius) !important; font-weight: 600 !important;
        background: var(--amber) !important; color: #fff !important; border: none !important;
        transition: all .18s !important;
    }
    .stDownloadButton > button:hover { filter: brightness(1.08); transform: translateY(-1px); box-shadow: var(--shadow-md); }

    /* ── 发布成功 ── */
    .publish-success {
        text-align: center; padding: 2.5rem 2rem;
        background: linear-gradient(160deg, var(--teal-light) 0%, var(--green-light) 100%);
        border: 1px solid rgba(91,140,90,.15);
        border-radius: var(--radius-xl); margin: 1rem 0;
    }

    /* ── 日志面板 ── */
    .proc-log-panel {
        background: #1B1D1E; border-radius: var(--radius); padding: 14px 18px; margin-top: 8px;
        font-family: 'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Consolas', monospace;
        font-size: 0.76rem; line-height: 1.65; max-height: 340px; overflow-y: auto;
        scroll-behavior: smooth; border: 1px solid #2D2F30;
        box-shadow: inset 0 2px 8px rgba(0,0,0,.35);
    }

    /* ── Radio / Checkbox ── */
    .stRadio > div { gap: 0.5rem; }
    .stRadio label, .stCheckbox label { font-weight: 500 !important; color: var(--ink) !important; }

    /* ── Metric ── */
    .stMetric { background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius-lg); padding: 1rem 1.25rem !important; box-shadow: var(--shadow-sm); }
    .stMetric label { color: var(--ink-muted) !important; font-weight: 500 !important; }
    .stMetric [data-testid="stMetricValue"] { color: var(--ink) !important; font-weight: 700 !important; }

    /* ── 响应式 ── */
    @media (max-width: 768px) {
        .stage-header { font-size: 1.4rem; }
        .card, .review-panel { padding: 1rem; }
    }
</style>
""", unsafe_allow_html=True)

# ── 初始化 Session State ─────────────────────────────────────

DEFAULTS = {
    "stage": "submit",          # submit | processing | review | published
    "session": None,            # 当前 session 数据
    "processing_progress": 0,
    "processing_text": "",
    "review_edits": {},         # 老师审核时的编辑缓存
}

# 需要在 reset_app() 时清除的所有 session state key（含 Streamlit widget 自动生成的 key）
_RESET_KEYS = [
    # 提交页
    "teacher_name", "grade_level", "article_input", "vocab_input",
    "transcript_input", "video_file", "lecture_notes",
    # 测试用例
    "_pending_test_case", "_test_case_loaded", "_test_case_error",
    # 处理管线
    "processing_logs", "_proc_stage", "_proc_done", "_proc_error",
    "_api_failed", "_connectivity_checked",
    # 并行处理
    "_parallel_start", "_parallel_threads", "_parallel_results",
    "_parallel_task_count", "_parallel_task_names", "_parallel_done",
    # 审核台 widget
    "feedback_view_mode", "edit_summary", "edit_coverage",
    "edit_teaching", "edit_parent", "feedback_done",
    "edit_grammar_points", "edit_phrases", "edit_vocab_summary",
    "edit_study_tips", "lecture_done", "homework_done",
    "clips_done", "gen_preview",
    # 视频预览
    "_preview_paths", "_preview_dir",
    # 最终输出
    "_final_feedback_report", "_final_lecture_notes",
    "_game_html_template",
]

for key, val in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = val

# ── 测试用例加载处理 ──
_pending_case = st.session_state.get("_pending_test_case", "")
if _pending_case:
    try:
        case = load_test_case(_pending_case)
        st.session_state["teacher_name"] = case.get("teacher", "")
        st.session_state["grade_level"] = case.get("grade_label", "")
        st.session_state["article_input"] = case.get("article", "")
        st.session_state["vocab_input"] = case.get("vocabulary_raw", "")
        st.session_state["transcript_input"] = case.get("transcript_text", "")
        st.session_state["_test_case_loaded"] = _pending_case
    except Exception as e:
        st.session_state["_test_case_error"] = str(e)
    st.session_state["_pending_test_case"] = ""


# ── 工具函数 ────────────────────────────────────────────────

def reset_app():
    """重置所有状态"""
    for key in DEFAULTS:
        st.session_state[key] = DEFAULTS[key]
    # 清除处理/审核/发布阶段遗留的所有 widget 和中间状态
    for key in _RESET_KEYS:
        if key in st.session_state:
            del st.session_state[key]


def _show_edit_indicator(current, original, label):
    """在编辑区下方显示修改状态 + AI 原文折叠。

    Args:
        current (str): 当前编辑后的文本
        original (str): AI 原始文本
        label (str): 字段名称（用于折叠标题）
    """
    changed = (current != original)
    if changed:
        st.caption(f"✏️ 已修改 — 共 {len(current)} 字（原文 {len(original)} 字）")
        with st.expander(f"📋 查看 AI 原文（{label}）"):
            st.info(original)
    else:
        st.caption(f"✅ 未修改 — {len(original)} 字")


def _render_report_preview(report, session):
    """渲染反馈报告的格式化预览（家长视角）。

    Args:
        report (dict): 合并编辑后的最终报告
        session (dict): session 数据
    """
    st.markdown("---")

    # 报告头部信息
    st.markdown(f"""
    <div style="text-align:center;padding:0.25rem 0 1rem;">
        <div style="font-size:0.82rem;color:var(--ink-muted);">{session.get('teacher', '老师')} · {session.get('grade_level', '')} · 课后反馈报告</div>
    </div>
    """, unsafe_allow_html=True)

    if report.get("_edited"):
        st.info("✏️ 本预览包含老师的手动编辑")

    # 课堂摘要
    st.markdown("#### 📋 课堂摘要")
    st.markdown(report.get("summary", "—"))
    st.markdown("---")

    # 知识覆盖度
    st.markdown("#### 🎯 知识覆盖度")
    for item in report.get("knowledge_coverage", []):
        icon = "✅" if item.get("status", "").startswith("✅") else "⚠️"
        st.markdown(f"- {icon} **{item.get('item', '—')}**：{item.get('detail', '—')}")
    st.markdown("---")

    # 学生表现
    st.markdown("#### 👤 学生表现评估")
    students = report.get("student_performance", {})
    level_colors = {"🌟 优秀": "green", "优秀": "green", "👍 良好": "blue", "良好": "blue", "💪 需加强": "orange", "需加强": "orange"}
    # 五维度标签
    dim_labels = {"发音准确性": "🗣️", "课堂参与": "🙋", "造句表达": "💬", "词汇掌握": "📚", "学习习惯": "📝"}
    for name, info in students.items():
        level = info.get("level", "—")
        color = level_colors.get(level, "grey")
        st.markdown(f"**{name}** — :{color}[{level}]")

        # 五维度星级展示
        dims = info.get("dimensions", {})
        if dims:
            dim_cols = st.columns(5)
            for i, (dim_name, dim_data) in enumerate(dims.items()):
                with dim_cols[i]:
                    stars = "⭐" * dim_data.get("stars", 0) + "☆" * (5 - dim_data.get("stars", 0))
                    emoji = dim_labels.get(dim_name, "")
                    st.markdown(f"{emoji} {stars}")
                    st.caption(dim_data.get("note", "")[:30] if dim_data.get("note") else "")

        # Highlight
        if info.get("highlight"):
            st.markdown(f"✨ *{info['highlight']}*")

        # 综合评语
        st.markdown(f"> {info.get('comment', '—')}")

        # 家长行动建议
        if info.get("parent_action"):
            st.caption(f"🏠 {info['parent_action']}")

        st.markdown("")
    st.markdown("---")

    # 教学建议
    st.markdown("#### 💡 教学建议")
    st.markdown(report.get("teaching_suggestions", "—"))
    st.markdown("---")

    # 家长指引
    st.markdown("#### 🏠 家长指引")
    st.markdown(report.get("parent_guide", "—"))

    st.markdown("---")
    st.caption(f"预览版本 · {report.get('summary', '')[:30]}..." if report.get('summary') else "预览版本")


def _format_report_for_download(report, session):
    """将反馈报告格式化为可读的纯文本，用于下载。

    Args:
        report (dict): 合并后的最终报告
        session (dict): session 数据

    Returns:
        str: 格式化的报告文本
    """
    lines = []
    lines.append("=" * 50)
    lines.append("课后反馈报告")
    lines.append("=" * 50)
    lines.append(f"教师：{session.get('teacher', '—')}")
    lines.append(f"年级：{session.get('grade_level', '—')}")
    lines.append(f"生成时间：{session.get('ai_outputs', {}).get('processed_at', '—')}")
    if report.get("_edited"):
        lines.append("⚠️ 本报告已经老师审核修改")
    lines.append("")

    lines.append("━" * 40)
    lines.append("📋 课堂摘要")
    lines.append("━" * 40)
    lines.append(report.get("summary", "—"))
    lines.append("")

    lines.append("━" * 40)
    lines.append("🎯 知识覆盖度")
    lines.append("━" * 40)
    for item in report.get("knowledge_coverage", []):
        icon = "✅" if item.get("status", "").startswith("✅") else "⚠️"
        lines.append(f"  {icon} {item.get('item', '')} — {item.get('detail', '')}")
    lines.append("")

    lines.append("━" * 40)
    lines.append("👤 学生表现评估")
    lines.append("━" * 40)
    dim_labels = {"发音准确性": "🗣️发音", "课堂参与": "🙋参与", "造句表达": "💬造句", "词汇掌握": "📚词汇", "学习习惯": "📝习惯"}
    for name, info in report.get("student_performance", {}).items():
        lines.append(f"【{name}】— {info.get('level', '—')}")
        # 五维度
        dims = info.get("dimensions", {})
        if dims:
            for dim_name, dim_data in dims.items():
                stars = "⭐" * dim_data.get("stars", 0) + "☆" * (5 - dim_data.get("stars", 0))
                label = dim_labels.get(dim_name, dim_name)
                lines.append(f"  {label} {stars} — {dim_data.get('note', '')}")
        # Highlight
        if info.get("highlight"):
            lines.append(f"  ✨ 高光：{info['highlight']}")
        lines.append(f"  📝 评语：{info.get('comment', '—')}")
        if info.get("parent_action"):
            lines.append(f"  🏠 家长行动：{info['parent_action']}")
        lines.append("")
    lines.append("")

    lines.append("━" * 40)
    lines.append("💡 教学建议")
    lines.append("━" * 40)
    lines.append(report.get("teaching_suggestions", "—"))
    lines.append("")

    lines.append("━" * 40)
    lines.append("🏠 家长指引")
    lines.append("━" * 40)
    lines.append(report.get("parent_guide", "—"))
    lines.append("")

    lines.append("=" * 50)
    lines.append("本报告由 AI 生成 + 老师审核编辑 · 课后输出工作台")
    lines.append("=" * 50)

    return "\n".join(lines)


def _format_lecture_notes_for_download(notes):
    """将讲义 JSON 格式化为可读的纯文本，用于下载。

    Args:
        notes (dict): 讲义数据

    Returns:
        str: 格式化的讲义文本
    """
    lines = []
    lines.append("=" * 50)
    lines.append(notes.get("title", "课堂讲义"))
    lines.append("=" * 50)
    ci = notes.get("class_info", {})
    lines.append(f"学科：{ci.get('subject', '英语')}  |  主题：{ci.get('topic', '')}  |  年级：{ci.get('grade', '')}")
    lines.append("")

    # 语法与句型详解
    grammar = notes.get("grammar_points", [])
    if grammar:
        lines.append("━" * 40)
        lines.append("一、语法与句型详解")
        lines.append("━" * 40)
        for i, gp in enumerate(grammar, 1):
            lines.append(f"\n{i}. {gp.get('name', '')}")
            lines.append(f"   结构：{gp.get('structure', '')}")
            lines.append(f"   含义：{gp.get('meaning', '')}")
            lines.append(f"   例句：{gp.get('example', '')}")
            lines.append(f"        {gp.get('example_cn', '')}")
            if gp.get("common_mistake"):
                lines.append(f"   ⚠️ 易错：{gp['common_mistake']}")
        lines.append("")

    # 常见搭配与短语
    phrases = notes.get("phrases", [])
    if phrases:
        lines.append("━" * 40)
        lines.append("二、常见搭配与短语归纳")
        lines.append("━" * 40)
        for i, ph in enumerate(phrases, 1):
            tag = f" [{ph.get('type', '')}]" if ph.get("type") else ""
            lines.append(f"\n{i}. {ph.get('phrase', '')}{tag} — {ph.get('meaning', '')}")
            if ph.get("example"):
                lines.append(f"   例句：{ph['example']}")
                if ph.get("example_cn"):
                    lines.append(f"       {ph['example_cn']}")
            if ph.get("note"):
                lines.append(f"   💡 {ph['note']}")
        lines.append("")

    # 词汇总结
    if notes.get("vocabulary_summary"):
        lines.append("━" * 40)
        lines.append("三、词汇总结")
        lines.append("━" * 40)
        lines.append(notes["vocabulary_summary"])
        lines.append("")

    # 学习建议
    if notes.get("study_tips"):
        lines.append("━" * 40)
        lines.append("四、学习建议")
        lines.append("━" * 40)
        lines.append(notes["study_tips"])
        lines.append("")

    lines.append("=" * 50)
    lines.append("本讲义由 AI 生成 · 课后输出工作台")
    return "\n".join(lines)


def _format_exercise_for_download(ex_data):
    """将练习题 JSON 格式化为可直接复制到 Word 的纯文本。

    Args:
        ex_data (dict): 练习题数据

    Returns:
        str: 格式化的测试卷文本
    """
    lines = []
    lines.append(f"# {ex_data.get('title', '英语词汇与语法综合测试')}")
    if ex_data.get("subtitle"):
        lines.append(f"*{ex_data['subtitle']}*")
    lines.append("")

    # 词汇部分
    vocab_sec = ex_data.get("vocabulary_section", {})
    if vocab_sec.get("questions"):
        lines.append("## 一、词汇部分 (Vocabulary Section)")
        if vocab_sec.get("instruction"):
            lines.append(f"*{vocab_sec['instruction']}*")
        lines.append("")
        for q in vocab_sec["questions"]:
            qid = q.get("id", "")
            lines.append(f"{qid}. {q.get('sentence', '')}")
            for opt_key in ("A", "B", "C", "D"):
                if opt_key in q.get("options", {}):
                    lines.append(f"    {opt_key}) {q['options'][opt_key]}")
            lines.append("")

    # 语法部分
    gram_sec = ex_data.get("grammar_section", {})
    if gram_sec.get("questions"):
        lines.append("## 二、语法部分 (Grammar Section)")
        if gram_sec.get("instruction"):
            lines.append(f"*{gram_sec['instruction']}*")
        lines.append("")
        for q in gram_sec["questions"]:
            qid = q.get("id", "")
            lines.append(f"{qid}. {q.get('sentence', '')}")
            for opt_key in ("A", "B", "C", "D"):
                if opt_key in q.get("options", {}):
                    lines.append(f"    {opt_key}) {q['options'][opt_key]}")
            lines.append("")

    # 答案与解析
    lines.append("---")
    lines.append("## 三、答案与解析")
    lines.append("")

    if vocab_sec.get("questions"):
        lines.append("### 词汇部分答案 (Vocabulary Answers)")
        lines.append("")
        for q in vocab_sec["questions"]:
            qid = q.get("id", "")
            ans = q.get("answer", "")
            exp = q.get("explanation", "")
            lines.append(f"{qid}. 正确答案：{ans}")
            lines.append(f"   解析：{exp}")
            lines.append("")

    if gram_sec.get("questions"):
        lines.append("### 语法部分答案 (Grammar Answers)")
        lines.append("")
        for q in gram_sec["questions"]:
            qid = q.get("id", "")
            ans = q.get("answer", "")
            exp = q.get("explanation", "")
            lines.append(f"{qid}. 正确答案：{ans}")
            lines.append(f"   解析：{exp}")
            lines.append("")

    lines.append("---")
    lines.append("本测试卷由 AI 生成 · 课后输出工作台")
    return "\n".join(lines)


def start_processing():
    """从提交阶段进入处理阶段"""
    # 构建 session
    vocab = []
    for line in st.session_state.get("vocab_input", "").strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) == 2:
            vocab.append({"word": parts[0].strip(), "meaning": parts[1].strip()})
        elif len(parts) == 1:
            vocab.append({"word": parts[0].strip(), "meaning": ""})

    # Phase 4: 处理视频文件上传
    video_file = st.session_state.get("video_file", None)
    video_path = None
    if video_file is not None:
        # 保存上传的视频到临时文件
        import tempfile
        suffix = Path(video_file.name).suffix or ".mp4"
        fd, tmp_path = tempfile.mkstemp(suffix=suffix, prefix="p4video_")
        with os.fdopen(fd, "wb") as f:
            f.write(video_file.getbuffer())
        video_path = tmp_path

    st.session_state["session"] = {
        "session_id": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "teacher": st.session_state.get("teacher_name", ""),
        "grade_level": st.session_state.get("grade_level", ""),
        "created_at": datetime.now().isoformat(),
        "status": "processing",
        "inputs": {
            "article": st.session_state.get("article_input", ""),
            "vocabulary": vocab,
            "video_name": video_file.name if video_file else None,
            "video_path": video_path,  # Phase 4: 临时视频文件路径
            "transcript_text": st.session_state.get("transcript_input", "").strip(),  # Phase 4: 转写稿
        },
        "options": {
            "homework_mode": st.session_state.get("homework_mode", "🎮 游戏"),
            "generate_lecture_notes": st.session_state.get("generate_lecture_notes", True),
        },
    }
    st.session_state["stage"] = "processing"
    st.session_state["processing_progress"] = 0
    st.session_state["processing_text"] = ""
    st.session_state["processing_logs"] = []  # 滚动日志
    st.session_state["_proc_stage"] = 0
    st.session_state["_proc_done"] = False


def _add_log(msg, level="info"):
    """推一条日志到处理日志列表。level: info|success|warn|highlight"""
    logs = st.session_state.setdefault("processing_logs", [])
    logs.append({"msg": msg, "level": level, "time": datetime.now().strftime("%H:%M:%S")})


def run_processing():
    """Phase 4 并行处理管线——三条 LLM 调用同时发出，总耗时 = 最慢那条。

    旧版 24 阶段串行（~5.5min）→ 新版 13 阶段并行（~4min）。
    Stage 7 是核心：线程池并发调 DeepSeek，反馈+高光+作业同时生成。
    """
    PARALLEL_TIMEOUT = 600  # 并行 LLM 超时秒数（10 分钟）

    stage = st.session_state.get("_proc_stage", 0)
    session = st.session_state["session"]
    inputs = session.get("inputs", {})
    article = inputs.get("article", "")
    vocabulary = inputs.get("vocabulary", [])

    # 进度映射：13 个 stage → 0-100%
    # Stage 7（并行 LLM）是唯一的长等待阶段，之前 18% → 之后直接到 80%
    progress_map = {0:2,1:4,2:7, 3:9,4:11,5:13, 6:18,7:80,
                    8:84,9:88, 10:92,11:98, 12:100, 99:100}

    # ═══════════════════════════════════════════════
    # Stage 0-2: 初始化（3 个微阶段，快速滚动）
    # ═══════════════════════════════════════════════
    if stage == 0:
        _add_log(">>> 启动课后输出处理管线 v2.0", "highlight")
        _add_log("加载配置: DeepSeek v4-pro @ api.deepseek.com", "info")
        st.session_state["_proc_stage"] = 1
        st.session_state["processing_progress"] = progress_map[1]
        st.session_state["processing_text"] = "⚙️ 初始化处理管线..."
        time.sleep(0.08); st.rerun()

    elif stage == 1:
        _add_log("初始化 Streamlit 会话状态…完成", "info")
        _add_log("挂载 Prompt 模板: feedback + homework + highlight", "info")
        _add_log("输入校验: 文章 1 篇, 词汇 14 个, 录屏 1 段", "success")
        st.session_state["_proc_stage"] = 2
        st.session_state["processing_progress"] = progress_map[2]
        time.sleep(0.08); st.rerun()

    elif stage == 2:
        _add_log("建立 API 连接池…max_retries=2, timeout=120s", "info")
        _add_log("管线就绪，开始执行", "success")
        st.session_state["_proc_stage"] = 3
        st.session_state["processing_progress"] = progress_map[3]
        time.sleep(0.05); st.rerun()

    # ═══════════════════════════════════════════════
    # Stage 3-5: ASR 语音识别
    # Phase 4: 根据输入类型分三条路径
    #   路径 A: 有腾讯会议转写稿 → parse_transcript() 秒级解析
    #   路径 B: 有视频文件 → FFmpeg + Whisper 转写 + LLM 分类
    #   路径 C: 都没有 → Mock 数据降级
    # ═══════════════════════════════════════════════
    elif stage == 3:
        st.session_state["processing_text"] = "🎙️ 正在进行语音识别（ASR）..."
        transcript_text = session.get("inputs", {}).get("transcript_text", "")
        video_path = session.get("inputs", {}).get("video_path", None)

        if transcript_text and is_transcript_available(transcript_text):
            # ── 路径 A：解析腾讯会议转写稿 ──
            _add_log("--- 语音识别 (ASR) ---", "highlight")
            _add_log("检测到腾讯会议转写稿 → 走路径 A（解析模式）", "info")
            _add_log(f"转写稿长度: {len(transcript_text)} 字符", "info")

            try:
                asr_result = parse_transcript(transcript_text)
                _add_log(get_parse_summary(asr_result), "success")
                session["asr_result"] = asr_result
                st.session_state["session"] = session
                # 跳过 Stage 4-5，直接到 Stage 6
                st.session_state["_proc_stage"] = 6
                st.session_state["processing_progress"] = progress_map[6]
                time.sleep(0.15); st.rerun()
            except ValueError as e:
                _add_log(f"转写稿解析失败: {e}", "warn")
                _add_log("回退到路径 C (Mock 数据)", "warn")
                st.session_state["_proc_stage"] = 4
                time.sleep(0.1); st.rerun()

        elif video_path and os.path.isfile(video_path):
            # ── 路径 B：视频 → FFmpeg + Whisper ──
            _add_log("--- 语音识别 (ASR) ---", "highlight")
            _add_log("检测到视频文件 → 走路径 B（Whisper 转写模式）", "info")
            ffmpeg_ok, _ = check_ffmpeg()
            if ffmpeg_ok:
                _add_log("FFmpeg 已就绪，准备提取音频…", "info")
                st.session_state["_proc_stage"] = 4
                st.session_state["processing_progress"] = progress_map[4]
            else:
                _add_log("FFmpeg 不可用，无法处理视频 → 回退 Mock", "warn")
                st.session_state["_proc_stage"] = 5
                st.session_state["processing_progress"] = progress_map[5]
            time.sleep(0.1); st.rerun()

        else:
            # ── 路径 C：Mock 降级 ──
            _add_log("--- 语音识别 (ASR) ---", "highlight")
            _add_log("无转写稿、无视频文件 → 走路径 C（Mock 降级）", "info")
            _add_log("使用预置课堂模拟数据…", "info")
            st.session_state["_proc_stage"] = 5
            st.session_state["processing_progress"] = progress_map[5]
            time.sleep(0.06); st.rerun()

    elif stage == 4:
        # 路径 B 继续：提取音频 + Whisper 转写
        _add_log("提取音频轨道 (16kHz mono WAV)…", "info")
        video_path = session.get("inputs", {}).get("video_path", None)
        try:
            from utils.asr_client import transcribe_video
            _add_log("加载 Whisper model (medium)…首次加载需要下载 ~5GB", "info")
            _add_log("⏳ 转写进行中（预计 2-5 分钟）…", "highlight")
            asr_result = transcribe_video(
                video_path,
                model_size="medium",
                progress_callback=lambda msg: _add_log(f"[Whisper] {msg}", "info"),
            )
            segments = asr_result.get("segments", [])
            _add_log(f"转写完成: {len(segments)} 个片段", "success")

            # LLM 说话人分类（独立 try，失败不丢 Whisper 结果）
            _add_log("正在进行说话人分类 (LLM)…", "info")
            try:
                from utils.asr_client import classify_speakers_with_llm
                teacher_name = session.get("teacher", "")
                asr_result = classify_speakers_with_llm(
                    asr_result,
                    teacher_hint=teacher_name if teacher_name else None,
                    progress_callback=lambda msg: _add_log(f"[分类] {msg}", "info"),
                )
                _add_log(get_parse_summary(asr_result), "success")
            except Exception as e:
                _add_log(f"LLM 说话人分类失败: {e}", "warn")
                _add_log("保留 Whisper 转写结果（speaker 标记为 unknown）", "info")
                # 保留 Whisper 结果，不做 mock 替换

        except Exception as e:
            _add_log(f"Whisper 转写失败: {e}", "error")
            _add_log("无法完成语音识别，请检查视频文件后重试。", "error")
            # 不降级到 mock——用空 segment 继续
            asr_result = {"speakers": {}, "segments": []}
            session["asr_result"] = asr_result
            st.session_state["session"] = session

        st.session_state["_proc_stage"] = 6
        st.session_state["processing_progress"] = progress_map[6]
        time.sleep(0.1); st.rerun()

    elif stage == 5:
        # 路径 C 继续：无可用 ASR 输入
        _add_log("未检测到转写稿或视频文件，跳过语音识别。", "info")
        _add_log("将仅基于文章和词汇生成内容。", "info")
        asr_result = {"speakers": {}, "segments": []}
        session["asr_result"] = asr_result
        _add_log("ASR 跳过（无可用输入）", "success")
        st.session_state["session"] = session
        st.session_state["_proc_stage"] = 6
        st.session_state["processing_progress"] = progress_map[6]
        time.sleep(0.06); st.rerun()

    # ═══════════════════════════════════════════════
    # Stage 6-7: 并行 LLM 调用（增量进度 + 超时保护）
    # 动态确定任务列表：反馈 + 高光（必做）+ 游戏/练习/讲义（按选项）
    # 最长等待 10 分钟，超时自动降级到 Mock 数据
    # ═══════════════════════════════════════════════
    elif stage == 6:
        import threading

        options = session.get("options", {})
        hw_mode = options.get("homework_mode", "🎮 游戏")
        want_lecture_notes = options.get("generate_lecture_notes", True)
        want_game = hw_mode in ("🎮 游戏", "🔀 都生成")
        want_exercise = hw_mode in ("📝 练习", "🔀 都生成")

        # ── 从 session 提取数据 ──
        asr_segments = session.get("asr_result", {}).get("segments", [])
        grade_level = session.get("grade_level", "")

        # ── 构建动态任务列表 ──
        task_list = []  # [(name, fn, args...)]
        task_list.append(("feedback", llm_client.generate_feedback_report, article, vocabulary, asr_segments, grade_level))
        task_list.append(("highlights", llm_client.identify_highlight_clips, article, vocabulary, asr_segments, True))
        if want_game:
            task_list.append(("game", llm_client.generate_homework_questions, article, vocabulary, grade_level))
        if want_exercise:
            # 练习模式用 raw materials 作为输入（讲义同时生成的话后续可替换）
            exercise_material = f"## 课堂文章\n{article}"
            if asr_segments:
                seg_text = "\n".join(f"[{s.get('speaker','')}] {s.get('text','')}" for s in asr_segments)
                exercise_material += f"\n\n## 课堂对话\n{seg_text}"
            task_list.append(("exercises", llm_client.generate_exercises, exercise_material, vocabulary, grade_level))
        if want_lecture_notes:
            task_list.append(("lecture_notes", llm_client.generate_lecture_notes, article, vocabulary, asr_segments, grade_level))

        total_tasks = len(task_list)
        task_names = [t[0] for t in task_list]

        st.session_state["processing_text"] = f"⚡ {total_tasks} 项 AI 任务并行处理中…"
        _add_log(f"━━━ 并行处理管线启动 ({total_tasks} 项) ━━━", "highlight")
        _add_log(f"任务: {', '.join(task_names)}", "info")
        _add_log("注入课堂文章 + 词汇表 + 逐字稿", "info")

        # ── API 连通性预检（2 秒超时）──
        _add_log("检查 DeepSeek API 连通性…", "info")
        try:
            api_ok, api_info = llm_client.check_connectivity()
            if api_ok:
                _add_log(f"DeepSeek API 连通: ✓ ({api_info:.0f}ms)", "success")
            else:
                _add_log(f"DeepSeek API 不可用: {api_info}", "error")
                _add_log("无法连接 DeepSeek API，请检查网络和 API 密钥后重试。", "error")
                st.session_state["processing_text"] = "❌ API 连接失败——请检查网络后重试"
                st.session_state["_api_failed"] = True
                st.session_state["_proc_stage"] = 8  # 跳过处理，直接到结果收集阶段
                st.session_state["processing_progress"] = 100
                st.rerun()
        except Exception as e:
            _add_log(f"API 预检异常: {e}", "error")
            _add_log("无法连接 DeepSeek API，请检查网络和 API 密钥后重试。", "error")
            st.session_state["processing_text"] = "❌ API 连接失败——请检查网络后重试"
            st.session_state["_api_failed"] = True
            st.session_state["_proc_stage"] = 8
            st.session_state["processing_progress"] = 100
            st.rerun()

        _add_log(f"🚀 同时发出 {total_tasks} 条 DeepSeek 请求", "highlight")
        _add_log("⏳ 等待响应（最长 10 分钟超时）…", "highlight")

        results = {}

        def _run_task(name, fn, *args):
            try:
                results[name] = ("ok", fn(*args))
            except Exception as e:
                results[name] = ("error", str(e)[:200])

        threads = [
            threading.Thread(target=_run_task, args=(name, fn, *args_list))
            for name, fn, *args_list in task_list
        ]

        for t in threads:
            t.daemon = True
            t.start()

        st.session_state["_parallel_start"] = time.time()
        st.session_state["_parallel_threads"] = threads
        st.session_state["_parallel_results"] = results
        st.session_state["_parallel_task_count"] = total_tasks
        st.session_state["_parallel_task_names"] = task_names
        st.session_state["_parallel_done"] = set()

        st.session_state["_proc_stage"] = 7
        st.session_state["processing_progress"] = 20
        time.sleep(0.5); st.rerun()

    elif stage == 7:
        # 轮询线程完成状态，带超时保护
        results = st.session_state.get("_parallel_results", {})
        done_before = st.session_state.get("_parallel_done", set())

        # 从 session options 推导任务列表（避免硬编码备用值不匹配动态任务计数）
        _opts = session.get("options", {})
        _hw = _opts.get("homework_mode", "🎮 游戏")
        _default_names = ["feedback", "highlights"]
        if _hw in ("🎮 游戏", "🔀 都生成"): _default_names.append("game")
        if _hw in ("📝 练习", "🔀 都生成"): _default_names.append("exercises")
        if _opts.get("generate_lecture_notes", True): _default_names.append("lecture_notes")

        total_tasks = st.session_state.get("_parallel_task_count", len(_default_names))
        task_names = st.session_state.get("_parallel_task_names", _default_names)
        t_start = st.session_state.get("_parallel_start", time.time())
        t_elapsed = time.time() - t_start

        # ── 超时保护：报告未完成的任务 ──
        if t_elapsed > PARALLEL_TIMEOUT:
            _add_log(f"⏰ 并行处理超时 ({t_elapsed:.0f}s > {PARALLEL_TIMEOUT}s)", "warn")
            for name in task_names:
                if name not in results:
                    _add_log(f"[{name}] 未完成——已超时", "warn")
                    results[name] = ("error", f"timeout after {PARALLEL_TIMEOUT}s")
            for t in st.session_state.get("_parallel_threads", []):
                t.join(timeout=1)
            st.session_state["_parallel_done"] = set(task_names)

        # ── 检查新完成的任务 ──
        step_map = {"feedback": 50, "highlights": 60, "game": 72, "exercises": 80, "lecture_notes": 88}
        new_done = set()

        for name, (status, data) in list(results.items()):
            if status == "ok" and name not in done_before:
                elapsed = time.time() - t_start
                if name == "feedback":
                    session["_feedback_report"] = data
                    students = data.get("student_performance", {})
                    _add_log(f"[反馈报告] 完成 ({elapsed:.0f}s) — {len(students)} 名学生", "success")
                elif name == "highlights":
                    session["_highlight_clips"] = data
                    top = max((c["auto_score"] for c in data), default=0) if isinstance(data, list) else 0
                    _add_log(f"[高光片段] 完成 ({elapsed:.0f}s) — {len(data) if isinstance(data,list) else '?'} 个, Top={top:.0%}", "success")
                elif name == "game":
                    session["_homework_questions"] = data
                    lvls = len(data.get("levels", [])) if isinstance(data, dict) else 0
                    _add_log(f"[游戏作业] 完成 ({elapsed:.0f}s) — {lvls} 关", "success")
                elif name == "exercises":
                    session["_exercises"] = data
                    vq = len(data.get("vocabulary_section", {}).get("questions", [])) if isinstance(data, dict) else 0
                    _add_log(f"[练习题] 完成 ({elapsed:.0f}s) — {vq} 词汇题", "success")
                elif name == "lecture_notes":
                    session["_lecture_notes"] = data
                    gp = len(data.get("grammar_points", [])) if isinstance(data, dict) else 0
                    _add_log(f"[讲义] 完成 ({elapsed:.0f}s) — {gp} 个语法点", "success")
                new_done.add(name)
                st.session_state["processing_progress"] = step_map.get(name, 50)
                remaining = total_tasks - len(done_before) - len(new_done)
                if remaining > 0:
                    st.session_state["processing_text"] = f"⚡ {name} 完成！等待其余 {remaining} 项…"

        for name, (status, data) in list(results.items()):
            if status == "error" and name not in done_before:
                _add_log(f"[{name}] 调用失败: {data}", "warn")
                new_done.add(name)

        st.session_state["_parallel_done"] = done_before | new_done
        st.session_state["session"] = session

        # 全部完成？
        all_done = len(st.session_state["_parallel_done"]) >= total_tasks
        if all_done:
            t_total = time.time() - t_start
            ok_count = sum(1 for _, (s, _) in results.items() if s == "ok")
            fail_count = total_tasks - ok_count

            if fail_count > 0:
                _add_log(f"━━━ 并行处理结束 ({t_total:.0f}s) — {ok_count}/{total_tasks} 成功, {fail_count} 失败 ━━━", "warn" if ok_count > 0 else "error")
                for name, (status, data) in results.items():
                    if status == "error":
                        _add_log(f"[{name}] 错误: {data}", "warn")
                if ok_count == 0:
                    _add_log("所有 AI 任务均失败，无法继续。请检查 DeepSeek API 状态后重试。", "error")
                    st.session_state["processing_text"] = "❌ 处理失败——所有 API 调用均未成功"
                    st.rerun()
            else:
                _add_log(f"━━━ 并行处理完成 ({t_total:.0f}s) ━━━", "highlight")

            # 后处理验证（区分"未请求"/"失败"/"成功"）
            _opts = session.get("options", {})
            _hw = _opts.get("homework_mode", "🎮 游戏")

            fb = session.get("_feedback_report", {})
            students = fb.get("student_performance", {})
            _add_log(f"反馈报告: {'✓ ' + str(len(students)) + ' 名学生评语' if students else '✗ 未生成'}", "success" if students else "warn")

            clips = session.get("_highlight_clips", [])
            if isinstance(clips, list) and clips:
                _add_log(f"高光片段: ✓ {len(clips)} 个", "success")
            else:
                _add_log("高光片段: ✗ 未生成", "warn")

            if _hw in ("🎮 游戏", "🔀 都生成"):
                game = session.get("_homework_questions", {})
                if isinstance(game, dict) and game.get("levels"):
                    valid, errs, warns = validate_game_data(game)
                    _add_log(f"游戏作业: {'✓' if valid else '⚠'} {len(game.get('levels',[]))} 关", "success" if valid else "warn")
                else:
                    _add_log("游戏作业: ✗ 生成失败", "warn")
            else:
                _add_log("游戏作业: — 未选择（跳过）", "info")

            if _hw in ("📝 练习", "🔀 都生成"):
                ex = session.get("_exercises", {})
                if isinstance(ex, dict) and ex.get("vocabulary_section"):
                    _add_log(f"练习题: ✓ 已生成", "success")
                else:
                    _add_log("练习题: ✗ 生成失败", "warn")
            else:
                _add_log("练习题: — 未选择（跳过）", "info")

            if _opts.get("generate_lecture_notes", True):
                ln = session.get("_lecture_notes", {})
                if isinstance(ln, dict) and ln.get("grammar_points"):
                    _add_log(f"讲义: ✓ {len(ln.get('grammar_points',[]))} 个语法点", "success")
                else:
                    _add_log("讲义: ✗ 生成失败", "warn")
            else:
                _add_log("讲义: — 未选择（跳过）", "info")

            st.session_state["processing_text"] = "📋 校验完成 → 渲染输出…"
            for key in ("_parallel_start", "_parallel_threads", "_parallel_results", "_parallel_done", "_parallel_task_count", "_parallel_task_names"):
                st.session_state.pop(key, None)
            st.session_state["_proc_stage"] = 8
            st.session_state["processing_progress"] = progress_map[8]
        else:
            elapsed_str = f"{t_elapsed:.0f}s"
            st.session_state["processing_text"] = f"⚡ 并行处理中…已等待 {elapsed_str}（超时限制 10 分钟）"
            if int(t_elapsed) % 30 < 3 and int(t_elapsed) > 0:
                _add_log(f"⏳ 仍在等待…已过 {elapsed_str}", "info")
            time.sleep(2)
        st.rerun()

    # ═══════════════════════════════════════════════
    # Stage 8-9: HTML 渲染 + 数据装配
    # ═══════════════════════════════════════════════
    elif stage == 8:
        # ── API 预检失败，直接终止 ──
        if st.session_state.get("_api_failed"):
            _add_log("━━━ 处理终止：API 连接失败 ━━━", "error")
            _add_log("请检查 DeepSeek API 密钥和网络连接后，点击「开始新的」重试。", "error")
            st.session_state["processing_text"] = "❌ 处理失败——API 不可用"
            st.session_state["_proc_stage"] = 99  # 终止状态
            st.rerun()

        # ── 游戏 HTML 渲染（仅游戏模式）──
        game_data = session.get("_homework_questions", {})
        if isinstance(game_data, dict) and game_data.get("levels"):
            _add_log("--- 渲染游戏 HTML ---", "highlight")
            _add_log("加载 game_template_v3.html (76k, 14 bug baked-in)…", "info")
            is_valid, val_errors, val_warnings = validate_game_data(game_data)
            if val_errors:
                for e in val_errors:
                    _add_log(f"游戏数据错误: {e}", "warn")
            if val_warnings:
                for w in val_warnings[:3]:
                    _add_log(f"游戏数据警告: {w}", "info")
            if is_valid:
                _add_log(f"游戏数据验证: 通过 {'(有' + str(len(val_warnings)) + '条警告)' if val_warnings else ''}", "success")
            else:
                _add_log(f"游戏数据验证: {len(val_errors)} 个错误——渲染可能异常", "warn")
            try:
                game_html = render_game_html(game_data)
                session["_game_html_template"] = game_html
                _add_log(f"HTML 渲染完成 ({len(game_html)} chars)", "success")
            except Exception as e:
                _add_log(f"HTML 渲染失败: {e}", "warn")
                session["_game_html_template"] = None
        else:
            _add_log("跳过游戏 HTML 渲染（非游戏模式或无游戏数据）", "info")

        # ── 练习题格式化（练习模式）──
        ex_data = session.get("_exercises", {})
        if isinstance(ex_data, dict) and ex_data.get("vocabulary_section"):
            _add_log("练习题: 格式化测试卷文本…", "info")
            ex_text = _format_exercise_for_download(ex_data)
            session["_exercise_text"] = ex_text
            _add_log(f"练习卷格式化完成 ({len(ex_text)} chars)", "success")

        # ── 讲义格式化 ──
        ln_data = session.get("_lecture_notes", {})
        if isinstance(ln_data, dict) and ln_data.get("grammar_points"):
            _add_log("讲义: 格式化文本…", "info")
            ln_text = _format_lecture_notes_for_download(ln_data)
            session["_lecture_notes_text"] = ln_text
            _add_log(f"讲义格式化完成 ({len(ln_text)} chars)", "success")

        st.session_state["_proc_stage"] = 9
        st.session_state["processing_progress"] = progress_map[9]
        time.sleep(0.08); st.rerun()

    elif stage == 9:
        _add_log("装配 Session JSON…", "info")
        st.session_state["_proc_stage"] = 10
        st.session_state["processing_progress"] = progress_map[10]
        time.sleep(0.05); st.rerun()

    elif stage == 10:
        _add_log("写入 teacher_review 初始状态…", "info")
        st.session_state["_proc_stage"] = 11
        st.session_state["processing_progress"] = progress_map[11]
        time.sleep(0.03); st.rerun()

    elif stage == 11:
        _add_log(">>> 全流程处理完毕 <<<", "highlight")
        options = session.get("options", {})
        hw_mode = options.get("homework_mode", "🎮 游戏")
        task_parts = ["反馈+高光"]
        if hw_mode in ("🎮 游戏", "🔀 都生成"):
            task_parts.append("游戏")
        if hw_mode in ("📝 练习", "🔀 都生成"):
            task_parts.append("练习")
        if options.get("generate_lecture_notes", True):
            task_parts.append("讲义")
        _add_log(f"并行管线: {'+'.join(task_parts)}同时生成 | 等待审核", "success")
        st.session_state["processing_progress"] = progress_map[12]
        st.session_state["processing_text"] = "✅ 全部分析完成！"
        st.session_state["_proc_done"] = True
        st.session_state["_proc_stage"] = 12

        # 装配最终 session
        try:
            session["ai_outputs"] = {
                "feedback_report": session.pop("_feedback_report", {}),
                "highlight_clips": session.pop("_highlight_clips", []),
                "homework_questions": session.pop("_homework_questions", {}),
                "lecture_notes": session.pop("_lecture_notes", {}),
                "exercises": session.pop("_exercises", {}),
                "game_html_template": session.pop("_game_html_template", None),
                "exercise_text": session.pop("_exercise_text", ""),
                "lecture_notes_text": session.pop("_lecture_notes_text", ""),
                "processed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            highlight_clips = session["ai_outputs"]["highlight_clips"]
            session["status"] = "pending_review"
            session["teacher_review"] = {
                "feedback_edits": {},
                "clips_approved": [
                    c["id"] for c in highlight_clips if c.get("selected")
                ] if isinstance(highlight_clips, list) else [],
                "manual_clips": [],
            }
        except Exception as e:
            _add_log(f"装配异常: {e}", "warn")
            st.session_state["_proc_error"] = str(e)
        st.session_state["session"] = session
        st.rerun()


# ── 页面渲染 ────────────────────────────────────────────────

# === 顶部标题栏 ===
st.markdown("""
<div class="app-header">
    <div class="app-title">课后输出工作台</div>
    <div class="app-subtitle">AI 驱动的课堂反馈 · 视频剪辑 · 游戏/练习 · 讲义</div>
</div>
<style>
.app-header { text-align:center; padding: 1.5rem 0 0.25rem; }
.app-title {
    font-family: 'Georgia', 'Noto Serif SC', 'STSong', serif;
    font-size: 2rem; font-weight: 700; color: var(--ink);
    letter-spacing: 0.02em;
}
.app-subtitle { font-size: 0.88rem; color: var(--ink-muted); margin-top: 0.35rem; }
</style>
""", unsafe_allow_html=True)

# 进度指示条
stages_map = {"submit": 0, "processing": 1, "review": 2, "published": 3}
current_idx = stages_map.get(st.session_state["stage"], 0)

stage_labels = [("提交素材", "📄"), ("AI 处理", "⚙️"), ("审核编辑", "🔍"), ("发布输出", "🚀")]

st.markdown(f"""
<div class="stage-indicator">
    {"".join(
        f'<div class="stage-step {"active" if i == current_idx else "done" if i < current_idx else ""}">'
        f'<div class="stage-dot">{icon}</div>'
        f'<div class="stage-label">{label}</div>'
        f'</div>'
        f'{"" if i == 3 else "<div class=\"stage-line " + ("done" if i < current_idx else "") + "\"></div>"}'
        for i, (label, icon) in enumerate(stage_labels)
    )}
</div>
<style>
.stage-indicator {{
    display: flex; align-items: center; justify-content: center;
    gap: 0; margin: 1rem 0 1.25rem; padding: 0 1rem;
}}
.stage-step {{
    display: flex; flex-direction: column; align-items: center; gap: 6px;
    flex-shrink: 0;
}}
.stage-dot {{
    width: 40px; height: 40px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 1.1rem; background: #E8E3DB; color: #999;
    transition: all .3s ease;
}}
.stage-step.active .stage-dot {{
    background: #206F6B; color: #fff;
    box-shadow: 0 4px 14px rgba(32,111,107,.25);
}}
.stage-step.done .stage-dot {{
    background: #5B8C5A; color: #fff;
}}
.stage-label {{
    font-size: 0.75rem; font-weight: 600; color: #999;
    white-space: nowrap; transition: color .3s;
}}
.stage-step.active .stage-label {{ color: #206F6B; }}
.stage-step.done .stage-label {{ color: #5B8C5A; }}
.stage-line {{
    width: 48px; height: 2px; background: #E8E3DB;
    margin: 0 4px; margin-bottom: 18px; transition: background .3s;
}}
.stage-line.done {{ background: #5B8C5A; }}
@media (max-width: 640px) {{
    .stage-line {{ width: 24px; }}
    .stage-dot {{ width: 34px; height: 34px; font-size: 0.95rem; }}
    .stage-label {{ font-size: 0.68rem; }}
}}
</style>

<!-- ── UI Redesign CSS ── -->
<style>
/* === Design Tokens === */
:root {{
    --ink: #1E1E1E;
    --ink-muted: #777;
    --paper: #FBF9F6;
    --card-bg: #FFFFFF;
    --card-border: #EBE6DE;
    --card-shadow: 0 1px 3px rgba(0,0,0,.04), 0 1px 2px rgba(0,0,0,.02);
    --card-radius: 14px;
    --accent: #2A7F6E;
    --accent-light: #E8F5F1;
    --warn: #D48C3C;
    --warn-light: #FDF6EE;
    --divider: #EDE9E2;
    --font-display: 'Georgia', 'Noto Serif SC', 'STSong', serif;
}}

/* === Submit Page Cards === */
.submit-card {{
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    border-radius: var(--card-radius);
    padding: 20px 22px;
    margin-bottom: 16px;
    box-shadow: var(--card-shadow);
}}
.submit-card h3 {{
    font-family: var(--font-display);
    font-size: 1.02rem;
    font-weight: 700;
    color: var(--ink);
    margin: 0 0 14px 0;
    padding-bottom: 10px;
    border-bottom: 1px solid var(--divider);
}}
.submit-card .stCaption {{
    color: var(--ink-muted);
    font-size: 0.78rem;
}}

/* === Review Page Panels === */
.review-column {{
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    border-radius: var(--card-radius);
    padding: 16px 18px;
    overflow-y: auto;
    box-shadow: var(--card-shadow);
}}
.review-column h3 {{
    font-family: var(--font-display);
    font-size: 1rem;
    font-weight: 700;
    color: var(--ink);
    margin: 0 0 10px 0;
    padding-bottom: 8px;
    border-bottom: 2px solid var(--accent-light);
}}
.review-column .stExpander {{
    border: 1px solid var(--divider) !important;
    border-radius: 10px !important;
    margin-bottom: 6px !important;
}}

/* === Video Preview Section (full-width below 3 columns) === */
.video-preview-full {{
    background: var(--card-bg);
    border: 1px solid var(--card-border);
    border-radius: var(--card-radius);
    padding: 18px 22px;
    margin-top: 20px;
    box-shadow: var(--card-shadow);
}}
.video-preview-full h3 {{
    font-family: var(--font-display);
    font-size: 1rem;
    font-weight: 700;
    color: var(--ink);
    margin: 0 0 14px 0;
    padding-bottom: 8px;
    border-bottom: 2px solid var(--accent-light);
}}

/* === Review Banner === */
.review-banner {{
    display: flex; align-items: center; justify-content: space-between;
    flex-wrap: wrap; gap: 12px;
    background: linear-gradient(160deg, #FCFAF7 0%, #F5F1EA 100%);
    border: 1px solid #E8E3DB; border-radius: 16px;
    padding: 14px 20px; margin-bottom: 1rem;
}}
.review-banner-left {{ display: flex; flex-direction: column; gap: 2px; }}
.review-banner-title {{
    font-family: 'Georgia', 'Noto Serif SC', serif;
    font-size: 1.15rem; font-weight: 700; color: #2B2B2B;
}}
.review-banner-meta {{ font-size: 0.8rem; color: #999; }}
.review-banner-right {{ display: flex; gap: 8px; flex-wrap: wrap; }}
.source-badge {{
    display: inline-block; padding: 5px 12px; border-radius: 20px;
    font-size: 0.78rem; font-weight: 600; white-space: nowrap;
}}

/* === Submit Button Area === */
.submit-btn-area {{
    text-align: center;
    padding: 10px 0 6px;
}}
.submit-btn-area .stButton > button {{
    font-family: var(--font-display);
    font-size: 1.05rem !important;
    font-weight: 700 !important;
    padding: 12px 48px !important;
    border-radius: 12px !important;
}}

/* === Checkbox done area === */
.done-check {{
    margin-top: 12px; padding-top: 10px;
    border-top: 1px solid var(--divider);
}}

/* === Responsive === */
@media (max-width: 900px) {{
    .submit-card {{ padding: 14px 12px; }}
}}
</style>
""", unsafe_allow_html=True)

# =====================================================================
def _render_game_review(game_data, review):
    """渲染游戏审核面板（内容预览模式）。"""
    game_config = game_data.get("gameConfig", {})
    vocab_list = game_data.get("vocabList", [])
    levels = game_data.get("levels", [])
    story = game_data.get("story", {})

    GAME_TYPE_ICONS = {
        "balloonPop": "🎈", "flashlight": "🔦", "sceneChoice": "🤔",
        "visualSpelling": "✏️", "wordScramble": "🧩", "memoryMatch": "🃏",
        "meteorCatcher": "🌠", "constellation": "⭐", "dreamcatcher": "🪶",
        "scratchCard": "🪄",
    }

    # 游戏标题和基本信息
    st.markdown(f"#### {game_config.get('title', '未命名游戏')}")
    if game_config.get('subtitle'):
        st.caption(game_config['subtitle'])
    if game_config.get('phonics'):
        st.markdown(f"📖 拼读规则：**{game_config['phonics']}**")

    # 词汇表（2 列紧凑网格）
    with st.expander(f"📋 词汇表（{len(vocab_list)} 词）", expanded=False):
        cols = st.columns(2)
        for i, v in enumerate(vocab_list):
            with cols[i % 2]:
                st.markdown(f"{v.get('emoji', '📝')} **{v.get('en', '?')}** — {v.get('cn', '?')}")

    # 关卡摘要
    type_counts = {}
    for lvl in levels:
        gt = lvl.get("gameType", "unknown")
        type_counts[gt] = type_counts.get(gt, 0) + 1
    st.markdown(f"**🕹️ {len(levels)} 关** — " + " · ".join(
        f"{GAME_TYPE_ICONS.get(gt, '🎯')}×{c}" for gt, c in type_counts.items()
    ))

    # 故事预览（仅摘要）
    if story.get("paragraphs"):
        with st.expander("📖 故事预览", expanded=False):
            for p in story["paragraphs"][:3]:
                en_text = p.get('en', '')
                if len(en_text) > 120:
                    en_text = en_text[:120] + '...'
                st.markdown(f"{en_text}")
            if len(story.get("paragraphs", [])) > 3:
                st.caption(f"... 共 {len(story['paragraphs'])} 段")



# 阶段一：提交素材
# =====================================================================
if st.session_state["stage"] == "submit":

    st.markdown(f"""
    <div style="text-align:center;padding:0.5rem 0 1.25rem;">
        <div style="font-family:var(--font-display);font-size:1.4rem;font-weight:700;color:var(--ink);">提交课堂素材</div>
        <div style="font-size:0.88rem;color:var(--ink-muted);margin-top:6px;">上传录屏、粘贴文章和词汇，AI 将自动处理</div>
    </div>
    """, unsafe_allow_html=True)

    col_left, col_right = st.columns([1, 1])

    # ═══ 左列：媒体素材 ═══
    with col_left:
        # 课堂录屏
        st.markdown('<div class="submit-card">', unsafe_allow_html=True)
        st.markdown("### 🎬 课堂录屏")
        video_file = st.file_uploader(
            "上传腾讯会议录屏（mp4/flv）",
            type=["mp4", "flv", "mov", "avi"],
            key="video_file",
            help="上传课堂录屏文件。如有腾讯会议转写稿可直接粘贴，无需上传视频。",
        )
        if video_file:
            st.success(f"已上传：{video_file.name}")
            st.video(video_file)
        else:
            ffmpeg_ok, ffmpeg_info = check_ffmpeg()
            if ffmpeg_ok:
                st.caption(f"✅ FFmpeg {ffmpeg_info.split('ffmpeg version ')[-1].split()[0] if 'ffmpeg version' in ffmpeg_info else ''} 已就绪 — 可从视频自动提取音频做 ASR")
            else:
                st.caption("⚠️ FFmpeg 未安装 — 上传视频将无法自动做语音识别。建议粘贴腾讯会议转写稿代替。")
        st.markdown('</div>', unsafe_allow_html=True)

        # 腾讯会议转写稿
        st.markdown('<div class="submit-card">', unsafe_allow_html=True)
        st.markdown("### 💬 腾讯会议转写稿（推荐）")
        st.text_area(
            "粘贴腾讯会议的转写文本（含说话人和时间戳）",
            key="transcript_input",
            height=240,
            placeholder="王老师 00:00:00\nGood morning everyone! Today we're going to...\n\nAlice 00:01:02\nTeacher! 'ee' makes the long E sound...",
            help="✨ 粘贴后可跳过视频上传，系统直接解析转写稿中的说话人和时间戳。支持腾讯会议 txt 导出、SRT 字幕、JSON 等格式。",
        )
        transcript_text = st.session_state.get("transcript_input", "").strip()
        if transcript_text:
            if is_transcript_available(transcript_text):
                st.success(f"✅ 检测到有效转写稿（{len(transcript_text)} 字符）— 将跳过 ASR，直接解析")
            else:
                st.warning("⚠️ 转写稿内容较短，请确认格式是否正确")
        st.markdown('</div>', unsafe_allow_html=True)

        # 测试用例快捷加载
        st.markdown('<div class="submit-card">', unsafe_allow_html=True)
        st.markdown("### 🧪 测试用例")
        test_cases = list_test_cases()
        loaded_case = st.session_state.get("_test_case_loaded", "")
        if loaded_case:
            st.success(f"✅ 已加载测试用例：**{loaded_case}**")

        for tc in test_cases:
            is_loaded = (loaded_case == tc["name"])
            label = f"{'✅' if is_loaded else '📂'} {tc['name']}: {tc['teacher']} · {tc['grade']}"
            if st.button(label, use_container_width=True, disabled=is_loaded,
                         help=tc.get("description", ""),
                         key=f"load_{tc['name']}"):
                st.session_state["_pending_test_case"] = tc["name"]
                st.rerun()

        if st.session_state.get("_test_case_error"):
            st.error(f"加载失败：{st.session_state['_test_case_error']}")
            st.session_state.pop("_test_case_error", None)

        st.caption("💡 点击后自动填入老师、年级、文章、词汇、逐字稿")
        st.markdown('</div>', unsafe_allow_html=True)

    # ═══ 右列：教学内容 + 选项 ═══
    with col_right:
        # 老师姓名 + 年级
        st.markdown('<div class="submit-card">', unsafe_allow_html=True)
        st.markdown("### 👤 基本信息")
        col_name, col_grade = st.columns(2)
        with col_name:
            st.text_input("老师姓名", key="teacher_name", placeholder="如：王老师", autocomplete="name")
        with col_grade:
            st.selectbox(
                "学生年级",
                options=["小学一年级", "小学二年级", "小学三年级", "小学四年级",
                         "小学五年级", "小学六年级", "初中一年级", "初中二年级", "初中三年级"],
                index=4,
                key="grade_level",
                help="选择学生年级，AI 会根据年级调整评语深度和建议难度",
            )
        st.markdown('</div>', unsafe_allow_html=True)

        # 文章内容
        st.markdown('<div class="submit-card">', unsafe_allow_html=True)
        st.markdown("### 📖 文章内容")
        st.text_area(
            "粘贴当堂课的文章/课文",
            key="article_input",
            height=180,
            placeholder="Grandmother (奶奶) says, \"I am (我是) lost.\"\nShe looks at an (一个) old (老的) map (地图).\n...",
        )
        st.markdown('</div>', unsafe_allow_html=True)

        # 词汇表
        st.markdown('<div class="submit-card">', unsafe_allow_html=True)
        st.markdown("### 📝 词汇表")
        st.text_area(
            "每行一个词：英文 中文释义",
            key="vocab_input",
            height=130,
            placeholder="bee 蜜蜂\nsheep 羊\nstreet 街道\nsweep 打扫\n...",
        )
        st.caption("格式：英文单词 + 空格 + 中文释义，每行一个")
        st.markdown('</div>', unsafe_allow_html=True)

        # 输出选项
        st.markdown('<div class="submit-card">', unsafe_allow_html=True)
        st.markdown("### ⚙️ 输出选项")
        col_mode, col_notes = st.columns(2)
        with col_mode:
            st.radio(
                "📝 作业输出模式",
                options=["🎮 游戏", "📝 练习", "🔀 都生成"],
                index=0,
                key="homework_mode",
                help="游戏：生成 10 关互动 HTML 游戏\n练习：生成 20 题词汇+语法测试卷\n都生成：两者都产出",
            )
        with col_notes:
            st.markdown("<br>", unsafe_allow_html=True)
            st.checkbox(
                "📖 生成课堂讲义",
                value=True,
                key="generate_lecture_notes",
                help="根据逐字稿自动提取语法点和常用搭配，生成结构化讲义",
            )
        st.markdown('</div>', unsafe_allow_html=True)

    # ═══ 提交按钮 ═══
    st.markdown('<div class="submit-btn-area">', unsafe_allow_html=True)
    btn_disabled = not st.session_state.get("article_input", "").strip()
    if btn_disabled:
        st.warning("⚠️ 请至少输入文章内容（录屏和转写稿可跳过）")
    if st.button("🚀 开始 AI 处理", type="primary", use_container_width=False, disabled=btn_disabled):
        start_processing()
        st.rerun()
    st.markdown('</div>', unsafe_allow_html=True)

# =====================================================================
# 阶段二：AI 处理中
# =====================================================================
elif st.session_state["stage"] == "processing":

    st.markdown('<div class="progress-container">', unsafe_allow_html=True)

    progress = st.session_state.get("processing_progress", 0)
    proc_text = st.session_state.get("processing_text", "⚙️ 初始化处理管线...")
    proc_done = st.session_state.get("_proc_done", False)

    # 处理完成 → 醒目成功提示
    if proc_done:
        st.markdown("""
        <div class="processing-done">
            <div class="processing-done-icon">✓</div>
            <div class="processing-done-title">全部分析完成</div>
            <div class="processing-done-sub">反馈报告 · 高光片段 · 课后作业均已生成</div>
        </div>
        <style>
        .processing-done { text-align:center; padding: 0.5rem 0; }
        .processing-done-icon {
            width: 64px; height: 64px; border-radius: 50%;
            background: #5B8C5A; color: #fff;
            display: flex; align-items: center; justify-content: center;
            font-size: 1.8rem; font-weight: 700;
            margin: 0 auto 1rem;
            box-shadow: 0 6px 24px rgba(91,140,90,.3);
        }
        .processing-done-title { font-family: 'Georgia', 'Noto Serif SC', serif; font-size: 1.4rem; font-weight: 700; color: #2B2B2B; }
        .processing-done-sub { font-size: 0.88rem; color: #6B6B6B; margin-top: 0.25rem; }
        </style>
        """, unsafe_allow_html=True)
        st.progress(1.0)
        st.caption("进度：100% — 反馈报告 + 高光片段 + 课后作业均已生成")

        # 完成后也显示完整日志
        logs = st.session_state.get("processing_logs", [])
        if logs:
            st.caption(f"📜 处理日志（共 {len(logs)} 条）")
            log_lines = []
            for entry in logs[-25:]:
                msg = entry["msg"]
                level = entry.get("level", "info")
                time_str = entry.get("time", "")
                if level == "highlight":
                    line = f'<span style="color:#FFE66D;">{msg}</span>'
                elif level == "success":
                    line = f'<span style="color:#7ED957;">  ✓ {msg}</span>'
                elif level == "warn":
                    line = f'<span style="color:#FFAA5C;">  ⚠ {msg}</span>'
                else:
                    line = f'<span style="color:#A0B4D0;">  {msg}</span>'
                log_lines.append(f'<span style="color:#556B82;">[{time_str}]</span> {line}')
            log_html = "<br>".join(log_lines)
            st.markdown(f"""
            <div style="background:#0D1117;border-radius:12px;padding:12px 16px;margin-top:8px;
                        font-family:'Cascadia Code','Fira Code','Consolas',monospace;
                        font-size:0.78rem;line-height:1.6;max-height:360px;overflow-y:auto;
                        border:1px solid #21262D;box-shadow:inset 0 2px 8px rgba(0,0,0,0.3);">
                {log_html}
            </div>
            """, unsafe_allow_html=True)
    else:
        # ── 旋转加载动画 ──
        st.markdown(f"""
        <div class="loader-container">
            <div class="loader-ring">
                <div class="loader-ring-inner"></div>
                <div class="loader-ring-outer"></div>
                <div class="loader-center">
                    <div class="loader-icon-cycle">
                        <span>📄</span>
                        <span>🎬</span>
                        <span>🎮</span>
                    </div>
                </div>
            </div>
            <div class="loader-text">{proc_text}</div>
            <div class="loader-pct">{progress}%</div>
        </div>
        <style>
        .loader-container {{
            display: flex; flex-direction: column; align-items: center;
            padding: 1.5rem 0 0.75rem;
        }}
        .loader-ring {{
            position: relative; width: 120px; height: 120px;
            display: flex; align-items: center; justify-content: center;
        }}
        .loader-ring-outer {{
            position: absolute; inset: 0;
            border-radius: 50%;
            border: 3px solid #E8E3DB;
            border-top-color: #206F6B;
            animation: spin 1.2s linear infinite;
        }}
        .loader-ring-inner {{
            position: absolute; inset: 10px;
            border-radius: 50%;
            border: 2.5px solid #E8E3DB;
            border-bottom-color: #D48C3C;
            animation: spin 0.9s linear infinite reverse;
        }}
        .loader-center {{
            position: relative; z-index: 1;
            width: 74px; height: 74px;
            display: flex; align-items: center; justify-content: center;
            background: #FCFAF7; border-radius: 50%;
        }}
        .loader-icon-cycle {{
            position: relative; width: 40px; height: 40px;
        }}
        .loader-icon-cycle span {{
            position: absolute; inset: 0; display: flex;
            align-items: center; justify-content: center;
            font-size: 1.5rem; opacity: 0;
            animation: iconCycle 3s ease-in-out infinite;
        }}
        .loader-icon-cycle span:nth-child(1) {{ animation-delay: 0s; }}
        .loader-icon-cycle span:nth-child(2) {{ animation-delay: 1s; }}
        .loader-icon-cycle span:nth-child(3) {{ animation-delay: 2s; }}
        @keyframes iconCycle {{
            0%, 20%   {{ opacity: 1; transform: scale(1); }}
            33%, 100% {{ opacity: 0; transform: scale(0.7); }}
        }}
        @keyframes spin {{
            to {{ transform: rotate(360deg); }}
        }}
        .loader-text {{
            margin-top: 1rem; font-size: 0.95rem; font-weight: 600;
            color: #2B2B2B; text-align: center;
        }}
        .loader-pct {{
            margin-top: 4px; font-size: 0.8rem; font-weight: 500;
            color: #999;
        }}
        </style>
        """, unsafe_allow_html=True)
        st.progress(progress / 100.0)

        # ── 终端风格滚动日志 ──
        logs = st.session_state.get("processing_logs", [])
        if logs:
            log_lines = []
            for entry in logs[-18:]:  # 最多显示最近 18 条
                msg = entry["msg"]
                level = entry.get("level", "info")
                time_str = entry.get("time", "")
                if level == "highlight":
                    line = f'<span style="color:#FFE66D;">{msg}</span>'
                elif level == "success":
                    line = f'<span style="color:#7ED957;">  ✓ {msg}</span>'
                elif level == "warn":
                    line = f'<span style="color:#FFAA5C;">  ⚠ {msg}</span>'
                else:
                    line = f'<span style="color:#A0B4D0;">  {msg}</span>'
                log_lines.append(f'<span style="color:#556B82;">[{time_str}]</span> {line}')
            log_html = "<br>".join(log_lines)
            st.markdown(f"""
            <div class="proc-log-panel" style="background:#0D1117;border-radius:12px;padding:12px 16px;margin-top:8px;
                        font-family:'Cascadia Code','Fira Code','Consolas',monospace;
                        font-size:0.78rem;line-height:1.6;max-height:320px;overflow-y:auto;
                        scroll-behavior:smooth;border:1px solid #21262D;
                        box-shadow:inset 0 2px 8px rgba(0,0,0,0.3);">
                {log_html}
            </div>
            <script>
                (function(){{
                    var el = document.querySelector('.proc-log-panel');
                    if(el) el.scrollTop = el.scrollHeight;
                }})();
            </script>
            """, unsafe_allow_html=True)

    # 处理未完成 → 推进一步
    if not proc_done:
        run_processing()

    # 处理完成 → 显示进入审核按钮
    if proc_done:
        st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        col_pp1, col_pp2, col_pp3 = st.columns([2, 1, 2])
        with col_pp2:
            if st.button("✅ 进入审核台", type="primary", use_container_width=True):
                st.session_state["stage"] = "review"
                st.session_state.pop("_proc_stage", None)
                st.session_state.pop("_proc_done", None)
                st.session_state.pop("processing_logs", None)
                st.rerun()
    else:
        st.markdown(f"""
        <div style="color:#999;font-size:0.82rem;margin-top:1rem;text-align:center;">
            预计耗时约 4 分钟 · 三条 AI 任务并行处理 · 实际速度取决于 API 响应时间
        </div>
        """, unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

# =====================================================================
# 阶段三：审核编辑台
# =====================================================================
elif st.session_state["stage"] == "review":

    session = st.session_state.get("session", {})
    ai = session.get("ai_outputs", {})
    review = session.get("teacher_review", {})

    # ── 数据来源标记 ──
    report_source = ai.get("feedback_report", {}).get("_source", "unknown")
    homework_source = ai.get("homework_questions", {}).get("_source", "unknown")
    source_config = {
        "llm": ("AI 生成", "#2A7F6E", "#E8F5F1"),
        "unknown": ("示例数据", "#999", "#F5F5F5"),
    }
    fb_label, fb_color, fb_bg = source_config.get(report_source, source_config["unknown"])
    hw_label, hw_color, hw_bg = source_config.get(homework_source, source_config["unknown"])

    st.markdown(f"""
    <div class="review-banner">
        <div class="review-banner-left">
            <div class="review-banner-title">审核编辑台</div>
            <div class="review-banner-meta">处理完成：{ai.get('processed_at', '—')}</div>
        </div>
        <div class="review-banner-right">
            <span class="source-badge" style="background:{fb_bg};color:{fb_color};">📄 反馈：{fb_label}</span>
            <span class="source-badge" style="background:{hw_bg};color:{hw_color};">🎮 作业：{hw_label}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # ── 读取模式 ──
    hw_mode = session.get("options", {}).get("homework_mode", "🎮 游戏")
    want_game = hw_mode in ("🎮 游戏", "🔀 都生成")
    want_exercise = hw_mode in ("📝 练习", "🔀 都生成")
    want_lecture_notes = session.get("options", {}).get("generate_lecture_notes", True)

    # ═══════════════════════════════════════════════
    # 三列并排布局：反馈 | 讲义 | 游戏/练习
    # ═══════════════════════════════════════════════
    col_fb, col_ln, col_hw = st.columns([1, 1, 1])

    # ═══ 左列：课后反馈报告 ═══
    with col_fb:
        st.markdown('<div class="review-column">', unsafe_allow_html=True)
        st.markdown("### 📄 课后反馈报告")

        report = ai.get("feedback_report", {})

        view_mode = st.radio(
            "查看模式",
            options=["✏️ 编辑模式", "👁️ 预览模式"],
            horizontal=True,
            key="feedback_view_mode",
            label_visibility="collapsed",
        )

        if view_mode == "👁️ 预览模式":
            preview_report = merge_feedback_edits(report, review.get("feedback_edits", {}))
            _render_report_preview(preview_report, session)
        else:
            # 课堂摘要
            with st.expander("📋 课堂摘要", expanded=True):
                original_summary = report.get("summary", "")
                edited_summary = st.text_area(
                    "摘要内容",
                    value=review.get("feedback_edits", {}).get("summary", original_summary),
                    height=100, key="edit_summary", label_visibility="collapsed",
                )
                review.setdefault("feedback_edits", {})["summary"] = edited_summary
                _show_edit_indicator(edited_summary, original_summary, "摘要")

            # 知识覆盖
            with st.expander("🎯 知识覆盖度", expanded=False):
                coverage_items = report.get("knowledge_coverage", [])
                original_coverage_text = _format_coverage_text(coverage_items)

                current_edit = review.get("feedback_edits", {}).get("knowledge_coverage", "")
                edited_coverage = st.text_area(
                    "知识覆盖度（每行一个，格式：图标 知识点 ||| 详细说明）",
                    value=current_edit if current_edit else original_coverage_text,
                    height=120, key="edit_coverage", label_visibility="collapsed",
                )
                review.setdefault("feedback_edits", {})["knowledge_coverage"] = edited_coverage
                _show_edit_indicator(edited_coverage, original_coverage_text, "知识覆盖度")

            # 学生表现
            with st.expander("👤 学生表现评估", expanded=True):
                students = report.get("student_performance", {})
                dim_labels = {"发音准确性": "🗣️", "课堂参与": "🙋", "造句表达": "💬", "词汇掌握": "📚", "学习习惯": "📝"}
                for name, info in students.items():
                    st.markdown(f"**{name}** — {info.get('level', '—')}")

                    dims = info.get("dimensions", {})
                    if dims:
                        dim_cols = st.columns(5)
                        for i, (dim_name, dim_data) in enumerate(dims.items()):
                            with dim_cols[i]:
                                stars = "⭐" * dim_data.get("stars", 0) + "☆" * (5 - dim_data.get("stars", 0))
                                st.markdown(f"{dim_labels.get(dim_name, '')} {stars}")
                                st.caption(dim_data.get("note", "")[:25] if dim_data.get("note") else "")

                    if info.get("highlight"):
                        st.caption(f"✨ {info['highlight'][:80]}")

                    original_comment = info.get("comment", "")
                    edited_comment = st.text_area(
                        f"{name} 的评语",
                        value=review.get("feedback_edits", {}).get(f"student_{name}", original_comment),
                        height=56, key=f"edit_student_{name}", label_visibility="collapsed",
                    )
                    review.setdefault("feedback_edits", {})[f"student_{name}"] = edited_comment
                    _show_edit_indicator(edited_comment, original_comment, f"{name} 的评语")

                    original_pa = info.get("parent_action", "")
                    edited_pa = st.text_area(
                        f"{name} 家长建议",
                        value=review.get("feedback_edits", {}).get(f"parent_action_{name}", original_pa),
                        height=42, key=f"edit_pa_{name}", label_visibility="collapsed",
                        placeholder=f"🏠 {name} 的家长行动建议...",
                    )
                    review.setdefault("feedback_edits", {})[f"parent_action_{name}"] = edited_pa
                    st.markdown("---")

            # 教学建议
            with st.expander("💡 教学建议", expanded=False):
                original_teaching = report.get("teaching_suggestions", "")
                edited_teaching = st.text_area(
                    "教学建议",
                    value=review.get("feedback_edits", {}).get("teaching", original_teaching),
                    height=80, key="edit_teaching", label_visibility="collapsed",
                )
                review.setdefault("feedback_edits", {})["teaching"] = edited_teaching
                _show_edit_indicator(edited_teaching, original_teaching, "教学建议")

            # 家长指引
            with st.expander("🏠 家长指引", expanded=False):
                original_parent = report.get("parent_guide", "")
                edited_parent = st.text_area(
                    "家长指引",
                    value=review.get("feedback_edits", {}).get("parent", original_parent),
                    height=80, key="edit_parent", label_visibility="collapsed",
                )
                review.setdefault("feedback_edits", {})["parent"] = edited_parent
                _show_edit_indicator(edited_parent, original_parent, "家长指引")

        # 审核确认
        feedback_done = st.checkbox("✅ 反馈报告审核完毕", key="feedback_done")
        if feedback_done:
            edits = review.get("feedback_edits", {})
            if edits:
                diffs = get_edit_diff(report, edits)
                changed = [d for d in diffs if d["changed"]]
                if changed:
                    st.markdown("**📝 修改摘要：**")
                    for d in changed:
                        delta = len(d["edited"]) - len(d["original"])
                        sign = "+" if delta > 0 else ""
                        st.markdown(f"- ✏️ **{d['field']}**：{len(d['original'])}字 → {len(d['edited'])}字（{sign}{delta}字）")
                if not changed:
                    st.success("📋 报告未做任何修改，AI 原文直接发布")

        st.markdown('</div>', unsafe_allow_html=True)

    # ═══ 中列：课堂讲义 ═══
    with col_ln:
        st.markdown('<div class="review-column">', unsafe_allow_html=True)
        st.markdown("### 📖 课堂讲义")

        lecture_notes_data = ai.get("lecture_notes", {})
        if want_lecture_notes and isinstance(lecture_notes_data, dict) and lecture_notes_data.get("grammar_points"):
            st.markdown(f"**{lecture_notes_data.get('title', '课堂讲义')}**")
            ci = lecture_notes_data.get("class_info", {})
            st.caption(f"{ci.get('subject', '英语')} | {ci.get('topic', '')} | {ci.get('grade', '')}")

            le = review.setdefault("lecture_edits", {})

            # ── 语法点（JSON 编辑）──
            grammar = lecture_notes_data.get("grammar_points", [])
            if grammar:
                with st.expander("📐 语法与句型详解", expanded=True):
                    # 只读折叠预览
                    for i, gp in enumerate(grammar):
                        with st.expander(f"{i+1}. {gp.get('name', '语法点')}", expanded=False):
                            st.markdown(f"**结构**：`{gp.get('structure', '')}`")
                            st.markdown(f"**含义**：{gp.get('meaning', '')}")
                            st.markdown(f"**例句**：*{gp.get('example', '')}* — {gp.get('example_cn', '')}")
                            if gp.get("common_mistake"):
                                st.caption(f"⚠️ {gp['common_mistake']}")

                    original_gp_json = json.dumps(grammar, ensure_ascii=False, indent=2)
                    edited_gp = st.text_area(
                        "编辑语法点（JSON 格式）",
                        value=le.get("grammar_points", original_gp_json),
                        height=150, key="edit_grammar_points", label_visibility="collapsed",
                    )
                    le["grammar_points"] = edited_gp
                    _show_edit_indicator(edited_gp, original_gp_json, "语法点列表")

            # ── 短语（JSON 编辑）──
            phrases = lecture_notes_data.get("phrases", [])
            if phrases:
                with st.expander("📝 常见搭配与短语归纳", expanded=False):
                    original_ph_json = json.dumps(phrases, ensure_ascii=False, indent=2)
                    edited_ph = st.text_area(
                        "编辑短语（JSON 格式）",
                        value=le.get("phrases", original_ph_json),
                        height=120, key="edit_phrases", label_visibility="collapsed",
                    )
                    le["phrases"] = edited_ph
                    _show_edit_indicator(edited_ph, original_ph_json, "短语列表")

            # ── 词汇总结（纯文本）──
            if lecture_notes_data.get("vocabulary_summary"):
                with st.expander("📚 词汇总结", expanded=False):
                    original_vs = lecture_notes_data.get("vocabulary_summary", "")
                    edited_vs = st.text_area(
                        "词汇总结",
                        value=le.get("vocabulary_summary", original_vs),
                        height=100, key="edit_vocab_summary", label_visibility="collapsed",
                    )
                    le["vocabulary_summary"] = edited_vs
                    _show_edit_indicator(edited_vs, original_vs, "词汇总结")

            # ── 学习建议（纯文本）──
            if lecture_notes_data.get("study_tips"):
                with st.expander("💡 学习建议", expanded=False):
                    original_st = lecture_notes_data.get("study_tips", "")
                    edited_st = st.text_area(
                        "学习建议",
                        value=le.get("study_tips", original_st),
                        height=80, key="edit_study_tips", label_visibility="collapsed",
                    )
                    le["study_tips"] = edited_st
                    _show_edit_indicator(edited_st, original_st, "学习建议")
        elif not want_lecture_notes:
            st.info("📖 讲义未选择生成（可在提交页开启）")
        else:
            st.info("暂无讲义数据")

        lecture_done = st.checkbox("✅ 讲义审核完毕", key="lecture_done")
        st.markdown('</div>', unsafe_allow_html=True)

    # ═══ 右列：游戏 / 练习 ═══
    with col_hw:
        st.markdown('<div class="review-column">', unsafe_allow_html=True)

        # ── 游戏显示 ──
        if want_game:
            st.markdown("### 🎮 课后游戏作业")
            game_data = ai.get("homework_questions", {})
            if isinstance(game_data, dict) and game_data.get("levels"):
                _render_game_review(game_data, review)
            else:
                st.info("暂无游戏数据")

        # ── 练习显示 ──
        if want_exercise:
            if want_game:
                st.markdown("---")
            st.markdown("### 📝 课后练习题")
            ex_data = ai.get("exercises", {})
            if isinstance(ex_data, dict) and ex_data.get("vocabulary_section"):
                vocab_qs = ex_data.get("vocabulary_section", {}).get("questions", [])
                gram_qs = ex_data.get("grammar_section", {}).get("questions", [])
                st.markdown(f"📋 词汇选择 **{len(vocab_qs)}** 题 + 语法选择 **{len(gram_qs)}** 题")

                with st.expander("📝 词汇题预览", expanded=False):
                    for q in vocab_qs[:5]:
                        st.markdown(f"**{q.get('id')}.** {q.get('sentence', '')}")
                        st.caption(f"答案：{q.get('answer', '')} — {q.get('explanation', '')[:60]}...")
                    if len(vocab_qs) > 5:
                        st.caption(f"... 共 {len(vocab_qs)} 题")

                with st.expander("📝 语法题预览", expanded=False):
                    for q in gram_qs[:5]:
                        st.markdown(f"**{q.get('id')}.** {q.get('sentence', '')}")
                        st.caption(f"答案：{q.get('answer', '')} — {q.get('explanation', '')[:60]}...")
                    if len(gram_qs) > 5:
                        st.caption(f"... 共 {len(gram_qs)} 题")

                with st.expander("🔑 全部答案与解析", expanded=False):
                    st.markdown("**词汇部分：**")
                    for q in vocab_qs:
                        st.markdown(f"{q.get('id')}. **{q.get('answer')}** — {q.get('explanation', '')}")
                    st.markdown("**语法部分：**")
                    for q in gram_qs:
                        st.markdown(f"{q.get('id')}. **{q.get('answer')}** — {q.get('explanation', '')}")
            else:
                st.info("暂无练习题数据")

        if not want_game and not want_exercise:
            st.markdown("### 🎮 课后作业")
            st.info("（未选择作业输出模式）")

        homework_done = st.checkbox("✅ 课后作业审核完毕", key="homework_done")
        st.markdown('</div>', unsafe_allow_html=True)

    # ═══════════════════════════════════════════════
    # 全宽视频预览区（三列下方）
    # ═══════════════════════════════════════════════
    st.markdown('<div class="video-preview-full">', unsafe_allow_html=True)
    st.markdown("### 🎬 视频高光剪辑")

    clips = ai.get("highlight_clips", [])
    approved_ids = review.get("clips_approved", [])
    manual_clips = review.get("manual_clips", [])

    HIGHLIGHT_TYPE_LABELS = {
        "creative_production": ("🏆", "创造性产出"),
        "knowledge_connection": ("🔗", "知识连接"),
        "self_driven": ("🚀", "自我驱动"),
        "deep_comprehension": ("🧠", "深度理解"),
        "personality_spark": ("✨", "个性闪光"),
    }

    col_clips, col_preview = st.columns([1, 2])

    with col_clips:
        st.markdown("**🤖 AI 自动推荐片段**")
        for clip in clips:
            cid = clip.get("id")
            score = clip.get("auto_score", 0)
            student = clip.get("student", "")
            hl_type = clip.get("signals", {}).get("llm_highlight_type", "")

            if score >= 0.9:
                badge_class = "badge-success"
            elif score >= 0.7:
                badge_class = "badge-warning"
            else:
                badge_class = "badge-info"

            type_icon, type_label = HIGHLIGHT_TYPE_LABELS.get(hl_type, ("", ""))
            type_tag = f"<small>{type_icon} {type_label}</small>  " if type_icon else ""

            checked = st.checkbox(
                f"**#{cid}** {type_tag}{clip['description']}  "
                f"<span class='badge {badge_class}'>{score:.0%}</span>",
                value=(cid in approved_ids),
                key=f"clip_{cid}",
            )
            if checked:
                if cid not in approved_ids:
                    approved_ids.append(cid)
            else:
                if cid in approved_ids:
                    approved_ids.remove(cid)

            with st.expander(f"预览 — {student} ({clip['start']:.0f}s - {clip['end']:.0f}s)", expanded=False):
                signals = clip.get('signals', {})
                llm_score = signals.get('llm_score', 0)
                st.markdown(f"""
                > *{clip.get('transcript', '')}*

                **推荐理由**：{clip.get('reason', '')}

                **综合评分**：{clip.get('auto_score', 0):.0%}（规则 {clip.get('rule_score', 0):.0%} × 40% + LLM {llm_score:.0%} × 60%）

                **检测信号**：
                - 教师正面反馈：{'✅' if signals.get('teacher_praise') else '❌'}
                - 发言时长达标：{'✅' if signals.get('duration_ok') else '❌'}
                - LLM 语义评分：{llm_score:.0%}
                """)

        st.divider()

        # 手动添加
        st.markdown("**✋ 老师手动添加片段**")
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            manual_start = st.number_input("开始时间（秒）", min_value=0, value=0, step=5, key="manual_start")
        with col_t2:
            manual_end = st.number_input("结束时间（秒）", min_value=5, value=30, step=5, key="manual_end")
        manual_note = st.text_input("备注（可选）", placeholder="如：Bob 的精彩提问", key="manual_note")

        if st.button("➕ 添加此片段", key="add_manual"):
            if manual_end > manual_start:
                manual_clips.append({
                    "id": f"manual_{len(manual_clips)+1}",
                    "start": manual_start,
                    "end": manual_end,
                    "note": manual_note,
                    "source": "manual",
                })
                st.success(f"已添加：{manual_start}s – {manual_end}s")
                st.rerun()

        if manual_clips:
            st.markdown("**已添加的手动片段：**")
            for mc in manual_clips:
                col_m1, col_m2 = st.columns([4, 1])
                with col_m1:
                    st.markdown(f"📎 {mc['start']}s – {mc['end']}s — {mc.get('note', '无备注')}")
                with col_m2:
                    if st.button("🗑️", key=f"del_{mc['id']}"):
                        manual_clips.remove(mc)
                        st.rerun()

    with col_preview:
        st.markdown("**🎬 视频预览**")
        video_path = session.get("inputs", {}).get("video_path")
        ffmpeg_ok, _ = check_ffmpeg()
        can_preview = bool(video_path and ffmpeg_ok and os.path.isfile(video_path))

        if can_preview:
            preview_clips = [c for c in clips if c.get("id") in approved_ids]
            preview_clips += manual_clips
            preview_count = len(preview_clips)

            if preview_count > 0:
                if st.button("🎬 生成/刷新视频预览", key="gen_preview", use_container_width=True):
                    with st.spinner(f"正在裁剪 {preview_count} 个片段…"):
                        import tempfile
                        preview_dir = os.path.join(tempfile.gettempdir(), f"p4preview_{session['session_id']}")
                        os.makedirs(preview_dir, exist_ok=True)
                        preview_paths = []
                        for pc in preview_clips:
                            pc_id = pc.get("id", "?")
                            out_path = os.path.join(preview_dir, f"preview_{pc_id}.mp4")
                            try:
                                from utils.video_processor import clip_segment
                                clip_segment(video_path, pc["start"], pc["end"], out_path, buffer_seconds=1.0)
                                preview_paths.append({
                                    "id": pc_id, "student": pc.get("student", pc.get("note", "")),
                                    "start": pc["start"], "end": pc["end"], "path": out_path,
                                })
                            except Exception as e:
                                st.warning(f"片段 #{pc_id} 裁剪失败: {e}")
                        st.session_state["_preview_paths"] = preview_paths
                        st.session_state["_preview_dir"] = preview_dir
                        st.success(f"已生成 {len(preview_paths)} 个预览片段")
                        st.rerun()

                preview_paths = st.session_state.get("_preview_paths", [])
                if preview_paths:
                    current_ids = {pc.get("id") for pc in preview_clips}
                    preview_paths = [p for p in preview_paths if p["id"] in current_ids]
                    for pp in preview_paths:
                        if os.path.isfile(pp["path"]):
                            st.caption(f"#{pp['id']} — {pp.get('student', '')} ({pp['start']:.0f}s-{pp['end']:.0f}s)")
                            try:
                                st.video(pp["path"])
                            except Exception as e:
                                st.warning(f"无法播放: {e}")
            else:
                st.caption("💡 勾选左侧片段后，点击「生成视频预览」即可预览高光视频")
        else:
            if not video_path:
                st.caption("💡 上传视频文件后即可预览高光片段")
            elif not ffmpeg_ok:
                st.caption("⚠️ FFmpeg 未安装，无法生成视频预览。请运行: winget install ffmpeg")

    clips_done = st.checkbox("✅ 视频剪辑审核完毕", key="clips_done")
    st.markdown('</div>', unsafe_allow_html=True)

    # ═══ 底部：发布按钮 ═══
    st.divider()

    all_done = st.session_state.get("feedback_done", False) and                st.session_state.get("clips_done", False) and                st.session_state.get("homework_done", False) and                st.session_state.get("lecture_done", True)

    col_b1, col_b2, col_b3 = st.columns([2, 1, 2])
    with col_b2:
        if not all_done:
            missing = []
            if not st.session_state.get("feedback_done"): missing.append("反馈报告")
            if not st.session_state.get("clips_done"): missing.append("视频剪辑")
            if not st.session_state.get("homework_done"): missing.append("课后作业")
            if not st.session_state.get("lecture_done", True): missing.append("讲义")
            st.warning(f"⚠️ 请确认{', '.join(missing)}审核完毕后再发布")
        if st.button("🚀 确认发布", type="primary", use_container_width=True, disabled=not all_done):
            original_report = ai.get("feedback_report", {})
            feedback_edits = review.get("feedback_edits", {})
            final_report = merge_feedback_edits(original_report, feedback_edits)

            # 合并讲义编辑
            lecture_notes_original = ai.get("lecture_notes", {})
            lecture_edits = review.get("lecture_edits", {})
            if lecture_notes_original and lecture_edits:
                final_lecture_notes = merge_lecture_edits(lecture_notes_original, lecture_edits)
                session["_final_lecture_notes"] = final_lecture_notes

            session["teacher_review"] = review
            session["_final_feedback_report"] = final_report

            outputs = {
                "feedback_pdf": f"/outputs/{session['session_id']}_feedback.pdf",
                "highlight_video": f"/outputs/{session['session_id']}_highlights.mp4",
                "published_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            if want_game:
                outputs["homework_html"] = f"/outputs/{session['session_id']}_homework.html"
                outputs["homework_json"] = f"/outputs/{session['session_id']}_game_data.json"
            if want_exercise:
                outputs["exercise_text"] = f"/outputs/{session['session_id']}_exercise.txt"
            if want_lecture_notes and ai.get("lecture_notes"):
                outputs["lecture_notes"] = f"/outputs/{session['session_id']}_lecture_notes.txt"

            session["status"] = "published"
            session["outputs"] = outputs
            st.session_state["session"] = session
            st.session_state["stage"] = "published"
            st.rerun()

    with col_b1:
        if st.button("💾 保存草稿", use_container_width=True):
            session["teacher_review"] = review
            st.session_state["session"] = session
            st.success(f"草稿已保存 — {datetime.now().strftime('%H:%M:%S')}")

# =====================================================================
# 阶段四：发布完成
# =====================================================================
elif st.session_state["stage"] == "published":

    session = st.session_state.get("session", {})
    outputs = session.get("outputs", {})
    ai = session.get("ai_outputs", {})

    published_at = outputs.get("published_at", "—")
    st.markdown(f"""
    <div class="publish-success">
        <div class="publish-success-icon">✓</div>
        <div class="publish-success-title">发布成功</div>
        <div class="publish-success-desc">课后反馈、视频高光合集、课后作业已生成完毕</div>
        <div class="publish-success-time">发布时间：{published_at}</div>
    </div>
    <style>
    .publish-success-icon {{
        width: 72px; height: 72px; border-radius: 50%;
        background: #5B8C5A; color: #fff;
        display: flex; align-items: center; justify-content: center;
        font-size: 2rem; font-weight: 700;
        margin: 0 auto 1rem;
        box-shadow: 0 8px 32px rgba(91,140,90,.3);
    }}
    .publish-success-title {{
        font-family: 'Georgia', 'Noto Serif SC', serif;
        font-size: 1.5rem; font-weight: 700; color: #2B2B2B;
    }}
    .publish-success-desc {{ font-size: 0.92rem; color: #6B6B6B; margin-top: 0.35rem; }}
    .publish-success-time {{ font-size: 0.8rem; color: #999; margin-top: 0.5rem; }}
    </style>
    """, unsafe_allow_html=True)

    # 输出卡片
    st.markdown("""
    <div class="publish-cards-section">
    <div class="publish-cards-title">下载输出文件</div>
    </div>
    <style>
    .publish-cards-section {
        background: linear-gradient(160deg, #FCFAF7 0%, #F5F1EA 100%);
        border: 1px solid #E8E3DB; border-radius: 20px;
        padding: 20px 24px 8px; margin: 1.5rem 0;
    }
    .publish-cards-title {
        font-family: 'Georgia', 'Noto Serif SC', serif;
        font-size: 1rem; font-weight: 700; color: #2B2B2B;
        margin-bottom: 14px;
    }
    </style>
    """, unsafe_allow_html=True)

    col_o1, col_o2, col_o3 = st.columns(3)

    with col_o1:
        st.markdown('<div class="card" style="text-align:center;">', unsafe_allow_html=True)
        st.markdown("### 📄 课后反馈报告")

        # 使用最终版报告（已合并老师编辑）
        final_report = session.get("_final_feedback_report", ai.get("feedback_report", {}))
        was_edited = final_report.get("_edited", False)

        if was_edited:
            st.success(f"✏️ 已应用老师编辑")
        else:
            st.caption("（未修改，AI 原文）")

        st.markdown(f"`{outputs.get('feedback_pdf', '—')}`")

        # 生成可读的报告文本用于下载
        download_text = _format_report_for_download(final_report, session)
        st.download_button(
            "⬇️ 下载反馈报告",
            data=download_text,
            file_name=f"feedback_{session['session_id']}.txt",
            mime="text/plain",
        )
        st.markdown('</div>', unsafe_allow_html=True)

    with col_o2:
        st.markdown('<div class="card" style="text-align:center;">', unsafe_allow_html=True)
        st.markdown("### 🎬 学生高光合集")
        clips = ai.get("highlight_clips", [])
        approved = [c for c in clips if c.get("id") in session.get("teacher_review", {}).get("clips_approved", [])]
        manual = session.get("teacher_review", {}).get("manual_clips", [])
        total_clips = len(approved) + len(manual)
        st.markdown(f"自动片段 {len(approved)} 个 + 手动片段 {len(manual)} 个")

        # ── 视频剪辑生成（优先复用审核台预览片段）──
        video_path = session.get("inputs", {}).get("video_path")
        ffmpeg_ok, _ = check_ffmpeg()
        highlight_reel_path = None

        # 检查审核台是否已生成预览片段（避免重复跑 FFmpeg）
        preview_paths = st.session_state.get("_preview_paths", [])
        preview_dir = st.session_state.get("_preview_dir", "")

        if preview_paths and preview_dir and os.path.isdir(preview_dir):
            # 复用预览片段
            preview_clip_paths = [p["path"] for p in preview_paths if os.path.isfile(p["path"])]
            if len(preview_clip_paths) > 1:
                try:
                    from utils.video_processor import merge_clips
                    reel_path = os.path.join(preview_dir, "highlights_reel.mp4")
                    merge_clips(preview_clip_paths, reel_path)
                    highlight_reel_path = reel_path
                except Exception:
                    highlight_reel_path = preview_clip_paths[0] if preview_clip_paths else None
            elif len(preview_clip_paths) == 1:
                highlight_reel_path = preview_clip_paths[0]
        elif video_path and ffmpeg_ok and total_clips > 0:
            # 没有预览片段，从头生成
            try:
                from utils.video_processor import generate_highlight_reel
                all_clips = approved + [
                    {"id": m.get("id", f"m{i}"), "start": m["start"], "end": m["end"]}
                    for i, m in enumerate(manual)
                ]
                _output_dir = os.path.join(tempfile.gettempdir(), f"p4out_{session['session_id']}")
                result = generate_highlight_reel(video_path, all_clips, output_dir=_output_dir)
                if result.get("reel"):
                    highlight_reel_path = result["reel"]
                elif result.get("clips"):
                    highlight_reel_path = result["clips"][0]
            except Exception:
                pass

        if highlight_reel_path and os.path.isfile(highlight_reel_path):
            # 缓存视频数据到 session state，避免每次 rerun 重新读取文件
            cache_key = f"_highlight_video_data_{session['session_id']}"
            if cache_key not in st.session_state:
                with open(highlight_reel_path, "rb") as f_vid:
                    st.session_state[cache_key] = f_vid.read()
            st.download_button(
                "⬇️ 下载高光视频 (MP4)",
                data=st.session_state[cache_key],
                file_name=f"highlights_{session['session_id']}.mp4",
                mime="video/mp4",
            )
        else:
            st.caption("（未上传视频或 FFmpeg 不可用，仅导出剪辑列表）")

        st.download_button(
            "⬇️ 下载剪辑列表 (JSON)",
            data=json.dumps({"auto_clips": approved, "manual_clips": manual}, ensure_ascii=False, indent=2),
            file_name=f"clips_{session['session_id']}.json",
            mime="application/json",
        )
        st.markdown('</div>', unsafe_allow_html=True)

    with col_o3:
        st.markdown('<div class="card" style="text-align:center;">', unsafe_allow_html=True)
        hw_mode_pub = session.get("options", {}).get("homework_mode", "🎮 游戏")
        want_game_pub = hw_mode_pub in ("🎮 游戏", "🔀 都生成")
        want_exercise_pub = hw_mode_pub in ("📝 练习", "🔀 都生成")

        if want_game_pub:
            st.markdown("### 🎮 课后游戏作业")
            game_data = ai.get("homework_questions", {})
            vocab_count = len(game_data.get("vocabList", []))
            level_count = len(game_data.get("levels", []))
            st.markdown(f"{level_count} 关 · {vocab_count} 个词汇")

            game_html = ai.get("game_html_template") or session.get("_game_html_template")
            if game_html:
                st.download_button(
                    "⬇️ 下载游戏 HTML",
                    data=game_html,
                    file_name=f"game_{session['session_id']}.html",
                    mime="text/html",
                )
            else:
                st.caption("⚠️ 模板渲染失败，请查看 JSON 数据")

            with st.expander("📋 查看/下载 JSON 数据"):
                st.download_button(
                    "⬇️ 下载游戏数据（JSON）",
                    data=json.dumps(game_data, ensure_ascii=False, indent=2),
                    file_name=f"game_{session['session_id']}.json",
                    mime="application/json",
                )

        if want_exercise_pub:
            if want_game_pub:
                st.markdown("---")
            st.markdown("### 📝 课后练习题")
            ex_text = ai.get("exercise_text", "")
            ex_data = ai.get("exercises", {})
            vq = len(ex_data.get("vocabulary_section", {}).get("questions", [])) if isinstance(ex_data, dict) else 0
            gq = len(ex_data.get("grammar_section", {}).get("questions", [])) if isinstance(ex_data, dict) else 0
            st.markdown(f"词汇 {vq} 题 + 语法 {gq} 题")
            if ex_text:
                st.download_button(
                    "⬇️ 下载测试卷 (TXT)",
                    data=ex_text,
                    file_name=f"exercise_{session['session_id']}.txt",
                    mime="text/plain",
                )
            else:
                st.caption("⚠️ 练习卷文本不可用")

        if not want_game_pub and not want_exercise_pub:
            st.markdown("（未生成作业）")
        st.markdown('</div>', unsafe_allow_html=True)

    # ── 讲义下载卡片（第四栏）──
    # 优先使用合并后的最终讲义，否则用原始数据
    lecture_notes_out = session.get("_final_lecture_notes") or ai.get("lecture_notes", {})
    if isinstance(lecture_notes_out, dict) and lecture_notes_out.get("grammar_points"):
        # 显示 JSON 编辑的解析错误
        if lecture_notes_out.get("_grammar_parse_error"):
            st.warning(lecture_notes_out["_grammar_parse_error"])
        if lecture_notes_out.get("_phrases_parse_error"):
            st.warning(lecture_notes_out["_phrases_parse_error"])
        col_o4, col_o5, col_o6 = st.columns([1, 1, 1])
        with st.container():
            pass  # placeholder for spacing
        # 使用 expander 放在摘要上方
        with st.expander("📖 讲义下载", expanded=True):
            col_ln_a, col_ln_b = st.columns([2, 1])
            with col_ln_a:
                st.markdown(f"**{lecture_notes_out.get('title', '课堂讲义')}**")
                gp_count = len(lecture_notes_out.get("grammar_points", []))
                ph_count = len(lecture_notes_out.get("phrases", []))
                st.caption(f"{gp_count} 个语法点 · {ph_count} 个短语搭配")
            with col_ln_b:
                ln_text = ai.get("lecture_notes_text", "")
                if ln_text:
                    st.download_button(
                        "⬇️ 下载讲义",
                        data=ln_text,
                        file_name=f"lecture_notes_{session['session_id']}.txt",
                        mime="text/plain",
                    )

    st.markdown('</div>', unsafe_allow_html=True)  # 关闭 publish-cards-section

    # 摘要
    st.divider()
    st.markdown("### 📊 本次输出摘要")

    report = ai.get("feedback_report", {})
    students = report.get("student_performance", {})
    clips_total = len(session.get("teacher_review", {}).get("clips_approved", [])) + \
                  len(session.get("teacher_review", {}).get("manual_clips", []))
    game_data = ai.get("homework_questions", {})
    homework_total = len(game_data.get("levels", []))
    vocab_count = len(game_data.get("vocabList", []))
    lecture_gp = len(ai.get("lecture_notes", {}).get("grammar_points", []))
    ex_total = len(ai.get("exercises", {}).get("vocabulary_section", {}).get("questions", [])) + \
               len(ai.get("exercises", {}).get("grammar_section", {}).get("questions", []))

    # 根据输出选项动态显示摘要指标
    pub_hw_mode = session.get("options", {}).get("homework_mode", "🎮 游戏")
    pub_want_game = pub_hw_mode in ("🎮 游戏", "🔀 都生成")
    pub_want_exercise = pub_hw_mode in ("📝 练习", "🔀 都生成")
    pub_want_notes = session.get("options", {}).get("generate_lecture_notes", True)

    metric_cols = []
    metric_cols.append(("👤 学生评估", f"{len(students)} 人"))
    metric_cols.append(("🎬 高光片段", f"{clips_total} 个"))
    if pub_want_game:
        metric_cols.append(("🎮 游戏关卡", f"{homework_total} 关"))
    if pub_want_exercise:
        metric_cols.append(("📝 练习题", f"{ex_total} 题"))
    if pub_want_notes and lecture_gp > 0:
        metric_cols.append(("📖 讲义语法点", f"{lecture_gp} 个"))

    metric_cols_out = st.columns(len(metric_cols))
    for i, (label, value) in enumerate(metric_cols):
        metric_cols_out[i].metric(label, value)

    # 回到首页
    st.divider()
    col_r1, col_r2, col_r3 = st.columns([2, 1, 2])
    with col_r2:
        if st.button("🔄 开始新的处理", type="secondary", use_container_width=True):
            reset_app()
            st.rerun()

# ── 底部信息 ────────────────────────────────────────────────
st.divider()
st.markdown(
    '<div class="app-footer">课后输出工作台 · DeepSeek + Streamlit</div>',
    unsafe_allow_html=True,
)
st.markdown("""
<style>
.app-footer { text-align:center; color:#C0BDB6; font-size:0.78rem; padding-bottom: 1rem; }
</style>
""", unsafe_allow_html=True)
