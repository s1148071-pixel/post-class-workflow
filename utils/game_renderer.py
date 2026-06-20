"""
游戏 HTML 渲染器 — Phase 5 v3 核心模块。

v3 架构（2026-06-07）：
  使用 english-game v2 模板为母版 + {{GAME_DATA}} JSON 注入。
  模板已 baked-in 14 个 bug 修复 + post-class 增强 confetti/音效系统。

工作流：
  game_data JSON → validate_game_data() → render_game_html() → 下载
"""

import json
import re
from pathlib import Path


_TEMPLATE_PATH = Path(__file__).parent / "game_template_v3.html"

# 有效的游戏类型（与模板的 switch 分支一致）
VALID_GAME_TYPES = {
    "balloonPop", "flashlight", "sceneChoice", "visualSpelling",
    "wordScramble", "memoryMatch", "meteorCatcher", "constellation",
    "dreamcatcher", "scratchCard",
}


def validate_game_data(game_data):
    """渲染前验证游戏数据完整性，返回 (is_valid, errors, warnings)。

    Args:
        game_data (dict): LLM 生成的游戏数据

    Returns:
        tuple: (bool, list[str], list[str]) — 是否通过 / 错误列表 / 警告列表
    """
    errors = []
    warnings = []

    # ── gameConfig ──
    config = game_data.get("gameConfig", {})
    if not config.get("title"):
        errors.append("缺少 gameConfig.title（游戏标题）")

    # ── vocabList ──
    vocab = game_data.get("vocabList", [])
    if not vocab:
        errors.append("vocabList 为空——至少需要 8 个词汇")
    else:
        if len(vocab) < 8:
            warnings.append(f"vocabList 仅 {len(vocab)} 词，建议 ≥ 8 词")
        if len(vocab) > 15:
            warnings.append(f"vocabList 有 {len(vocab)} 词，关卡可能无法全部覆盖")
        # 检查每个词汇的必要字段
        for i, v in enumerate(vocab):
            if not v.get("en"):
                errors.append(f"vocabList[{i}] 缺少 en（英文）")
            if not v.get("cn"):
                warnings.append(f"vocabList[{i}] ({v.get('en', '?')}) 缺少 cn（中文）")
            if not v.get("emoji"):
                warnings.append(f"vocabList[{i}] ({v.get('en', '?')}) 缺少 emoji（图标）")

    # ── levels ──
    levels = game_data.get("levels", [])
    if not levels:
        errors.append("levels 为空——至少需要 8 个关卡")
    else:
        if len(levels) < 8:
            warnings.append(f"仅 {len(levels)} 关，建议 10 关")
        if len(levels) > 12:
            warnings.append(f"{len(levels)} 关偏多，建议 10 关以内")

        seen_answers = []  # 用 list 保留重复，才能做 dedup 检测
        for i, lvl in enumerate(levels):
            gt = lvl.get("gameType", "")
            lid = lvl.get("id", i + 1)

            if gt not in VALID_GAME_TYPES:
                errors.append(f"L{lid}: 未知游戏类型 '{gt}'，有效值: {sorted(VALID_GAME_TYPES)}")

            # 检查每关的必要字段
            if gt == "balloonPop":
                if not lvl.get("targetWord"): errors.append(f"L{lid} (气球): 缺少 targetWord")
                if not lvl.get("targetMeaning"): warnings.append(f"L{lid} (气球): 缺少 targetMeaning")
                if lvl.get("targetWord"): seen_answers.append(lvl["targetWord"])
                opts = lvl.get("options", [])
                if len(opts) < 3: errors.append(f"L{lid} (气球): options 不足（需 ≥ 3）")
                for o in opts:
                    if not o.get("en"): warnings.append(f"L{lid} (气球): option 缺少 en")
                # 🔴 答案正确性验证：options 必须包含 targetWord
                target_word = lvl.get("targetWord", "")
                if target_word and opts:
                    en_values = [o.get("en", "") for o in opts]
                    if target_word not in en_values:
                        errors.append(f"L{lid} (气球): options 不包含 targetWord '{target_word}'！游戏无法回答正确答案。")
                    else:
                        # emoji 一致性检查
                        correct_opt = next((o for o in opts if o.get("en") == target_word), None)
                        if correct_opt:
                            vocab_match = [v for v in vocab if v.get("en", "").lower() == target_word.lower()]
                            if vocab_match and correct_opt.get("emoji") != vocab_match[0].get("emoji"):
                                warnings.append(f"L{lid} (气球): 正确选项 emoji ({correct_opt.get('emoji')}) 与 vocabList 不一致 ({vocab_match[0].get('emoji')})")

            elif gt == "flashlight":
                if not lvl.get("targetEmoji"): errors.append(f"L{lid} (暗夜): 缺少 targetEmoji")
                if not lvl.get("targetWord"): warnings.append(f"L{lid} (暗夜): 缺少 targetWord（英文提示词）")
                if not lvl.get("targetMeaning"): warnings.append(f"L{lid} (暗夜): 缺少 targetMeaning")
                dist = lvl.get("distractors", [])
                if len(dist) < 5: errors.append(f"L{lid} (暗夜): distractors 不足（需 ≥ 5）")
                if len(dist) < 9: warnings.append(f"L{lid} (暗夜): distractors 仅 {len(dist)} 个（建议恰好 9 个，不足会随机化但可能导致网格空位）")

            elif gt == "sceneChoice":
                if not lvl.get("correctWord"): errors.append(f"L{lid} (情景): 缺少 correctWord")
                if not lvl.get("correctEmoji"): warnings.append(f"L{lid} (情景): 缺少 correctEmoji")
                if not lvl.get("wrongWord"): warnings.append(f"L{lid} (情景): 缺少 wrongWord")
                if lvl.get("correctWord"): seen_answers.append(lvl["correctWord"])
                # emoji 一致性检查
                cw = lvl.get("correctWord", "")
                ce = lvl.get("correctEmoji", "")
                if cw and ce:
                    vocab_match = [v for v in vocab if v.get("en", "").lower() == cw.lower()]
                    if vocab_match and ce != vocab_match[0].get("emoji"):
                        warnings.append(f"L{lid} (情景): correctEmoji ({ce}) 与 vocabList 中 {cw} 的 emoji ({vocab_match[0].get('emoji')}) 不一致")

            elif gt == "visualSpelling":
                if not lvl.get("targetWord"): errors.append(f"L{lid} (拼写): 缺少 targetWord")
                if not lvl.get("blankPattern"): errors.append(f"L{lid} (拼写): 缺少 blankPattern（含 blank id 的 HTML）")
                else:
                    bp = lvl["blankPattern"]
                    # 检查 blank id 是否从 0 开始
                    blank_ids = re.findall(r'id="blank-(\d+)"', bp)
                    if blank_ids:
                        ids = [int(x) for x in blank_ids]
                        if min(ids) != 0:
                            errors.append(f"L{lid} (拼写): blankPattern 的 id 编号从 {min(ids)} 开始，必须从 0 开始（模板代码用 blank-0, blank-1...）")
                        expected = list(range(len(ids)))
                        if ids != expected:
                            errors.append(f"L{lid} (拼写): blankPattern 的 id 不连续，期望 {expected}，实际 {ids}")
                correct = lvl.get("correct", [])
                if not correct: errors.append(f"L{lid} (拼写): 缺少 correct（正确字母列表）")
                distractors = lvl.get("distractors", [])
                if not distractors: errors.append(f"L{lid} (拼写): 缺少 distractors（干扰字母列表）")
                # 检查每个正确字母在干扰项中出现次数
                for c in correct:
                    count = distractors.count(c)
                    if count < correct.count(c):
                        errors.append(f"L{lid} (拼写): 字母 '{c}' 在 distractors 中出现 {count} 次，需要 ≥ {correct.count(c)} 次（Bug#8 回归防护）")
                if lvl.get("targetWord"): seen_answers.append(lvl["targetWord"])

            elif gt == "wordScramble":
                if not lvl.get("targetWord"): errors.append(f"L{lid} (重组): 缺少 targetWord")
                if not lvl.get("scrambled"): errors.append(f"L{lid} (重组): 缺少 scrambled（逗号分隔的乱序字母）")
                if lvl.get("targetWord"): seen_answers.append(lvl["targetWord"])

            elif gt == "memoryMatch":
                pairs = lvl.get("pairs", [])
                if len(pairs) < 2: errors.append(f"L{lid} (配对): pairs 不足（需 ≥ 2 对）")
                for p in pairs:
                    if not p.get("word"): warnings.append(f"L{lid} (配对): pair 缺少 word")
                    if not p.get("emoji"): warnings.append(f"L{lid} (配对): pair 缺少 emoji")
                    if p.get("word"): seen_answers.append(p["word"])

            elif gt == "meteorCatcher":
                if not lvl.get("targetWord"): errors.append(f"L{lid} (流星): 缺少 targetWord")
                if not lvl.get("targetMeaning"): warnings.append(f"L{lid} (流星): 缺少 targetMeaning")
                if lvl.get("targetWord"): seen_answers.append(lvl["targetWord"])

            elif gt == "constellation":
                if not lvl.get("targetWord"): errors.append(f"L{lid} (星座): 缺少 targetWord")
                if lvl.get("targetWord"): seen_answers.append(lvl["targetWord"])

            elif gt == "dreamcatcher":
                if not lvl.get("targetWord"): errors.append(f"L{lid} (捕梦网): 缺少 targetWord")
                if lvl.get("targetWord"): seen_answers.append(lvl["targetWord"])

            elif gt == "scratchCard":
                if not lvl.get("correctWord"): errors.append(f"L{lid} (刮刮卡): 缺少 correctWord")
                if not lvl.get("wrongWord"): warnings.append(f"L{lid} (刮刮卡): 缺少 wrongWord")
                # 词汇一致性检查（correctWord 和 wrongWord 都应来自词汇表）
                cw = lvl.get("correctWord", "")
                ww = lvl.get("wrongWord", "")
                if cw:
                    vocab_match = [v for v in vocab if v.get("en", "").lower() == cw.lower()]
                    if not vocab_match:
                        warnings.append(f"L{lid} (刮刮卡): correctWord '{cw}' 不在词汇表中")
                if ww:
                    vocab_match = [v for v in vocab if v.get("en", "").lower() == ww.lower()]
                    if not vocab_match:
                        warnings.append(f"L{lid} (刮刮卡): wrongWord '{ww}' 不在词汇表中")
                # L10 是回顾性质，不参与去重检查

        # 答案去重检查
        vocab_words = {v.get("en", "").lower() for v in vocab if v.get("en")}
        if seen_answers and vocab_words:
            covered = vocab_words & {a.lower() for a in seen_answers}
            uncovered = vocab_words - covered
            if uncovered:
                warnings.append(f"以下词汇未被任何关卡作为答案: {sorted(uncovered)}")
            # 去重
            from collections import Counter
            dupes = [w for w, c in Counter([a.lower() for a in seen_answers]).items() if c > 1]
            if dupes:
                warnings.append(f"答案重复: {dupes}（Bug#2 回归风险）")

    # ── story ──
    story = game_data.get("story", {})
    if not story.get("paragraphs"):
        warnings.append("story.paragraphs 为空，首页将不显示故事")

    is_valid = len(errors) == 0
    return is_valid, errors, warnings


def render_game_html(game_data):
    """模板渲染：读取 v3 模板，注入 GAME_TITLE + GAME_DATA，返回完整 HTML。

    Args:
        game_data (dict): 游戏关卡数据

    Returns:
        str: 完整 HTML 文件内容
    """
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")

    game_config = game_data.get("gameConfig", {})
    title = game_config.get("title", "英语趣味闯关")

    html = template.replace("{{GAME_TITLE}}", title)
    html = html.replace(
        "{{GAME_DATA}}",
        json.dumps(game_data, ensure_ascii=False, indent=2),
    )

    return html
