# AI Paper Reviewer

本项目是一个本地网页应用，用于上传论文初稿，并通过 `academic-research-skills-main` 中的多 agent 学术评审流程生成中文评审意见。

## 功能

- 上传 `.txt`、`.md`、`.docx`、`.pdf` 初稿文件
- 后端读取 `app/config.json` 中的 OpenAI-compatible LLM 配置
- 多 agent 逐步运行可视化
- HTML 可视化评审报告
- 导出 Markdown 和 PDF

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

更多说明见 [app/README.md](app/README.md)。
