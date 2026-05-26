from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from reviewer_engine import (
    analyze_manuscript,
    call_chat_completion,
    profile_to_dict,
)


ROOT = Path(__file__).resolve().parents[1]
ACADEMIC_PAPER_AGENT_ROOT = ROOT / "academic-research-skills-main" / "academic-paper" / "agents"


REVISION_AGENT_FILES = {
    "structure_architect": "structure_architect_agent.md",
    "argument_builder": "argument_builder_agent.md",
    "citation_compliance": "citation_compliance_agent.md",
    "revision_coach": "revision_coach_agent.md",
}


REVISION_ROLE_LABELS = {
    "revision_intake": "评审解析 / Revision Intake",
    "structure_architect": "结构设计 / Structure Architect",
    "argument_builder": "论证强化 / Argument Builder",
    "citation_compliance": "证据引用 / Citation Compliance",
    "revision_coach": "修改教练 / Revision Coach",
}


LANE_LABELS = {
    "diagnosis": "问题诊断 / Diagnosis",
    "structure": "结构重组 / Structure",
    "argument": "论证强化 / Argument",
    "evidence": "证据与引用 / Evidence",
    "writing": "写作执行 / Writing",
    "response": "回复审稿 / Response",
}


def load_revision_agent_prompt(agent_id: str) -> str:
    filename = REVISION_AGENT_FILES[agent_id]
    return (ACADEMIC_PAPER_AGENT_ROOT / filename).read_text(encoding="utf-8")


def emit_progress(progress: Any, agent_id: str, status: str, **extra: Any) -> None:
    if progress:
        progress(agent_id, status, **extra)


def build_review_markdown(review_result: dict[str, Any]) -> str:
    agents = review_result.get("agents") or []
    return "\n\n---\n\n".join(
        f"# {agent.get('label') or agent.get('id')}\n\n{agent.get('markdown') or ''}".strip()
        for agent in agents
    )


def review_result_from_markdown(markdown: str, title: str = "Imported Review Report") -> dict[str, Any]:
    markdown = markdown.strip()
    sections = split_review_markdown(markdown)
    agents = []
    for index, section in enumerate(sections, start=1):
        label = section["label"] or f"Imported Review Section {index}"
        recommendation = extract_imported_recommendation(section["markdown"])
        agents.append(
            {
                "id": f"imported_{index}",
                "label": label,
                "status": "complete",
                "recommendation": recommendation,
                "confidence": 4,
                "markdown": section["markdown"],
            }
        )
    if not agents:
        agents.append(
            {
                "id": "imported_review",
                "label": "Imported Review Report",
                "status": "complete",
                "recommendation": extract_imported_recommendation(markdown),
                "confidence": 4,
                "markdown": markdown,
            }
        )
    decision = extract_imported_recommendation(markdown)
    return {
        "provider": "imported-markdown",
        "mode": "imported",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "profile": {"title": title},
        "agents": agents,
        "summary": {
            "decision": decision,
            "confidence": 4,
            "markdown": markdown,
        },
    }


def split_review_markdown(markdown: str) -> list[dict[str, str]]:
    chunks = [chunk.strip() for chunk in re.split(r"\n\s*---+\s*\n", markdown) if chunk.strip()]
    sections = []
    for chunk in chunks:
        heading = re.search(r"^\s*#\s+(.+)$", chunk, re.M)
        label = heading.group(1).strip() if heading else ""
        sections.append({"label": label, "markdown": chunk})
    return sections


def extract_imported_recommendation(markdown: str) -> str:
    text = markdown or ""
    patterns = [
        ("Reject", [r"\bReject\b", "拒稿", "拒绝", "退稿", "不建议接收"]),
        ("Major Revision", [r"\bMajor Revision\b", "大修", "重大修改", "大幅修改"]),
        ("Minor Revision", [r"\bMinor Revision\b", "小修", "轻微修改"]),
        ("Accept", [r"\bAccept\b", "接收", "接受", "录用"]),
    ]
    for rec, rec_patterns in patterns:
        if any(re.search(pattern, text, re.I) for pattern in rec_patterns):
            return rec
    return "Major Revision"


def run_revision_plan(
    manuscript_text: str,
    review_result: dict[str, Any],
    options: dict[str, Any] | None = None,
    progress: Any = None,
) -> dict[str, Any]:
    options = options or {}
    provider = options.get("provider") or "heuristic"
    profile = analyze_manuscript(manuscript_text)
    review_markdown = build_review_markdown(review_result)
    if provider == "openai":
        return run_llm_revision_plan(
            manuscript_text=manuscript_text,
            review_markdown=review_markdown,
            review_result=review_result,
            profile=profile,
            options=options,
            progress=progress,
        )
    return run_heuristic_revision_plan(
        manuscript_text=manuscript_text,
        review_markdown=review_markdown,
        review_result=review_result,
        profile=profile,
        progress=progress,
    )


def run_llm_revision_plan(
    manuscript_text: str,
    review_markdown: str,
    review_result: dict[str, Any],
    profile: Any,
    options: dict[str, Any],
    progress: Any = None,
) -> dict[str, Any]:
    base_url = (options.get("base_url") or "https://api.openai.com/v1").rstrip("/")
    model = options.get("model") or "gpt-4o-mini"
    api_key = options.get("api_key") or ""
    disable_proxy = bool(options.get("disable_proxy", False))
    verify_ssl = bool(options.get("verify_ssl", True))
    ca_bundle = options.get("ca_bundle") or ""
    if not api_key:
        raise ValueError("后端没有配置 API Key。请在 app/config.json 中配置 api_key，或设置环境变量 OPENAI_API_KEY。")

    shared_context = (
        "请使用中文生成具体修改计划；标题、角色名和必要技术术语可中英并列。\n"
        "禁止编造不存在的数据、实验结果、统计显著性或文献。遇到需要作者补充的信息，请明确标为作者输入。\n\n"
        f"Manuscript title: {profile.title}\n"
        f"Manuscript profile: {json.dumps(profile_to_dict(profile), ensure_ascii=False)}\n\n"
        f"Original manuscript excerpt:\n{manuscript_text[:36000]}\n\n"
        f"Multi-agent review report Markdown:\n{review_markdown[:42000]}"
    )

    emit_progress(progress, "revision_intake", "running", message="正在把评审意见拆解为可执行问题")
    intake_md = call_chat_completion(
        base_url=base_url,
        api_key=api_key,
        model=model,
        disable_proxy=disable_proxy,
        verify_ssl=verify_ssl,
        ca_bundle=ca_bundle,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are Revision Intake Analyst. Convert peer-review comments into a prioritized revision backlog. "
                    "Group items by fatal/major/minor, identify dependencies, and mark issues that require author-supplied evidence."
                ),
            },
            {"role": "user", "content": shared_context},
        ],
    )
    emit_progress(progress, "revision_intake", "complete", recommendation="问题清单完成", confidence=4)

    analyses: dict[str, str] = {"revision_intake": intake_md}
    for agent_id in ["structure_architect", "argument_builder", "citation_compliance"]:
        emit_progress(progress, agent_id, "running", message=f"{REVISION_ROLE_LABELS[agent_id]} 正在规划")
        prompt = load_revision_agent_prompt(agent_id)
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
                        "请只输出与你角色相关的修改策略，使用中文，避免全文重写。\n\n"
                        f"Revision backlog:\n{intake_md[:16000]}\n\n{shared_context}"
                    ),
                },
            ],
        )
        analyses[agent_id] = content
        emit_progress(progress, agent_id, "complete", recommendation="策略完成", confidence=4)

    emit_progress(progress, "revision_coach", "running", message="正在综合为可视化修改流程")
    final_prompt = load_revision_agent_prompt("revision_coach")
    final_json = call_chat_completion(
        base_url=base_url,
        api_key=api_key,
        model=model,
        disable_proxy=disable_proxy,
        verify_ssl=verify_ssl,
        ca_bundle=ca_bundle,
        messages=[
            {"role": "system", "content": final_prompt},
            {
                "role": "user",
                "content": build_final_plan_prompt(
                    manuscript_title=profile.title,
                    review_result=review_result,
                    analyses=analyses,
                ),
            },
        ],
    )
    plan = parse_plan_json(final_json)
    plan = normalize_plan(plan, profile.title, review_result)
    markdown = plan_to_markdown(plan)
    emit_progress(progress, "revision_coach", "complete", recommendation="修改计划完成", confidence=4)

    return {
        "provider": "openai",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "profile": profile_to_dict(profile),
        "source_review": {
            "decision": (review_result.get("summary") or {}).get("decision", ""),
            "confidence": (review_result.get("summary") or {}).get("confidence", ""),
        },
        "agents": [
            {
                "id": agent_id,
                "label": REVISION_ROLE_LABELS[agent_id],
                "status": "complete",
                "markdown": analyses[agent_id],
            }
            for agent_id in ["revision_intake", "structure_architect", "argument_builder", "citation_compliance"]
        ]
        + [
            {
                "id": "revision_coach",
                "label": REVISION_ROLE_LABELS["revision_coach"],
                "status": "complete",
                "markdown": final_json,
            }
        ],
        "plan": plan,
        "markdown": markdown,
    }


def build_final_plan_prompt(
    manuscript_title: str,
    review_result: dict[str, Any],
    analyses: dict[str, str],
) -> str:
    decision = (review_result.get("summary") or {}).get("decision", "")
    return f"""请把以下多 agent 修改分析综合为一个“可视化流程图”友好的修改计划。

输出必须是合法 JSON，不能使用 Markdown 代码块，不能添加 JSON 外的说明文字。

JSON schema:
{{
  "title": "中文标题",
  "decision_context": "来自上一轮审稿的总体判断",
  "priority_summary": "一句话概括最优先修改方向",
  "lanes": [
    {{"id": "diagnosis", "label": "问题诊断 / Diagnosis"}},
    {{"id": "structure", "label": "结构重组 / Structure"}},
    {{"id": "argument", "label": "论证强化 / Argument"}},
    {{"id": "evidence", "label": "证据与引用 / Evidence"}},
    {{"id": "writing", "label": "写作执行 / Writing"}},
    {{"id": "response", "label": "回复审稿 / Response"}}
  ],
  "nodes": [
    {{
      "id": "P1",
      "phase": 1,
      "lane": "diagnosis",
      "title_zh": "短标题",
      "title_en": "Short English title",
      "priority": "Critical | Major | Minor",
      "objective": "这个节点要解决什么问题",
      "actions": ["动作1", "动作2"],
      "evidence_from_review": "来自评审意见的依据",
      "manuscript_target": "对应原文位置或章节",
      "depends_on": [],
      "deliverable": "完成后产物",
      "owner_agent": "负责该节点的 agent 名称"
    }}
  ],
  "timeline": [
    {{"stage": "第1轮", "focus": "本轮重点", "node_ids": ["P1", "P2"]}}
  ],
  "author_inputs": [
    {{"needed_for": "P3", "item": "需要作者提供的真实数据、文献或判断", "reason": "为什么 AI 不能自行补"}}
  ],
  "risk_controls": [
    {{"risk": "修改风险", "control": "控制办法", "related_nodes": ["P2"]}}
  ]
}}

要求：
- nodes 数量控制在 7-10 个。
- phase 从 1 开始递增，体现依赖顺序。
- 所有具体修改意见、动作、风险控制必须用中文。
- 不要要求 AI 自行编造结果、数据、访谈、实验、统计检验或引用。
- 如果评审意见互相冲突，把冲突处理放入单独节点。

Manuscript title: {manuscript_title}
Editorial decision context: {decision}

# Revision Intake
{analyses["revision_intake"][:18000]}

# Structure Architect
{analyses["structure_architect"][:14000]}

# Argument Builder
{analyses["argument_builder"][:14000]}

# Citation Compliance
{analyses["citation_compliance"][:14000]}
"""


def parse_plan_json(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            return json.loads(match.group(0))
        raise ValueError("修改计划 JSON 解析失败。模型没有返回合法 JSON。")


def normalize_plan(plan: dict[str, Any], title: str, review_result: dict[str, Any]) -> dict[str, Any]:
    plan.setdefault("title", f"{title} 修改计划")
    plan.setdefault("decision_context", (review_result.get("summary") or {}).get("decision", ""))
    plan.setdefault("priority_summary", "优先处理阻碍录用的核心问题，再进入局部写作优化。")
    lanes = plan.get("lanes")
    if not isinstance(lanes, list) or not lanes:
        plan["lanes"] = [{"id": lane_id, "label": label} for lane_id, label in LANE_LABELS.items()]
    else:
        plan["lanes"] = [
            lane if isinstance(lane, dict) else {"id": str(lane), "label": str(lane)}
            for lane in lanes
        ]
    nodes = plan.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        plan["nodes"] = fallback_nodes_from_summary(plan["priority_summary"])
    else:
        plan["nodes"] = [node for node in nodes if isinstance(node, dict)]
        if not plan["nodes"]:
            plan["nodes"] = fallback_nodes_from_summary(plan["priority_summary"])
    for index, node in enumerate(plan["nodes"], start=1):
        node.setdefault("id", f"P{index}")
        node["phase"] = safe_phase(node.get("phase"), index)
        if not isinstance(node.get("lane"), str):
            node["lane"] = "writing"
        node.setdefault("title_zh", f"修改节点 {index}")
        node.setdefault("title_en", f"Revision Node {index}")
        node.setdefault("priority", "Major")
        node.setdefault("objective", "")
        if isinstance(node.get("actions"), str):
            node["actions"] = [node["actions"]]
        elif not isinstance(node.get("actions"), list):
            node["actions"] = []
        node.setdefault("evidence_from_review", "")
        node.setdefault("manuscript_target", "")
        if isinstance(node.get("depends_on"), str):
            node["depends_on"] = [node["depends_on"]]
        elif not isinstance(node.get("depends_on"), list):
            node["depends_on"] = []
        node.setdefault("deliverable", "")
        node.setdefault("owner_agent", "")
    if not isinstance(plan.get("timeline"), list):
        plan["timeline"] = build_timeline_from_nodes(plan["nodes"])
    if not isinstance(plan.get("author_inputs"), list):
        plan["author_inputs"] = []
    if not isinstance(plan.get("risk_controls"), list):
        plan["risk_controls"] = []
    return plan


def safe_phase(value: Any, fallback: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def fallback_nodes_from_summary(summary: str) -> list[dict[str, Any]]:
    return [
        {
            "id": "P1",
            "phase": 1,
            "lane": "diagnosis",
            "title_zh": "确认核心问题",
            "title_en": "Confirm blocking issues",
            "priority": "Critical",
            "objective": summary,
            "actions": ["把所有评审意见拆成可执行任务", "标出需要作者补充的信息"],
            "evidence_from_review": "来自多 agent 评审综合意见",
            "manuscript_target": "全文",
            "depends_on": [],
            "deliverable": "修改任务清单",
            "owner_agent": "Revision Intake",
        },
        {
            "id": "P2",
            "phase": 2,
            "lane": "writing",
            "title_zh": "执行高优先级修改",
            "title_en": "Execute priority revisions",
            "priority": "Major",
            "objective": "先处理会影响审稿结论的主要问题。",
            "actions": ["重写关键章节", "补充必要证据或限制说明"],
            "evidence_from_review": "来自主审稿意见",
            "manuscript_target": "摘要、引言、方法、讨论",
            "depends_on": ["P1"],
            "deliverable": "第一版修改稿",
            "owner_agent": "Revision Coach",
        },
    ]


def build_timeline_from_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_phase: dict[int, list[str]] = {}
    for node in nodes:
        phase = safe_phase(node.get("phase"), 1)
        by_phase.setdefault(phase, []).append(str(node.get("id")))
    return [
        {"stage": f"第{phase}轮", "focus": "完成本阶段依赖任务", "node_ids": ids}
        for phase, ids in sorted(by_phase.items())
    ]


def run_heuristic_revision_plan(
    manuscript_text: str,
    review_markdown: str,
    review_result: dict[str, Any],
    profile: Any,
    progress: Any = None,
) -> dict[str, Any]:
    emit_progress(progress, "revision_intake", "running", message="正在解析评审 Markdown")
    issues = extract_review_issues(review_markdown)
    emit_progress(progress, "revision_intake", "complete", recommendation="问题清单完成", confidence=3)
    for agent_id in ["structure_architect", "argument_builder", "citation_compliance"]:
        emit_progress(progress, agent_id, "running", message=f"{REVISION_ROLE_LABELS[agent_id]} 正在规划")
        emit_progress(progress, agent_id, "complete", recommendation="策略完成", confidence=3)
    emit_progress(progress, "revision_coach", "running", message="正在生成修改流程")
    nodes = heuristic_nodes(issues, profile)
    plan = {
        "title": f"{profile.title} 修改计划",
        "decision_context": (review_result.get("summary") or {}).get("decision", ""),
        "priority_summary": "先处理方法、证据和核心论证，再推进结构重组、文字改写和回复审稿。",
        "lanes": [{"id": lane_id, "label": label} for lane_id, label in LANE_LABELS.items()],
        "nodes": nodes,
        "timeline": build_timeline_from_nodes(nodes),
        "author_inputs": [
            {
                "needed_for": "P4",
                "item": "真实补充数据、稳健性分析结果或作者确认的限制条件",
                "reason": "AI 不能替作者生成不存在的实证结果。",
            }
        ],
        "risk_controls": [
            {
                "risk": "为回应评审而过度承诺",
                "control": "所有新增结论必须能被原始数据、方法或文献支撑。",
                "related_nodes": ["P3", "P4"],
            }
        ],
    }
    markdown = plan_to_markdown(plan)
    emit_progress(progress, "revision_coach", "complete", recommendation="修改计划完成", confidence=3)
    return {
        "provider": "heuristic",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "profile": profile_to_dict(profile),
        "source_review": {
            "decision": (review_result.get("summary") or {}).get("decision", ""),
            "confidence": (review_result.get("summary") or {}).get("confidence", ""),
        },
        "agents": [
            {
                "id": agent_id,
                "label": REVISION_ROLE_LABELS[agent_id],
                "status": "complete",
                "markdown": "",
            }
            for agent_id in REVISION_ROLE_LABELS
        ],
        "plan": plan,
        "markdown": markdown,
    }


def extract_review_issues(review_markdown: str) -> list[str]:
    candidates = []
    for line in review_markdown.splitlines():
        stripped = line.strip(" -*\t")
        if not stripped:
            continue
        if any(token in stripped for token in ["致命", "主要", "Major", "Critical", "weakness", "不足", "问题", "建议"]):
            candidates.append(stripped)
    return candidates[:12]


def heuristic_nodes(issues: list[str], profile: Any) -> list[dict[str, Any]]:
    issue_text = issues[0] if issues else "上一轮评审指出论文仍有影响录用判断的关键问题。"
    return [
        {
            "id": "P1",
            "phase": 1,
            "lane": "diagnosis",
            "title_zh": "冻结修改范围",
            "title_en": "Lock revision scope",
            "priority": "Critical",
            "objective": "把上一轮评审意见拆解成必须修改、可以修改和暂不接受三类。",
            "actions": ["合并重复评审意见", "标注每条意见对应的原文章节", "识别互相冲突的建议"],
            "evidence_from_review": issue_text,
            "manuscript_target": "全文",
            "depends_on": [],
            "deliverable": "可执行修改清单",
            "owner_agent": "Revision Intake",
        },
        {
            "id": "P2",
            "phase": 2,
            "lane": "structure",
            "title_zh": "重排论文结构",
            "title_en": "Restructure manuscript",
            "priority": "Major",
            "objective": "让引言、方法、结果和讨论按审稿人最关心的问题重新组织。",
            "actions": ["重写引言末尾贡献陈述", "调整方法和结果的对应关系", "把限制放入讨论结尾"],
            "evidence_from_review": "评审关注稿件逻辑链和章节支撑关系。",
            "manuscript_target": "引言、方法、结果、讨论",
            "depends_on": ["P1"],
            "deliverable": "新版章节大纲",
            "owner_agent": "Structure Architect",
        },
        {
            "id": "P3",
            "phase": 3,
            "lane": "argument",
            "title_zh": "收紧核心论证",
            "title_en": "Tighten central argument",
            "priority": "Major",
            "objective": "把论文主张限定在现有证据真正能支持的范围内。",
            "actions": ["删除过度泛化表达", "补充机制解释", "把贡献写成可验证陈述"],
            "evidence_from_review": "评审对证据链、原创性或理论贡献提出质疑。",
            "manuscript_target": "摘要、引言、讨论",
            "depends_on": ["P2"],
            "deliverable": "修订后的核心论点段落",
            "owner_agent": "Argument Builder",
        },
        {
            "id": "P4",
            "phase": 3,
            "lane": "evidence",
            "title_zh": "补足证据和引用",
            "title_en": "Repair evidence and citations",
            "priority": "Major",
            "objective": "明确哪些结论需要数据、稳健性分析或文献支撑。",
            "actions": ["列出必须补充的真实数据或分析", "补齐关键文献", "标注 AI 不能代填的位置"],
            "evidence_from_review": "评审关注方法、统计、文献或证据充分性。",
            "manuscript_target": "方法、结果、参考文献",
            "depends_on": ["P1"],
            "deliverable": "证据缺口表",
            "owner_agent": "Citation Compliance",
        },
        {
            "id": "P5",
            "phase": 4,
            "lane": "writing",
            "title_zh": "局部重写",
            "title_en": "Targeted rewriting",
            "priority": "Major",
            "objective": "只重写受评审意见影响的关键段落，避免全文无差别改写。",
            "actions": ["优先改摘要和引言", "重写方法不足说明", "将新增限制写入讨论"],
            "evidence_from_review": "多位评审的主要意见需要反映到正文。",
            "manuscript_target": "摘要、引言、方法、讨论",
            "depends_on": ["P3", "P4"],
            "deliverable": "第一版修改稿",
            "owner_agent": "Draft Writer",
        },
        {
            "id": "P6",
            "phase": 5,
            "lane": "response",
            "title_zh": "生成逐条回复",
            "title_en": "Draft response letter",
            "priority": "Major",
            "objective": "把每条评审意见对应到具体修改位置和回应策略。",
            "actions": ["逐条引用评审意见", "说明接受、部分接受或不接受理由", "标注修改页码或章节"],
            "evidence_from_review": "需要形成可提交的 response-to-reviewers。",
            "manuscript_target": "回复信",
            "depends_on": ["P5"],
            "deliverable": "逐条回复草稿",
            "owner_agent": "Revision Coach",
        },
    ]


def plan_to_markdown(plan: dict[str, Any]) -> str:
    lines = [
        f"# {plan.get('title', '论文修改计划')}",
        "",
        f"**总体方向**：{plan.get('priority_summary', '')}",
        "",
        "## 修改流程节点",
    ]
    for node in plan.get("nodes", []):
        lines.extend(
            [
                "",
                f"### {node.get('id')} · {node.get('title_zh')} / {node.get('title_en')}",
                f"- 优先级：{node.get('priority')}",
                f"- 阶段：{node.get('phase')}",
                f"- 对应位置：{node.get('manuscript_target')}",
                f"- 目标：{node.get('objective')}",
                f"- 产物：{node.get('deliverable')}",
                "- 动作：",
            ]
        )
        lines.extend(f"  - {action}" for action in node.get("actions", []))
    if plan.get("author_inputs"):
        lines.extend(["", "## 需要作者补充"])
        for item in plan["author_inputs"]:
            lines.append(f"- {item.get('needed_for')}: {item.get('item')}（{item.get('reason')}）")
    return "\n".join(lines)
