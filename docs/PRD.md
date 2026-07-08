# 课后输出工作台 — 技术交底书

> **写给技术部的同事们** | 袁闻骏 (Donovan) | 2026-07-08
> 代码：[github.com/s1148071-pixel/post-class-workflow](https://github.com/s1148071-pixel/post-class-workflow)
> 在线 demo：http://localhost:8501（本地）/ Streamlit Cloud（部署中）

---

## 这玩意儿干嘛的

简单说：**老师上完课，粘贴文章和单词表，AI 自动吐出一份反馈报告、一段高光视频剪辑列表、一个学生能直接在手机上玩的 HTML 游戏。** 老师在审核台过一眼、改几处，点发布，全部下载。

以前老师手工干这事要 30-60 分钟。现在大概 10 分钟——其中 AI 处理 ~2 分钟，剩下 8 分钟是老师审核编辑。

---

## 我为什么要做这个

5 月份进高木实习，发现老师们每节课后的输出流程极其痛苦：

1. 翻课堂录屏回放，找学生发言的高光片段——很耗时
2. 给每个学生写个性化反馈——没逐字稿时基本靠编，"表现很好继续努力"往上一贴
3. 出课后作业——PPT 截图贴 Word 里导出 PDF，学生打开率极低

我当时在想：这堆东西能不能一次性自动生成？

于是花了两周写需求文档（就在我桌面 `课后输出工作流-需求文档.md`），画了流程图，6 月初开始写代码。一个半月后，v1 能跑了。

---

## 技术栈 & 为什么选这些

| 选型 | 为什么 |
|------|--------|
| **Streamlit** | Python 一把梭。不需要写前端（我没有 React 熟练度），一个 `st.button()` 就是一个按钮。审核台的三栏布局用 `st.columns()` 就搞定了。代价是性能——单线程，LLM 调用时 UI 会卡住（后面会讲怎么绕的） |
| **DeepSeek v4-pro** | 公司本来就有 proxy。API 兼容 OpenAI 格式，`openai` 库直接调。中文产出质量不错，102s 出 10 关游戏 JSON，schema 合规率 100%（调了几轮 prompt 之后） |
| **纯 HTML 游戏模板** | 一开始想让 LLM 直接生成 HTML——结果不稳定，同样的 prompt 两次输出完全不同的 DOM 结构。后来改成固定模板 + JSON 数据注入：LLM 只填内容词，模板负责渲染。Schema 合规率从 ~70% 蹦到 100% |
| **有道 dictvoice** | 免费，不需要 API Key，`<audio src="...">` 贴进去就能发音。Whisper/通义听悟也调研了，但发现腾讯会议的自动转写稿已经够用——外部 ASR API 多一层网络延迟，用户体验反而变差，最后砍了 |
| **FFmpeg** | 高光视频片段需要从原始录屏里裁剪。`shutil.which("ffmpeg")` 自动搜路径，Windows 上兼容 winget 安装的版本 |

---

## 项目结构（5 分钟看懂）

```
post-class-workflow/
├── app.py                       # ~2600 行，Streamlit UI + 四阶段状态机
├── .streamlit/config.toml       # 主题色 + maxUploadSize=500MB
├── packages.txt                 # Streamlit Cloud 自动 apt install ffmpeg
├── requirements.txt             # 就仨依赖：streamlit openai python-dotenv
├── test_game_data.py            # 12 项自动化检测
├── docs/
│   ├── PRD.md                   # 这份文档
│   ├── DEVELOPMENT_GANTT.md     # 开发甘特图
│   └── gantt-chart.html         # 甘特图可视化
└── utils/
    ├── prompts.py               # 🔥 所有 LLM prompt 模板在这里（调 prompt 只改这个）
    ├── llm_client.py            # DeepSeek API 封装 + JSON 解析 + fallback
    ├── game_renderer.py         # 游戏 HTML 渲染引擎 + validate_game_data()
    ├── game_template_v3.html    # 🔥 10 关固定机制模板（76KB，14 个 bug baked-in）
    ├── game_template.html       # 旧版 13 机制模板（已废弃，等清理）
    ├── transcript_parser.py     # 腾讯会议转写稿解析（支持 4 种格式）
    ├── video_processor.py       # FFmpeg 封装（提取音频/裁剪/合并）
    ├── asr_client.py            # Whisper ASR（延迟加载，路径 B 已废案）
    ├── mock_data.py             # Mock 数据 + 示例转写稿
    ├── session.py               # Session JSON 持久化
    └── __init__.py              # 编辑合并 + 差异对比工具
```

**核心设计原则**：三层分离。

- `prompts.py` — 纯 prompt 字符串，调 prompt 不用翻 UI 代码
- `llm_client.py` — 纯 API 调用，不依赖 Streamlit
- `app.py` — 纯 UI 渲染，不关心 LLM 怎么调

每个文件可以独立修改和测试。我经常改 prompt 的时候 Streamlit 还在跑着，改完 `prompts.py` 保存，下次处理就生效——因为 Python 的 `import` 在 Streamlit 的 rerun 循环中会重新加载。

---

## 四个阶段怎么流转的

```
st.session_state["stage"]
    ∈ {submit → processing → review → published}
```

不是真正的路由——就是 `if/elif` 四个大分支。简单粗暴但够用。

**阶段 1 (submit)**：三个输入区——文章（textarea）、词汇表（textarea + 格式检测）、转写稿（textarea 或文件上传）。年级下拉框影响 LLM prompt 里的难度等级。

**阶段 2 (processing)**：最复杂的部分。24 个微阶段（Stage 0-23），在后台线程里跑：

```python
# 简化版伪代码
thread = threading.Thread(target=run_processing)
thread.start()

# 主线程轮询状态 + 定期 st.rerun() 刷新 UI
while thread.is_alive():
    time.sleep(1)
    st.rerun()
```

每个微阶段做完一件事（验证输入、解析转写稿、调 LLM、渲染游戏 HTML 等），往 `st.session_state.logs` 里 append 一条日志，然后 `st.rerun()`。日志面板实时滚屏，100% 进度条只在全部完成后才显示——不搞虚假进度。

**阶段 3 (review)**：三栏布局。左栏反馈报告（可逐段编辑，编辑/预览模式切换，显示修改 diff），中栏高光片段列表，右栏游戏预览。修改后的内容通过 `merge_feedback_edits()` 合并回最终输出。

**阶段 4 (published)**：四个下载按钮 + 处理摘要。

---

## 几个值得讲的工程决策

### 1. 为什么从 13 种游戏机制收敛到固定 10 关

最初的设计是：LLM 从 13 种游戏机制里自选 10 关，每关可以选不同的游戏类型。结果：

- LLM 经常选重复的游戏类型（连着两关 balloon pop）
- 有些机制（连线配对 connectMatch）LLM 理解偏差，JSON 字段经常填错
- Schema 合规率不到 70%

后来改了思路：**固定 10 关顺序，LLM 只填内容词**。balloonPop → flashlight → sceneChoice → ... → scratchCard，顺序永远不变。LLM 不需要理解"什么是 connectMatch"，只需要输出 `[{word: "apple", meaning: "苹果"}, ...]`。

改了之后 Schema 合规率 100%，0 errors 0 warnings。代价是灵活性降低了——但如果老师想调整，可以在审核台逐关删除。

### 2. 14 个 baked-in bug

这 14 个 bug 是从我之前做的 11 款英语教学游戏里一个一个踩出来的，全部在 `game_template_v3.html` 模板层做了预防性修复。举三个最典型的：

1. **拖拽状态机冲突**：之前在多个元素上分别绑定 document 的 mousemove/mouseup 事件，结果拖 A 元素时 B 也跟着飞。修复：单例 `activeDragFeather` 状态机，全局只有一个拖拽实例。

2. **Canvas 每帧 Math.random()**：流星关每帧在 Canvas 上随机生成星星，requestAnimationFrame 循环里调 Math.random()——画面疯狂闪烁。修复：预渲染静态背景到离屏 canvas，只在需要变化时才重绘。

3. **关卡切换时 setInterval 泄漏**：离开关卡 A 时 `setInterval` 没清，切换到关卡 B 后 A 的定时器还在跑。修复：全局 `activeLevelCleanup` 回调 + 统一的 `addTimer`/`clearAllTimers` 管理。

### 3. Fallback 机制——API 挂了怎么办

```python
def _call_llm_with_fallback(prompt_func, mock_func, **kwargs):
    try:
        return call_deepseek(prompt_func(**kwargs))
    except (APIError, Timeout, JSONDecodeError) as e:
        st.warning(f"⚠️ API 失败: {e}，降级到 Mock 数据")
        return mock_func(**kwargs)
```

每个 LLM 调用都包了这一层。DeepSeek 超时、配额用完、返回格式解析失败——都不影响流程，自动切到 mock 数据。审核台会显示 `⚠️ Mock 降级` 标记，老师能看到。

这意味着 **Demo 永远能跑**——即使 API 挂了，也能展示完整流程和效果。

### 4. 数据验证层——LLM 和 HTML 之间的最后一道防线

`validate_game_data()` 在 HTML 渲染前逐关检查：

```python
errors = []
# 检查每关的必需字段
for level in game_data["levels"]:
    if not all(k in level for k in REQUIRED_FIELDS):
        errors.append(f"Level {level['id']} 缺少字段")
    if level["answer"] in seen_answers:
        errors.append(f"Level {level['id']} 答案重复: {level['answer']}")
    # L4 blankPattern id 必须从 0 开始
    if level["type"] == "visualSpelling":
        blank_ids = [b["id"] for b in level["blankPattern"]]
        if min(blank_ids) != 0:
            errors.append(f"L4 blankPattern id 必须从 0 开始")
```

我单独写了一个 `test_game_data.py`，12 项自动检测——可以在 CI 里跑，也可以手动 `python test_game_data.py` 快速验证 LLM 产出的 JSON 是否合规。

---

## 踩过的坑

### 坑 1：Streamlit 单线程卡 UI

LLM 调用一个 40 秒一个 100 秒，Streamlit 默认同步执行——UI 完全冻结。用户看着进度条不动以为死机了。

**解决**：`threading.Thread` 把处理逻辑扔到后台线程，主线程每秒 `st.rerun()` 刷新 UI。问题是 `st.rerun()` 会重置 Python 的局部变量——所以处理状态全部存在 `st.session_state` 里（它是 per-session 持久化的）。

### 坑 2：Prompt 里"避免空泛"是句废话

给 LLM 说"不要空泛"——它不知道什么叫空泛。后来改成给正反例对比：

```
❌ 差：“Tom 表现得很好，继续加油。”
✅ 好：“Tom 在 /er/ 发音练习中准确率达到 80%，尤其在 'teacher'
   和 'river' 两个词上发音清晰。下次可以多练习 'burger' 的重音位置。”
```

并且加了三条硬规则：每个学生的评语必须包含至少一个具体例子 + 覆盖发音/词汇/课堂参与三个维度 + 六年级以上禁用"很棒""真厉害"等幼龄化表达。

### 坑 3：LLM 产出的 blankPattern id 从 1 开始

L4 visualSpelling 需要标注哪些字母位置是空格（让学生填），`id` 是 JS 里用来定位 DOM 元素的索引。LLM 习惯性 id 从 1 开始——但 JS 数组索引从 0 开始。渲染出来全是错位的。

**解决**：在 `validate_game_data()` 里加了硬检测——`if min(blank_ids) != 0: raise`。并且 prompt 里明确写了 `blankPattern.id 从 0 开始编号`。

### 坑 4：VPN + Git push GitHub 连不上

Windows 上 Git Bash 用的 HTTPS 走 443 端口，开了 VPN 反而被拦。解决方案是关 `sslVerify` 或者切 SSH（走 22 端口）。记得 push 完恢复 `sslVerify`。

---

## 部署指南

### 本地跑

```powershell
cd C:\Users\23899\Projects\post-class-workflow
cp .env.example .env          # 编辑 .env，填 DeepSeek API Key
pip install -r requirements.txt
streamlit run app.py
```

浏览器打开 `http://localhost:8501`。

### 部署到 Streamlit Cloud（给老师用）

1. Push 代码到 GitHub（已完成）
2. 打开 [streamlit.io/cloud](https://streamlit.io/cloud)，用 GitHub 登录
3. New app → 选 `s1148071-pixel/post-class-workflow` → main 分支 → `app.py`
4. Advanced settings → Secrets：
   ```
   DEEPSEEK_API_KEY = sk-xxx
   DEEPSEEK_BASE_URL = https://api.deepseek.com/v1
   ```
5. Deploy。几分钟后拿到 `xxx.streamlit.app` 链接，发给老师即可

**注意**：Streamlit Cloud 免费版有资源限制（1GB RAM，不保证 CPU）。如果处理慢，考虑切到 Hugging Face Spaces（Docker 环境，更灵活）。

---

## 当前状态和接下来要做的

### 已就绪

- ✅ 核心管线（提交 → 处理 → 审核 → 发布）完整可用
- ✅ 反馈报告：支持逐段编辑、预览模式、修改 diff
- ✅ 游戏生成：10 关固定机制，schema 合规率 100%
- ✅ 转写稿解析：支持 4 种腾讯会议格式
- ✅ API fallback：失败自动降级 mock 数据
- ✅ Git + 部署配置就绪

### 短期（Demo 前，优先级 P0）

| 事项 | 负责 | 预估 |
|------|:--:|:--:|
| 移动端触摸实测（L7 流星/L9 拖拽/L10 刮刮卡） | 我 | 30min |
| Streamlit Cloud 连接上线 | 我 | 30min |
| 端到端走查：粘贴→处理→审核→下载 | 我+老师 | 30min |

### 中期（试用反馈驱动，P1-P2）

- **处理速度优化**：当前 ~140 秒（40s 反馈 + 100s 游戏）。方向：流式输出（`stream=True`）、切更快模型、模板预编译
- **反馈报告空泛问题**：无转写稿时从文章+词汇表提取更多差异化信号。现在的 prompt 已经做了正反例，但还有调优空间
- **批量操作**：如果老师一次要给多个学生用，需要批量导入+批量处理
- **游戏关卡可配置**：老师可选择开启/关闭某些关卡类型

### 长期（产品化，P3）

- 学生账号体系 + 游戏成绩回传 → 老师看到完整学习闭环
- 拍照 OCR 输入（识别黑板/课本内容，减少手动输入）
- 多语言扩展

### 技术债务（有空就清）

- `utils/asr_client.py` 里 Whisper 代码留着没删——虽然延迟加载不会影响运行，但容易误导新接手的同事
- `utils/game_template.html`（72KB 旧版 13 机制模板）已被 v3 替代，该归档或删除
- 日志面板的 24 个微阶段，有些 <0.1s 的纯内存操作和 100s 的 LLM 调用混在一起显示——建议加权重分级，让用户感知更真实

---

## 如果有同事想接着搞

**改 prompt**：只动 `utils/prompts.py`，三个函数：
- `FEEDBACK_SYSTEM_PROMPT` — 反馈报告
- `HOMEWORK_SYSTEM_PROMPT` — 游戏 JSON
- `HIGHLIGHT_SYSTEM_PROMPT` — 高光片段

**改游戏模板**：`utils/game_template_v3.html`，76KB 纯 HTML/CSS/JS。结构是 `{{GAME_DATA}}` 占位符 + JS 动态渲染。改之前建议先读一下 `english-game` 仓库里的 HANDOFF.md 和 `_edu-game-checklist.md`。

**加新功能**：在 `app.py` 的对应 stage 分支里加。如果加新的 LLM 调用，参考 `llm_client.py` 里的 `_call_llm_with_fallback()` 模式。

**调 bug**：先跑 `python test_game_data.py` 确认不是游戏数据的问题，然后看 Streamlit 的日志输出（处理阶段的所有日志都在 `st.session_state.logs` 里，审查时也能看到）。

---

## 最后

这个项目从 6 月初的需求文档到现在的 v1，大概一个半月。中间推翻过两次架构（游戏模板从 LLM 直出 → 模板注入，游戏机制从 13 种灵活 → 10 关固定），也踩了不少 DeepSeek prompt 的坑。

如果技术部有同事想一起搞或者接手维护，随时找我聊。项目不大（~2700 行核心代码 + 76KB 模板），一个下午能看完。

— Donovan
