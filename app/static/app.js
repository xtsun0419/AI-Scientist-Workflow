const form = document.querySelector("#reviewForm");
const revisionImportForm = document.querySelector("#revisionImportForm");
const runButton = document.querySelector("#runButton");
const importRevisionButton = document.querySelector("#importRevisionButton");
const reportOutput = document.querySelector("#reportOutput");
const agentLane = document.querySelector("#agentLane");
const tabs = document.querySelector("#tabs");
const copyButton = document.querySelector("#copyButton");
const downloadMdButton = document.querySelector("#downloadMdButton");
const downloadPdfButton = document.querySelector("#downloadPdfButton");
const revisionPlanButton = document.querySelector("#revisionPlanButton");
const paperTitle = document.querySelector("#paperTitle");
const summaryMetrics = document.querySelector("#summaryMetrics");

let currentResult = null;
let currentReviewTaskId = null;
let currentRevisionPlan = null;
let activeAgentId = null;
let activeView = "review";
let pollTimer = null;

const startingAgents = [
  ["field_analyst", "领域分析 / Field Analyst"],
  ["eic", "主编 / Editor-in-Chief"],
  ["methodology", "方法学 / Methodology"],
  ["domain", "领域专家 / Domain"],
  ["perspective", "跨学科视角 / Perspective"],
  ["devils_advocate", "反方评审 / Devil's Advocate"],
  ["synthesizer", "编辑综合 / Synthesizer"],
];

const revisionAgents = [
  ["revision_intake", "评审解析 / Revision Intake"],
  ["structure_architect", "结构设计 / Structure Architect"],
  ["argument_builder", "论证强化 / Argument Builder"],
  ["citation_compliance", "证据引用 / Citation Compliance"],
  ["revision_coach", "修改教练 / Revision Coach"],
];

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(form);
  const file = formData.get("file");
  if (!(file instanceof File) || !file.name) {
    renderMessage("请先上传论文初稿文件。支持 .txt / .md / .docx / .pdf。");
    return;
  }
  formData.set("provider", "openai");

  currentReviewTaskId = null;
  currentRevisionPlan = null;
  activeView = "review";
  setRunning(true);
  renderAgentPlaceholders();
  renderMessage("正在读取稿件并调用后端配置的外部 LLM API。完整多 agent 评审可能需要几分钟...");

  try {
    const response = await fetch("/api/review/start", {
      method: "POST",
      body: formData,
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Review failed");
    }
    currentReviewTaskId = data.task_id;
    pollReviewTask(data.task_id);
  } catch (error) {
    renderMessage(`评审失败：${error.message}`, "error");
    markAgentsError();
    setRunning(false);
  }
});

revisionPlanButton.addEventListener("click", async () => {
  if (!currentReviewTaskId) return;
  if (currentRevisionPlan) {
    renderRevisionPlan(currentRevisionPlan);
    return;
  }
  setRevisionRunning(true);
  renderRevisionAgentPlaceholders();
  showRevisionShell("正在读取原始论文和后台 Markdown 评审结果，生成可视化修改计划...");
  try {
    const response = await fetch("/api/revision-plan/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ review_task_id: currentReviewTaskId }),
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Revision plan failed");
    }
    pollRevisionPlanTask(data.task_id);
  } catch (error) {
    renderMessage(`修改计划生成失败：${error.message}`, "error");
    markAgentsError();
    setRevisionRunning(false);
  }
});

revisionImportForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(revisionImportForm);
  const manuscriptFile = formData.get("manuscript_file");
  const reviewFile = formData.get("review_markdown_file");
  if (!(manuscriptFile instanceof File) || !manuscriptFile.name) {
    renderMessage("请先上传原始论文文件。", "error");
    return;
  }
  if (!(reviewFile instanceof File) || !reviewFile.name) {
    renderMessage("请上传上次下载的评审 Markdown 文件。", "error");
    return;
  }
  currentResult = null;
  currentReviewTaskId = null;
  currentRevisionPlan = null;
  activeView = "revision";
  setRevisionRunning(true);
  renderRevisionAgentPlaceholders();
  showRevisionShell("正在读取原始论文和评审 Markdown，直接生成可视化修改计划...");
  try {
    const response = await fetch("/api/revision-plan/import", {
      method: "POST",
      body: formData,
    });
    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.error || "Revision import failed");
    }
    pollRevisionPlanTask(data.task_id);
  } catch (error) {
    renderMessage(`导入评审 Markdown 失败：${error.message}`, "error");
    markAgentsError();
    setRevisionRunning(false);
  }
});

async function pollReviewTask(taskId) {
  if (pollTimer) clearTimeout(pollTimer);
  try {
    const response = await fetch(`/api/review/status?id=${encodeURIComponent(taskId)}`);
    const task = await response.json();
    if (!response.ok) {
      throw new Error(task.error || "Task status failed");
    }
    renderProgress(task);
    if (task.status === "complete") {
      currentResult = task.result;
      activeAgentId = currentResult.agents[currentResult.agents.length - 1].id;
      renderResult(currentResult);
      setRunning(false);
      return;
    }
    if (task.status === "error") {
      renderMessage(`评审失败：${task.error}`, "error");
      markAgentsError();
      setRunning(false);
      return;
    }
    pollTimer = setTimeout(() => pollReviewTask(taskId), 1200);
  } catch (error) {
    renderMessage(`评审进度获取失败：${error.message}`, "error");
    setRunning(false);
  } finally {
    // Completion and error branches stop the polling loop explicitly.
  }
}

async function pollRevisionPlanTask(taskId) {
  if (pollTimer) clearTimeout(pollTimer);
  try {
    const response = await fetch(`/api/revision-plan/status?id=${encodeURIComponent(taskId)}`);
    const task = await response.json();
    if (!response.ok) {
      throw new Error(task.error || "Revision plan status failed");
    }
    renderProgress(task);
    if (task.status === "complete") {
      currentRevisionPlan = task.result;
      renderRevisionPlan(currentRevisionPlan);
      setRevisionRunning(false);
      return;
    }
    if (task.status === "error") {
      renderMessage(`修改计划生成失败：${task.error}`, "error");
      markAgentsError();
      setRevisionRunning(false);
      return;
    }
    pollTimer = setTimeout(() => pollRevisionPlanTask(taskId), 1200);
  } catch (error) {
    renderMessage(`修改计划进度获取失败：${error.message}`, "error");
    setRevisionRunning(false);
  }
}

copyButton.addEventListener("click", async () => {
  if (activeView === "revision" && currentRevisionPlan) {
    await navigator.clipboard.writeText(currentRevisionPlan.markdown || "");
    return;
  }
  const agent = getActiveAgent();
  if (!agent) return;
  await navigator.clipboard.writeText(agent.markdown);
});

downloadMdButton.addEventListener("click", () => {
  if (!currentResult && !currentRevisionPlan) return;
  const content = activeView === "revision" && currentRevisionPlan ? currentRevisionPlan.markdown : buildAllMarkdown(currentResult);
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  downloadBlob(blob, activeView === "revision" ? "ai-paper-revision-plan.md" : "ai-paper-review-report.md");
});

downloadPdfButton.addEventListener("click", async () => {
  if (!currentResult || activeView !== "review") return;
  downloadPdfButton.disabled = true;
  downloadPdfButton.textContent = "正在生成 PDF...";
  try {
    const response = await fetch("/api/export/pdf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(currentResult),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || "PDF export failed");
    }
    const blob = await response.blob();
    downloadBlob(blob, "ai-paper-review-report.pdf");
  } catch (error) {
    renderMessage(`PDF 生成失败：${error.message}`, "error");
  } finally {
    downloadPdfButton.disabled = false;
    downloadPdfButton.textContent = "下载 PDF";
  }
});

function setRunning(running) {
  runButton.disabled = running;
  importRevisionButton.disabled = running;
  revisionPlanButton.disabled = running || !currentReviewTaskId;
  runButton.innerHTML = running
    ? '<span class="button-icon">●</span> 正在评审'
    : '<span class="button-icon">▶</span> 开始多 Agent 评审';
}

function setRevisionRunning(running) {
  runButton.disabled = running;
  importRevisionButton.disabled = running;
  revisionPlanButton.disabled = running || (!currentReviewTaskId && !currentRevisionPlan);
  revisionPlanButton.textContent = running ? "正在生成修改计划..." : "继续生成修改计划";
  importRevisionButton.innerHTML = running
    ? '<span class="button-icon">●</span> 正在生成'
    : '<span class="button-icon">↳</span> 导入并生成修改计划';
}

function renderAgentPlaceholders() {
  agentLane.innerHTML = startingAgents
    .map(
      ([id, label], index) => `
      <article class="agent-card ${index === 0 ? "running" : "idle"}" data-agent="${id}">
        <div class="agent-top">
          <span class="status-dot"></span>
          <strong>${escapeHtml(label)}</strong>
        </div>
        <p>${index === 0 ? "正在处理" : "等待中"}</p>
      </article>`
    )
    .join("");
}

function renderRevisionAgentPlaceholders() {
  agentLane.innerHTML = revisionAgents
    .map(
      ([id, label], index) => `
      <article class="agent-card ${index === 0 ? "running" : "idle"}" data-agent="${id}">
        <div class="agent-top">
          <span class="status-dot"></span>
          <strong>${escapeHtml(label)}</strong>
        </div>
        <p>${index === 0 ? "正在处理" : "等待中"}</p>
      </article>`
    )
    .join("");
}

function renderProgress(task) {
  const agents = task.agents && task.agents.length ? task.agents : [];
  agentLane.innerHTML = agents
    .map(
      (agent) => `
      <article class="agent-card ${statusClass(agent.status)} ${decisionClass(agent.recommendation)}" data-agent="${agent.id}">
        <div class="agent-top">
          <span class="status-dot"></span>
          <strong>${escapeHtml(agent.label)}</strong>
        </div>
        <p>${escapeHtml(progressText(agent))}</p>
      </article>`
    )
    .join("");
}

function statusClass(status) {
  if (status === "running") return "running";
  if (status === "complete") return "complete";
  if (status === "error") return "error";
  return "idle";
}

function progressText(agent) {
  if (agent.status === "complete") {
    const rec = agent.recommendation ? formatRecommendation(agent.recommendation) : "完成";
    const confidence = agent.confidence ? ` · 置信度 ${agent.confidence}/5` : "";
    return `${rec}${confidence}`;
  }
  if (agent.status === "running") return agent.message || "正在运行";
  if (agent.status === "error") return agent.message || "运行失败";
  return "等待中";
}

function markAgentsError() {
  document.querySelectorAll(".agent-card").forEach((card) => {
    card.classList.remove("running", "idle", "complete");
    card.classList.add("error");
  });
}

function renderResult(data) {
  activeView = "review";
  const profile = data.profile;
  paperTitle.textContent = profile.title || "Untitled Manuscript";
  summaryMetrics.innerHTML = `
    <div><span>${escapeHtml(formatRecommendation(data.summary.decision || "-"))}</span><small>决策 / Decision</small></div>
    <div><span>${profile.word_count || 0}</span><small>词数 / Words</small></div>
    <div><span>${profile.reference_count || 0}</span><small>文献 / Refs</small></div>
    <div><span>${data.agents.length}</span><small>Agents</small></div>
  `;

  agentLane.innerHTML = data.agents
    .map(
      (agent) => `
      <article class="agent-card complete ${decisionClass(agent.recommendation)}" data-agent="${agent.id}">
        <div class="agent-top">
          <span class="status-dot"></span>
          <strong>${escapeHtml(agent.label)}</strong>
        </div>
        <p>${escapeHtml(formatRecommendation(agent.recommendation || "评审完成 / Complete"))} · 置信度 ${agent.confidence || "-"}/5</p>
      </article>`
    )
    .join("");

  tabs.innerHTML = data.agents
    .map(
      (agent) => `
      <button type="button" data-agent="${agent.id}" class="${agent.id === activeAgentId ? "active" : ""}">
        ${escapeHtml(shortLabel(agent.label))}
      </button>`
    )
    .join("");
  tabs.querySelectorAll("button").forEach((button) => {
    button.addEventListener("click", () => {
      activeAgentId = button.dataset.agent;
      renderActiveReport();
    });
  });

  copyButton.disabled = false;
  downloadMdButton.disabled = false;
  downloadPdfButton.disabled = false;
  revisionPlanButton.disabled = false;
  revisionPlanButton.textContent = currentRevisionPlan ? "查看修改计划" : "继续生成修改计划";
  renderActiveReport();
}

function showRevisionShell(message) {
  activeView = "revision";
  paperTitle.textContent = currentResult?.profile?.title
    ? `${currentResult.profile.title} · 修改计划`
    : "论文修改计划";
  summaryMetrics.innerHTML = `
    <div><span>2</span><small>阶段 / Step</small></div>
    <div><span>${revisionAgents.length}</span><small>Agents</small></div>
    <div><span>-</span><small>节点 / Nodes</small></div>
    <div><span>运行中</span><small>Status</small></div>
  `;
  tabs.innerHTML = "";
  copyButton.disabled = true;
  downloadMdButton.disabled = true;
  downloadPdfButton.disabled = true;
  reportOutput.innerHTML = `
    <div class="empty-state">
      ${escapeHtml(message)}
    </div>
  `;
}

function renderRevisionPlan(data) {
  activeView = "revision";
  const plan = data.plan || {};
  const nodes = Array.isArray(plan.nodes) ? plan.nodes : [];
  paperTitle.textContent = plan.title || "论文修改计划";
  summaryMetrics.innerHTML = `
    <div><span>${escapeHtml(data.source_review?.decision || "-")}</span><small>原评审决策</small></div>
    <div><span>${nodes.length}</span><small>修改节点</small></div>
    <div><span>${countCriticalNodes(nodes)}</span><small>Critical</small></div>
    <div><span>${escapeHtml(data.provider || "openai")}</span><small>Provider</small></div>
  `;
  tabs.innerHTML = `
    <button type="button" class="active">修改流程图</button>
    ${currentResult ? '<button type="button" id="showReviewReportTab">返回评审报告</button>' : ""}
  `;
  const backButton = document.querySelector("#showReviewReportTab");
  if (backButton) {
    backButton.addEventListener("click", () => {
      if (currentResult) renderResult(currentResult);
    });
  }
  copyButton.disabled = false;
  downloadMdButton.disabled = false;
  downloadPdfButton.disabled = true;
  revisionPlanButton.disabled = false;
  revisionPlanButton.textContent = "查看修改计划";
  reportOutput.innerHTML = buildRevisionPlanHtml(plan);
}

function buildRevisionPlanHtml(plan) {
  const lanes = Array.isArray(plan.lanes) ? plan.lanes : [];
  const nodes = Array.isArray(plan.nodes) ? plan.nodes : [];
  const nodesByLane = new Map();
  nodes.forEach((node) => {
    const lane = node.lane || "writing";
    if (!nodesByLane.has(lane)) nodesByLane.set(lane, []);
    nodesByLane.get(lane).push(node);
  });
  const laneHtml = lanes
    .map((lane) => {
      const laneNodes = nodesByLane.get(lane.id) || [];
      return `
        <section class="flow-lane">
          <div class="flow-lane-title">${escapeHtml(lane.label || lane.id)}</div>
          <div class="flow-lane-stack">
            ${laneNodes.map((node) => revisionNodeHtml(node)).join("") || '<div class="flow-empty">暂无节点</div>'}
          </div>
        </section>
      `;
    })
    .join("");
  return `
    <div class="revision-board">
      <header class="revision-hero">
        <div>
          <span class="report-kicker">Revision Workflow / 修改工作流</span>
          <h3>${escapeHtml(plan.title || "论文修改计划")}</h3>
          <p>${escapeHtml(plan.priority_summary || "")}</p>
        </div>
        <div class="revision-legend">
          <span class="priority-critical">Critical</span>
          <span class="priority-major">Major</span>
          <span class="priority-minor">Minor</span>
        </div>
      </header>
      <div class="timeline-strip">
        ${(plan.timeline || []).map((stage) => timelineStageHtml(stage)).join("")}
      </div>
      <div class="flow-board">
        ${laneHtml}
      </div>
      ${authorInputsHtml(plan.author_inputs || [])}
      ${riskControlsHtml(plan.risk_controls || [])}
    </div>
  `;
}

function revisionNodeHtml(node) {
  const depends = Array.isArray(node.depends_on) && node.depends_on.length
    ? node.depends_on.join(", ")
    : "无";
  const actions = Array.isArray(node.actions) ? node.actions : [];
  return `
    <article class="revision-node ${priorityClass(node.priority)}">
      <div class="node-topline">
        <span class="node-id">${escapeHtml(node.id || "")}</span>
        <span class="node-phase">Phase ${escapeHtml(node.phase || "-")}</span>
      </div>
      <h4>${escapeHtml(node.title_zh || "")}</h4>
      <p class="node-en">${escapeHtml(node.title_en || "")}</p>
      <p class="node-objective">${escapeHtml(node.objective || "")}</p>
      <div class="node-meta">
        <span>${escapeHtml(node.priority || "Major")}</span>
        <span>依赖：${escapeHtml(depends)}</span>
      </div>
      <dl>
        <div>
          <dt>原文位置</dt>
          <dd>${escapeHtml(node.manuscript_target || "-")}</dd>
        </div>
        <div>
          <dt>交付物</dt>
          <dd>${escapeHtml(node.deliverable || "-")}</dd>
        </div>
      </dl>
      <ul>
        ${actions.slice(0, 4).map((action) => `<li>${escapeHtml(action)}</li>`).join("")}
      </ul>
      <div class="node-evidence">${escapeHtml(node.evidence_from_review || "")}</div>
    </article>
  `;
}

function timelineStageHtml(stage) {
  const ids = Array.isArray(stage.node_ids) ? stage.node_ids.join(" · ") : "";
  return `
    <article>
      <strong>${escapeHtml(stage.stage || "")}</strong>
      <span>${escapeHtml(stage.focus || "")}</span>
      <small>${escapeHtml(ids)}</small>
    </article>
  `;
}

function authorInputsHtml(items) {
  if (!items.length) return "";
  return `
    <section class="revision-panel attention">
      <h4>需要作者补充 / Author Inputs</h4>
      <div class="panel-grid">
        ${items
          .map(
            (item) => `
            <article>
              <strong>${escapeHtml(item.needed_for || "")}</strong>
              <p>${escapeHtml(item.item || "")}</p>
              <small>${escapeHtml(item.reason || "")}</small>
            </article>
          `
          )
          .join("")}
      </div>
    </section>
  `;
}

function riskControlsHtml(items) {
  if (!items.length) return "";
  return `
    <section class="revision-panel">
      <h4>风险控制 / Risk Controls</h4>
      <div class="panel-grid">
        ${items
          .map(
            (item) => `
            <article>
              <strong>${escapeHtml(item.risk || "")}</strong>
              <p>${escapeHtml(item.control || "")}</p>
              <small>${escapeHtml((item.related_nodes || []).join(" · "))}</small>
            </article>
          `
          )
          .join("")}
      </div>
    </section>
  `;
}

function priorityClass(priority) {
  const value = String(priority || "").toLowerCase();
  if (value.includes("critical")) return "priority-critical";
  if (value.includes("minor")) return "priority-minor";
  return "priority-major";
}

function countCriticalNodes(nodes) {
  return nodes.filter((node) => String(node.priority || "").toLowerCase().includes("critical")).length;
}

function renderActiveReport() {
  const agent = getActiveAgent();
  tabs.querySelectorAll("button").forEach((button) => {
    button.classList.toggle("active", button.dataset.agent === activeAgentId);
  });
  if (!agent) {
    renderMessage("");
    return;
  }
  reportOutput.innerHTML = `
    <div class="report-heading">
      <span class="report-kicker">${escapeHtml(agent.label)}</span>
      <h3>${escapeHtml(formatRecommendation(agent.recommendation || "评审完成 / Complete"))}</h3>
      <div class="report-badges">
        <span>置信度 ${agent.confidence || "-"}/5</span>
        <span>${escapeHtml(currentResult.provider || "openai")}</span>
      </div>
    </div>
    <div class="markdown-body">${markdownToHtml(agent.markdown)}</div>
  `;
}

function getActiveAgent() {
  if (!currentResult || !activeAgentId) return null;
  return currentResult.agents.find((item) => item.id === activeAgentId);
}

function renderMessage(message, type = "info") {
  reportOutput.innerHTML = `<div class="empty-state ${type}">${escapeHtml(message)}</div>`;
}

function markdownToHtml(markdown) {
  const lines = String(markdown || "").split(/\r?\n/);
  const html = [];
  let inTable = false;
  let inList = false;
  let inCode = false;
  let codeLines = [];

  const closeList = () => {
    if (inList) {
      html.push("</ul>");
      inList = false;
    }
  };
  const closeTable = () => {
    if (inTable) {
      html.push("</tbody></table>");
      inTable = false;
    }
  };

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    if (line.startsWith("```")) {
      if (inCode) {
        html.push(`<pre><code>${escapeHtml(codeLines.join("\n"))}</code></pre>`);
        codeLines = [];
        inCode = false;
      } else {
        closeList();
        closeTable();
        inCode = true;
      }
      continue;
    }
    if (inCode) {
      codeLines.push(line);
      continue;
    }

    if (/^\|.*\|$/.test(line)) {
      closeList();
      const cells = line.split("|").slice(1, -1).map((cell) => inlineMarkdown(cell.trim()));
      const separator = cells.every((cell) => /^:?-{3,}:?$/.test(stripTags(cell)));
      if (separator) continue;
      if (!inTable) {
        html.push("<table><tbody>");
        inTable = true;
      }
      html.push(`<tr>${cells.map((cell) => `<td>${cell}</td>`).join("")}</tr>`);
      continue;
    }
    closeTable();

    if (!line.trim()) {
      closeList();
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if (heading) {
      closeList();
      const level = Math.min(heading[1].length + 1, 5);
      html.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
      continue;
    }
    const bullet = line.match(/^[-*]\s+(.+)$/);
    if (bullet) {
      if (!inList) {
        html.push("<ul>");
        inList = true;
      }
      html.push(`<li>${inlineMarkdown(bullet[1])}</li>`);
      continue;
    }
    const numbered = line.match(/^\d+\.\s+(.+)$/);
    if (numbered) {
      if (!inList) {
        html.push("<ul>");
        inList = true;
      }
      html.push(`<li>${inlineMarkdown(numbered[1])}</li>`);
      continue;
    }
    closeList();
    html.push(`<p>${inlineMarkdown(line)}</p>`);
  }
  closeList();
  closeTable();
  return html.join("\n");
}

function inlineMarkdown(text) {
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`(.+?)`/g, "<code>$1</code>");
}

function stripTags(text) {
  return text.replace(/<[^>]*>/g, "");
}

function buildAllMarkdown(data) {
  return data.agents.map((agent) => `# ${agent.label}\n\n${agent.markdown}`).join("\n\n---\n\n");
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function shortLabel(label) {
  return label
    .replace("领域分析 / ", "")
    .replace("主编 / ", "")
    .replace("评审人1：方法学 / ", "R1 ")
    .replace("评审人2：领域专家 / ", "R2 ")
    .replace("评审人3：跨学科视角 / ", "R3 ")
    .replace("反方评审 / ", "")
    .replace("编辑综合 / ", "")
    .replace("Reviewer 1: ", "R1 ")
    .replace("Reviewer 2: ", "R2 ")
    .replace("Reviewer 3: ", "R3 ")
    .replace("Editorial ", "");
}

function formatRecommendation(value) {
  const labels = {
    Accept: "接收 / Accept",
    "Minor Revision": "小修 / Minor Revision",
    "Major Revision": "大修 / Major Revision",
    Reject: "拒稿 / Reject",
    "Panel configured": "评审团队已配置 / Panel configured",
    Complete: "评审完成 / Complete",
  };
  return labels[value] || value;
}

function decisionClass(value) {
  const text = String(value || "");
  const lower = text.toLowerCase();
  if (lower.includes("accept") || text.includes("接收")) return "decision-accept";
  if (lower.includes("minor") || text.includes("小修")) return "decision-minor";
  if (lower.includes("major") || text.includes("大修")) return "decision-major";
  if (lower.includes("reject") || text.includes("拒稿")) return "decision-reject";
  return "";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
