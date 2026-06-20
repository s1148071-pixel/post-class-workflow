#!/usr/bin/env python3
"""post-class 游戏数据验证工具 — 移植自 english-game test_runtime.py 的 12 项检测。

用法：
  python test_game_data.py game_data.json            # 验证指定 JSON 文件
  python test_game_data.py --render game_data.json   # 验证 + 渲染并检测 HTML
"""

import io
import json
import re
import sys
from pathlib import Path
from collections import Counter

# 修复 Windows GBK 编码问题
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 添加项目根目录到 path
sys.path.insert(0, str(Path(__file__).parent))
from utils.game_renderer import validate_game_data, render_game_html


def check_html_syntax(html):
    """基础 HTML 语法检查（移植自 test_syntax.py）。"""
    issues = []

    # 检查是否有 </script> 在 JSON 数据中（致命）
    script_close_count = html.count('</script>')
    if script_close_count != 1:
        issues.append(f"</script> 出现了 {script_close_count} 次（应为 1 次）——可能是 JSON 数据中未转义")

    # 检查关键 DOM 元素
    required_ids = [
        'page-bg-photo', 'bg-deco-layer', 'app',
        'page-container', 'confetti-canvas', 'feedback-toast',
        'progress-bar-wrap', 'progress-text', 'progress-inner', 'progress-score',
    ]
    for elem_id in required_ids:
        if f'id="{elem_id}"' not in html and f"id='{elem_id}'" not in html:
            issues.append(f"缺少 DOM 元素 #{elem_id}")

    # 检查关键函数定义
    required_funcs = [
        'function renderHome', 'function getCN', 'function getEmoji',
        'function makeListenButton', 'function handleCorrect', 'function handleWrong',
        'function goHome', 'function showToast', 'function speakWord',
        'function makeLevelContainer', 'function bindNavButtons',
        'function showCelebration', 'function updateProgress',
        'function getLevelData', 'function renderLevel',
    ]
    for func in required_funcs:
        if func not in html:
            issues.append(f"缺少函数: {func}")

    # 检查 Bug 修复是否 baked-in
    if 'meteorSpawnCount >= 6' not in html and 'spawnMeteor' in html:
        issues.append("Bug#5 回归：流星保底计数器缺失")
    if 'feather.dataset.letter === letters[wovenCount]' not in html:
        issues.append("Bug#6 回归：捕梦网字母值匹配缺失")
    if 'Math.cos(angle) * 28' not in html:
        if 'Math.cos(angle) * 3' in html:
            issues.append("Bug#13 回归：捕梦网轨道半径可能过大")
    if 'connected.includes' not in html:
        issues.append("Bug#7 回归：星座字母值扫描缺失")

    return issues


def check_vocab_coverage(game_data):
    """检查词汇覆盖度和答案分布。"""
    issues = []
    vocab = game_data.get("vocabList", [])
    levels = game_data.get("levels", [])
    vocab_words = {v.get("en", "").lower() for v in vocab if v.get("en")}

    if len(vocab) != 10:
        issues.append(f"VOCAB 词数 {len(vocab)}，建议恰好 10 词（Bug#1 防护）")

    # 收集所有答案词
    answer_words = set()
    for lvl in levels:
        gt = lvl.get("gameType", "")
        if gt == "balloonPop":
            if lvl.get("targetWord"): answer_words.add(lvl["targetWord"].lower())
        elif gt == "sceneChoice":
            if lvl.get("correctWord"): answer_words.add(lvl["correctWord"].lower())
        elif gt in ("visualSpelling", "wordScramble", "constellation", "dreamcatcher", "meteorCatcher"):
            if lvl.get("targetWord"): answer_words.add(lvl["targetWord"].lower())
        elif gt == "memoryMatch":
            for p in lvl.get("pairs", []):
                if p.get("word"): answer_words.add(p["word"].lower())
        elif gt == "scratchCard":
            if lvl.get("correctWord"): answer_words.add(lvl["correctWord"].lower())

    uncovered = vocab_words - answer_words
    if uncovered:
        issues.append(f"⚠️ {len(uncovered)} 个词汇未被任何关卡作为答案: {sorted(uncovered)}")

    return issues


def print_header(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def main():
    do_render = '--render' in sys.argv

    # 确定输入
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if args:
        data_path = Path(args[0])
        game_data = json.loads(data_path.read_text(encoding='utf-8'))
    else:
        print("❌ 请提供 game_data.json 文件路径作为参数")
        print("   用法: python test_game_data.py <game_data.json> [--render]")
        sys.exit(1)

    print_header("📋 Phase 5 v3 游戏数据验证")
    print(f"标题: {game_data.get('gameConfig', {}).get('title', '未命名')}")
    print(f"词汇: {len(game_data.get('vocabList', []))} 词")
    print(f"关卡: {len(game_data.get('levels', []))} 关")
    print(f"故事段落: {len(game_data.get('story', {}).get('paragraphs', []))} 段")

    # ── 数据层验证 ──
    print_header("🔍 数据层验证 (validate_game_data)")
    is_valid, errors, warnings = validate_game_data(game_data)

    if errors:
        print(f"\n❌ {len(errors)} 个错误:")
        for e in errors:
            print(f"   ❌ {e}")
    if warnings:
        print(f"\n⚠️ {len(warnings)} 个警告:")
        for w in warnings:
            print(f"   ⚠️ {w}")
    if not errors and not warnings:
        print("\n✅ 数据层验证全部通过！")

    # ── 词汇覆盖检查 ──
    print_header("📊 词汇覆盖度")
    vocab_issues = check_vocab_coverage(game_data)
    if vocab_issues:
        for i in vocab_issues:
            print(f"   {i}")
    else:
        print("✅ 词汇覆盖度正常")

    # ── HTML 渲染 + 静态分析 ──
    if do_render:
        print_header("🌐 HTML 渲染 + 静态分析")
        try:
            html = render_game_html(game_data)
            print(f"✅ HTML 渲染成功 ({len(html)} chars)")

            html_issues = check_html_syntax(html)
            if html_issues:
                print(f"\n⚠️ {len(html_issues)} 个 HTML 问题:")
                for i in html_issues:
                    print(f"   ⚠️ {i}")
            else:
                print("✅ HTML 静态分析全部通过！")
        except Exception as e:
            print(f"❌ HTML 渲染失败: {e}")

    # ── 汇总 ──
    print_header("📊 汇总")
    total_issues = len(errors) + len(warnings) + len(vocab_issues)
    if errors:
        print(f"🚨 {len(errors)} 个错误 — 渲染可能失败或游戏功能异常")
    if total_issues == 0:
        print("🎉 全部检查通过！游戏数据就绪。")
    else:
        print(f"共 {total_issues} 个问题需关注（{len(errors)} 错误 + {len(warnings) + len(vocab_issues)} 警告）")

    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
