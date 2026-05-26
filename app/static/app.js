const form = document.querySelector("#reviewForm");
const runButton = document.querySelector("#runButton");
const reportOutput = document.querySelector("#reportOutput");
const agentLane = document.querySelector("#agentLane");
const tabs = document.querySelector("#tabs");
const copyButton = document.querySelector("#copyButton");
const downloadMdButton = document.querySelector("#downloadMdButton");
const downloadPdfButton = document.querySelector("#downloadPdfButton");
const paperTitle = document.querySelector("#paperTitle");
const summaryMetrics = document.querySelector("#summaryMetrics");

let currentResult = null;
let activeAgentId = null;
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

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const formData = new FormData(form);
  const file = formData.get("file");
  if (!(file instanceof File) || !file.name) {
    renderMessage("请先上传论文初稿文件。支持 .txt / .md / .docx / .pdf。");
    return;
  }
  formData.set("provider", "openai");

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
    pollReviewTask(data.task_id);
  } catch (error) {
    renderMessage(`评审失败：${error.message}`, "error");
    markAgentsError();
    setRunning(false);
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

copyButton.addEventListener("click", async () => {
  const agent = getActiveAgent();
  if (!agent) return;
  await navigator.clipboard.writeText(agent.markdown);
});

downloadMdButton.addEventListener("click", () => {
  if (!currentResult) return;
  const content = buildAllMarkdown(currentResult);
  const blob = new Blob([content], { type: "text/markdown;charset=utf-8" });
  downloadBlob(blob, "ai-paper-review-report.md");
});

downloadPdfButton.addEventListener("click", async () => {
  if (!currentResult) return;
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
  runButton.innerHTML = running
    ? '<span class="button-icon">●</span> 正在评审'
    : '<span class="button-icon">▶</span> 开始多 Agent 评审';
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
  renderActiveReport();
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
  const lower = String(value || "").toLowerCase();
  if (lower.includes("accept") || value.includes("接收")) return "decision-accept";
  if (lower.includes("minor") || value.includes("小修")) return "decision-minor";
  if (lower.includes("major") || value.includes("大修")) return "decision-major";
  if (lower.includes("reject") || value.includes("拒稿")) return "decision-reject";
  return "";
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}
