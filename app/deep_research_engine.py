from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from reviewer_engine import call_chat_completion


ROOT = Path(__file__).resolve().parents[1]
AGENT_ROOT = ROOT / "academic-research-skills-main" / "deep-research" / "agents"


DEEP_RESEARCH_AGENT_FILES = {
    "research_question": "research_question_agent.md",
    "research_architect": "research_architect_agent.md",
    "bibliography": "bibliography_agent.md",
    "synthesis": "synthesis_agent.md",
    "report_compiler": "report_compiler_agent.md",
}


DEEP_RESEARCH_ROLE_LABELS = {
    "research_question": "研究问题 / Research Question",
    "research_architect": "研究设计 / Research Architect",
    "bibliography": "文献策略 / Bibliography",
    "synthesis": "综合框架 / Synthesis",
    "report_compiler": "报告大纲 / Report Compiler",
}


def load_deep_agent_prompt(agent_id: str) -> str:
    return (AGENT_ROOT / DEEP_RESEARCH_AGENT_FILES[agent_id]).read_text(encoding="utf-8")


def emit_progress(progress: Any, agent_id: str, status: str, **extra: Any) -> None:
    if progress:
        progress(agent_id, status, **extra)


def run_deep_research(topic: str, options: dict[str, Any] | None = None, progress: Any = None) -> dict[str, Any]:
    options = options or {}
    topic = normalize_topic(topic)
    provider = options.get("provider") or os.environ.get("AI_REVIEWER_PROVIDER", "heuristic")
    if provider == "openai":
        return run_llm_deep_research(topic, options, progress=progress)
    return run_heuristic_deep_research(topic, options, progress=progress)


def normalize_topic(topic: str) -> str:
    topic = re.sub(r"\s+", " ", topic or "").strip()
    if len(topic) < 20:
        raise ValueError("请至少输入 20 个字符的研究主题、想法或背景。")
    return topic


def run_llm_deep_research(topic: str, options: dict[str, Any], progress: Any = None) -> dict[str, Any]:
    base_url = options.get("base_url") or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")
    model = options.get("model") or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    api_key = options.get("api_key") or os.environ.get("OPENAI_API_KEY", "")
    disable_proxy = bool(options.get("disable_proxy", False))
    verify_ssl = bool(options.get("verify_ssl", True))
    ca_bundle = options.get("ca_bundle") or os.environ.get("SSL_CERT_FILE", "")
    mode = options.get("mode") or "research-plan"
    if not api_key:
        raise ValueError("后端没有配置 API Key。请在 app/config.json 中配置 api_key，或设置环境变量 OPENAI_API_KEY。")

    shared_instruction = (
        "Output language requirement: write concrete research guidance in Chinese. "
        "Keep agent names, method names, databases, and key technical terms bilingual when helpful.\n"
        "Do not fabricate citations, DOI, data, or evidence. If a real literature search is required, provide search strings, databases, and source-selection criteria instead of fake references.\n"
        "This is an MVP Deep Research workflow. Produce the assigned phase deliverable only.\n\n"
        f"Mode: {mode}\nResearch topic / user idea:\n{topic}"
    )

    outputs: dict[str, str] = {}
    agents = []
    for agent_id in DEEP_RESEARCH_AGENT_FILES:
        emit_progress(progress, agent_id, "running", message=f"{DEEP_RESEARCH_ROLE_LABELS[agent_id]} 正在分析")
        prompt = load_deep_agent_prompt(agent_id)
        upstream = "\n\n---\n\n".join(f"# {DEEP_RESEARCH_ROLE_LABELS[key]}\n{value}" for key, value in outputs.items())
        content = call_chat_completion(
            base_url=base_url,
            api_key=api_key,
            model=model,
            disable_proxy=disable_proxy,
            verify_ssl=verify_ssl,
            ca_bundle=ca_bundle,
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": (
                        f"{shared_instruction}\n\n"
                        f"Upstream phase outputs:\n{upstream or '(none yet)'}\n\n"
                        "Please produce only your assigned Deep Research phase output."
                    ),
                },
            ],
        )
        outputs[agent_id] = content
        agents.append(
            {
                "id": agent_id,
                "label": DEEP_RESEARCH_ROLE_LABELS[agent_id],
                "status": "complete",
                "recommendation": "完成",
                "confidence": 4,
                "markdown": content,
            }
        )
        emit_progress(progress, agent_id, "complete", recommendation="完成", confidence=4)

    workflow = build_workflow(topic, agents)
    return {
        "provider": "openai",
        "mode": mode,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "topic": topic,
        "agents": agents,
        "workflow": workflow,
        "markdown": build_deep_markdown(topic, agents),
    }


def run_heuristic_deep_research(topic: str, options: dict[str, Any], progress: Any = None) -> dict[str, Any]:
    mode = options.get("mode") or "research-plan"
    agents = []
    for agent_id in DEEP_RESEARCH_AGENT_FILES:
        emit_progress(progress, agent_id, "running", message=f"{DEEP_RESEARCH_ROLE_LABELS[agent_id]} 正在生成本地规划")
        markdown = heuristic_agent_output(agent_id, topic)
        agents.append(
            {
                "id": agent_id,
                "label": DEEP_RESEARCH_ROLE_LABELS[agent_id],
                "status": "complete",
                "recommendation": "完成",
                "confidence": 3,
                "markdown": markdown,
            }
        )
        emit_progress(progress, agent_id, "complete", recommendation="完成", confidence=3)
    workflow = build_workflow(topic, agents)
    return {
        "provider": "heuristic",
        "mode": mode,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "topic": topic,
        "agents": agents,
        "workflow": workflow,
        "markdown": build_deep_markdown(topic, agents),
    }


def heuristic_agent_output(agent_id: str, topic: str) -> str:
    if agent_id == "research_question":
        return f"""# 研究问题简报 / Research Question Brief

## 初始主题
{topic}

## 可研究主问题
围绕该主题，优先将问题收束为：在特定对象、场景和时间范围内，某一机制、策略或现象如何影响关键结果。

## FINER 初评
| 维度 | 判断 |
|---|---|
| Feasible | 需要明确可获取的数据、文献范围或案例材料 |
| Interesting | 主题具有现实和理论价值，但需要找到具体争议 |
| Novel | 新意取决于情境、对象或方法组合 |
| Ethical | 需要检查隐私、偏见和受影响群体 |
| Relevant | 需要说明对政策、实践或理论的贡献 |

## 建议下一步
- 明确研究对象、地区、时间范围和主要结果变量。
- 写出 2-3 个子问题，用于后续文献检索和分析。"""
    if agent_id == "research_architect":
        return """# 方法蓝图 / Methodology Blueprint

## 推荐设计
- 如果目标是解释机制：采用理论导向的文献综述或多案例比较。
- 如果目标是评估效果：优先考虑系统综述、准实验或统计建模。
- 如果目标是生成框架：采用 scoping review + thematic synthesis。

## 数据策略
- 学术数据库：Web of Science、Scopus、ERIC、PubMed、Google Scholar。
- 纳入标准：同行评审、主题高度相关、方法透明、近年核心研究。
- 排除标准：来源不清、证据不足、与研究问题仅弱相关。

## 效度控制
- 明确概念定义。
- 记录检索式和筛选流程。
- 对冲突证据单独建表。"""
    if agent_id == "bibliography":
        return """# 文献检索策略 / Search Strategy

## 检索式模板
| 组 | 示例 |
|---|---|
| 核心概念 | topic keywords OR synonyms |
| 对象/场景 | population OR context |
| 结果/机制 | outcome OR mechanism |

## 数据库
- Web of Science / Scopus：核心学术网络。
- Google Scholar：补充灰色线索。
- 领域数据库：按学科选择 ERIC、PubMed、IEEE Xplore 等。

## 输出
- 检索记录表。
- 初筛/复筛理由。
- 注释书目，不编造真实引用。"""
    if agent_id == "synthesis":
        return """# 综合框架 / Synthesis Framework

## 初步主题轴
1. 概念定义与边界。
2. 主要机制或解释路径。
3. 支持证据与反向证据。
4. 方法差异导致的结论差异。
5. 研究空白和未来方向。

## 冲突处理
- 区分真实矛盾、场景差异、方法差异和证据质量差异。
- 对每个核心结论标注证据强度。"""
    return """# 报告结构 / Report Outline

## 建议结构
1. 摘要：研究目的、方法、核心发现、贡献。
2. 引言：问题背景、研究缺口、研究问题。
3. 方法：检索策略、纳入排除标准、分析方法。
4. 发现：按主题综合证据。
5. 讨论：理论贡献、实践意义、限制。
6. 结论：回答研究问题并提出下一步研究。

## 写作原则
- 每个主张必须对应证据。
- 没有证据的地方标记为材料缺口，而不是补写。"""


def build_workflow(topic: str, agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    objectives = {
        "research_question": "把宽泛想法压缩成可研究问题和边界。",
        "research_architect": "确定方法、数据策略和质量控制。",
        "bibliography": "形成可复现的检索策略和筛选标准。",
        "synthesis": "规划跨来源综合、冲突处理和研究空白映射。",
        "report_compiler": "生成可写作的研究报告结构。",
    }
    return [
        {
            "id": agent["id"],
            "label": agent["label"],
            "phase": index,
            "objective": objectives.get(agent["id"], ""),
            "summary": summarize_markdown(agent.get("markdown", "")),
            "status": "complete",
        }
        for index, agent in enumerate(agents, start=1)
    ]


def summarize_markdown(markdown: str) -> str:
    lines = [line.strip(" -#\t") for line in markdown.splitlines() if line.strip()]
    useful = [line for line in lines if len(line) >= 18 and not line.startswith("|")]
    return useful[0][:180] if useful else "该阶段已完成。"


def build_deep_markdown(topic: str, agents: list[dict[str, Any]]) -> str:
    sections = [f"# Deep Research Plan\n\n**Topic**: {topic}"]
    sections.extend(f"# {agent['label']}\n\n{agent.get('markdown', '')}" for agent in agents)
    return "\n\n---\n\n".join(sections)
