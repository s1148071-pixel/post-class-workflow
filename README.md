# 课后输出工作台

AI 驱动的英语课后内容生成工具。老师上完课，粘贴文章和词汇表，AI 自动生成三样东西：**课后反馈报告**、**学生高光视频剪辑列表**、**交互式 HTML 课后游戏作业**。老师在审核台编辑确认后，一键发布下载。

## 运行方式

```bash
# 1. 克隆项目
cd post-class-workflow

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置 API Key
cp .env.example .env
# 编辑 .env，填入你的 DeepSeek API Key

# 4. 启动
streamlit run app.py
```

浏览器打开 `http://localhost:8501`。

## 线上部署

项目已配置为 Streamlit Community Cloud 一键部署：

1. Fork / 克隆本项目到你的 GitHub
2. 在 [Streamlit Cloud](https://streamlit.io/cloud) 连接仓库
3. 在 Streamlit Secrets 中配置：
   - `DEEPSEEK_API_KEY` = `sk-your-key-here`
   - `DEEPSEEK_BASE_URL` = `https://api.deepseek.com/v1`
4. 部署完成，获得公开链接供老师使用

> **注意**：视频高光功能需要 FFmpeg（通过 `packages.txt` 自动安装）。主要使用路径为粘贴腾讯会议转写稿，无需上传视频。

## 功能流程

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ ① 提交   │ → │ ② AI处理 │ → │ ③ 审核   │ → │ ④ 发布   │
│ 文章+词汇 │    │ 24微阶段 │    │ 三栏编辑台│    │ 下载输出  │
└──────────┘    └──────────┘    └──────────┘    └──────────┘
```

### ① 提交素材
- 老师姓名、学生年级
- 课堂文章 / 课文
- 词汇表（英文 + 中文释义，每行一个）
- 课堂录屏（可选，Demo 阶段使用 Mock 数据）

### ② AI 处理
- DeepSeek v4-pro 并行处理三项任务
- 反馈报告约 40 秒，游戏作业约 100 秒
- 24 微阶段滚动日志面板，旋转加载动画
- API 失败自动降级到 Mock 数据

### ③ 审核编辑台
- 左栏：反馈报告（编辑/预览模式切换、逐段修改、修改摘要）
- 中栏：视频高光剪辑（AI 推荐片段 + 手动添加）
- 右栏：课后游戏作业（关卡预览、逐关删除）

### ④ 发布输出
- 反馈报告 `.txt`
- 高光剪辑列表 `.json`
- **课后游戏 HTML**（学生手机直接打开玩）

## 游戏作业

AI 生成 **10 关固定机制** 的交互式英语游戏，单文件 HTML，移动端优先。

| 关卡 | 类型 | 技能 |
|:--:|------|------|
| 1 | 🎈 气球挑战 | 词义匹配 |
| 2 | 🔦 暗夜搜寻 | 图标识别 |
| 3 | 🤔 情景辨析 | 看图标选词 |
| 4 | ✏️ 视觉拼写 | 补全单词 |
| 5 | 🧩 字母拼图 | 按序拼词 |
| 6 | 🃏 记忆配对 | 图文匹配 |
| 7 | 🌠 接流星 | 快速识别 |
| 8 | ⭐ 星座连线 | 拼写顺序 |
| 9 | 🪶 捕梦网 | 拖拽拼词 |
| 10 | 🪄 刮刮卡 | 综合回顾 |

游戏模板基于 11 款已交付英语教学游戏的实战经验，14 个已知 bug 在模板层 baked-in 修复。

## 项目结构

```
post-class-workflow/
├── app.py                    # Streamlit 主应用（4 阶段状态机）
├── test_game_data.py         # 游戏数据验证工具（12 项自动检测）
├── requirements.txt          # Python 依赖
├── .env.example              # 环境变量模板
├── README.md
└── utils/
    ├── prompts.py            # Prompt 模板（反馈 + 作业 + 高光）
    ├── llm_client.py         # DeepSeek API 封装（含 fallback）
    ├── game_renderer.py      # 游戏 HTML 渲染引擎 + 数据验证
    ├── game_template_v3.html # 游戏模板（10 关固定机制）
    ├── mock_data.py          # Mock 数据（Demo / fallback）
    ├── session.py            # Session JSON 持久化
    └── __init__.py           # 编辑合并 + 差异对比工具
```

## 架构设计

### 三层分离
- `prompts.py` → 构建 LLM messages（调 prompt 只改这个文件）
- `llm_client.py` → 调 API + 解析 JSON + fallback
- `app.py` → 渲染 Streamlit UI

### 四阶段状态机
`st.session_state["stage"]` ∈ `{submit, processing, review, published}`

### Fallback 机制
API 调用失败自动降级到 `mock_data.py`，审核台显示 `Mock 降级` 标记，确保 Demo 随时可跑。

### 游戏数据验证
`validate_game_data()` 在 HTML 渲染前逐关检查：字段完整性、词汇覆盖率、答案去重、blankPattern id 编号。`test_game_data.py` 提供 12 项自动化检测。

## 技术栈

- **前端**：Streamlit 1.57
- **LLM**：DeepSeek v4-pro（直连 api.deepseek.com/v1）
- **游戏模板**：纯 HTML/CSS/JS，零外部依赖，10 关固定机制
- **发音**：有道 dictvoice API
- **视频**：FFmpeg（高光剪辑）
- **ASR**：腾讯会议转写稿解析（路径 A，主力方案）
- **部署**：Streamlit Cloud

## 开发阶段

| Phase | 内容 | 状态 |
|-------|------|:--:|
| 0 | 需求确认 + 流程图 | ✅ |
| 1 | Streamlit 审核台骨架 | ✅ |
| 2 | LLM 处理管线 | ✅ |
| 2b | Prompt 质量调优 | ✅ |
| 3 | 反馈报告审核编辑 | ✅ |
| 4 | 视频高光 + FFmpeg | ✅ v1 |
| 5 | 作业 HTML 游戏化 | ✅ v3 |
| 5c | LLM 联调验证 | ✅ |
| — | Git 初始化 + 部署配置 | ✅ |
| 5b | 模板浏览器实测 | 🟡 |
| 6 | 内部试用 | ⬜ |
