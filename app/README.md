# AI Paper Reviewer Web MVP

本目录是一个本地网页版本，用来把 `academic-research-skills-main/academic-paper-reviewer` 中的多 agent 审稿流程放到浏览器界面里。

## 启动

```bash
git clone https://github.com/xtsun0419/AI-Scientist-Workflow.git
cd AI-Scientist-Workflow
python3 app/server.py
```

打开：

```text
http://127.0.0.1:8765
```

## 支持输入

- `.txt`
- `.md`
- `.docx`
- `.pdf`

当前前端只保留文件上传，不再支持粘贴文本。

## 当前能力

- Field Analyst 自动识别领域、方法类型、稿件成熟度，并配置评审团队。
- 5 个评审角色独立输出意见：
  - Editor-in-Chief
  - Methodology Reviewer
  - Domain Reviewer
  - Perspective Reviewer
  - Devil's Advocate
- Editorial Synthesizer 汇总决策和修改路线图。
- 默认使用后端 `app/config.json` 中的 OpenAI-compatible API 配置，适合获得实质性审稿内容。
- `流程演示 / Local demo` 只用于无 API key 时检查界面和流程，不代表真正的全文深读审稿。
- 具体评审意见、问题、修改建议和 revision roadmap 默认使用中文输出；题目、角色名、方法名和技术术语可保留中英并列。
- 前端以可视化 HTML 报告展示评审结果，不再直接显示纯 Markdown。
- 支持下载 Markdown 和 PDF；PDF 由后端使用 XeLaTeX 生成，适合阅读和分享。
- 评审运行采用后台任务 + 前端轮询。每个 agent 开始、完成或失败都会单独更新卡片状态。
- 评审完成后可继续生成“修改计划 / Revision Plan”，由后端读取原始论文和 Markdown 评审结果，再以前端泳道流程图展示。

## 接真实 LLM

推荐把 API Key 放在后端配置文件，不从前端输入。

复制并编辑：

```bash
cp app/config.example.json app/config.json
```

然后在 `app/config.json` 中填写：

- API Base URL
- API Key
- Model

`app/config.json` 已加入 `.gitignore`，避免误提交 key。前端不显示 API Key、Base URL 或模型输入框，凭据只保存在后端配置或本机环境变量中。

也可以启动服务前设置 OpenAI-compatible 环境变量作为默认值：

```bash
export OPENAI_API_KEY="..."
export OPENAI_BASE_URL="https://api.openai.com/v1"
export OPENAI_MODEL="gpt-4o-mini"
python3 app/server.py
```

后端会读取现有 agent prompt 文件：

```text
academic-research-skills-main/academic-paper-reviewer/agents/
```

这样后续改 prompt 不需要改前端。

LLM 分支也会显式要求模型用中文写具体评审意见，同时允许标题、角色名和技术术语中英并列。

## 修改计划

点击“继续生成修改计划”后，系统会调用第二组写作/修改 agents：

- Revision Intake：把多 agent 评审意见拆成可执行问题清单。
- Structure Architect：规划章节结构和论证顺序调整。
- Argument Builder：收紧核心论点和贡献表达。
- Citation Compliance：标出证据、引用和作者必须补充的信息。
- Revision Coach：综合生成可视化修改流程。

这一阶段使用后台保存的 Markdown 评审结果，不读取 PDF。PDF 只作为人工阅读和分享格式。

## SSL 证书错误

如果出现：

```text
CERTIFICATE_VERIFY_FAILED
```

这通常不是 API Key 问题，而是本机 Python 不信任服务端证书链、代理/VPN 替换证书，或服务端证书链不完整。

更稳妥的处理：

- 在 `app/config.json` 设置 `ca_bundle` 为可信 CA 文件路径。
- 检查代理/VPN 是否在做 HTTPS 证书替换。
- 本地调试时可临时设置 `"verify_ssl": false`，但不建议长期使用。

## PDF 导出

PDF 导出依赖本机 `xelatex`。当前模板使用 `ctexart`、`xeCJK` 和 `PingFang SC`，在 macOS 上已通过 smoke test。点击网页上的“下载 PDF”会把最近一次评审结果发送给后端生成 PDF。

## 置信度说明

置信度是每个评审角色对“自己这份判断可靠程度”的自评，1-5 分。它主要受角色专业匹配度、稿件信息完整度、证据可见性影响。它不是论文通过概率，也不是模型准确率。
