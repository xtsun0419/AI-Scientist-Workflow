# AI Paper Reviewer

本项目是一个本地网页应用，用于上传论文初稿，并通过 `academic-research-skills-main` 中的多 agent 学术评审流程生成中文评审意见。

## 功能

- 上传 `.txt`、`.md`、`.docx`、`.pdf` 初稿文件
- 后端读取 `app/config.json` 中的 OpenAI-compatible LLM 配置
- 多 agent 逐步运行可视化
- HTML 可视化评审报告
- 导出 Markdown 和 PDF
- 评审完成后继续生成可视化论文修改计划

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

## 配置

复制模板：

```bash
cp app/config.example.json app/config.json
```

然后编辑 `app/config.json`，填入你的 API key、base URL 和模型名。

`app/config.json` 已被 `.gitignore` 忽略，不会提交到 GitHub。

## 修改计划工作流

第一阶段完成评审后，网页会出现“继续生成修改计划”按钮。第二阶段会读取后台保存的原始论文文本和 Markdown 评审结果，生成结构化修改计划，并以泳道流程图展示。

PDF 报告主要面向人工阅读；系统内部不会把 PDF 作为下一阶段 agents 的输入。

更多说明见 [app/README.md](app/README.md)。
