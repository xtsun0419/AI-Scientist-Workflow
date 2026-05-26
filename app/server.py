from __future__ import annotations

import json
import mimetypes
import re
import subprocess
import tempfile
import threading
import time
import uuid
import warnings
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from reviewer_engine import read_text_from_upload, run_review
from revision_engine import review_result_from_markdown, run_revision_plan

with warnings.catch_warnings():
    warnings.filterwarnings("ignore", category=DeprecationWarning)
    import cgi


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
CONFIG_PATH = APP_DIR / "config.json"

AGENT_ORDER = [
    ("field_analyst", "领域分析 / Field Analyst"),
    ("eic", "主编 / Editor-in-Chief"),
    ("methodology", "方法学 / Methodology"),
    ("domain", "领域专家 / Domain"),
    ("perspective", "跨学科视角 / Perspective"),
    ("devils_advocate", "反方评审 / Devil's Advocate"),
    ("synthesizer", "编辑综合 / Editorial Synthesizer"),
]

REVISION_AGENT_ORDER = [
    ("revision_intake", "评审解析 / Revision Intake"),
    ("structure_architect", "结构设计 / Structure Architect"),
    ("argument_builder", "论证强化 / Argument Builder"),
    ("citation_compliance", "证据引用 / Citation Compliance"),
    ("revision_coach", "修改教练 / Revision Coach"),
]

TASKS: dict[str, dict] = {}
REVISION_TASKS: dict[str, dict] = {}
TASK_LOCK = threading.Lock()


def load_backend_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"后端配置文件 app/config.json 不是有效 JSON：{exc}") from exc


class ReviewerHandler(BaseHTTPRequestHandler):
    server_version = "AIPaperReviewer/0.1"

    def log_message(self, fmt: str, *args: object) -> None:
        print(f"{self.client_address[0]} - {fmt % args}")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/review/status":
            self._handle_review_status()
            return
        if path == "/api/revision-plan/status":
            self._handle_revision_plan_status()
            return
        if path in {"/", "/index.html"}:
            self._send_file(STATIC_DIR / "index.html")
            return
        if path.startswith("/static/"):
            requested = (STATIC_DIR / path.removeprefix("/static/")).resolve()
            if STATIC_DIR.resolve() in requested.parents or requested == STATIC_DIR.resolve():
                self._send_file(requested)
                return
        self._send_json({"error": "Not found"}, status=404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/export/pdf":
            self._handle_pdf_export()
            return
        if path == "/api/review/start":
            self._handle_review_start()
            return
        if path == "/api/revision-plan/start":
            self._handle_revision_plan_start()
            return
        if path == "/api/revision-plan/import":
            self._handle_revision_plan_import()
            return
        if path != "/api/review":
            self._send_json({"error": "Not found"}, status=404)
            return
        try:
            result = self._handle_review()
            self._send_json(result)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)

    def _handle_review_start(self) -> None:
        try:
            text, options = self._parse_review_request()
            task_id = start_review_task(text, options)
            self._send_json({"task_id": task_id})
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)

    def _handle_review_status(self) -> None:
        task_id = get_query_id(self.path)
        with TASK_LOCK:
            task = TASKS.get(task_id)
            payload = public_task_payload(task) if task else None
        if not payload:
            self._send_json({"error": "Task not found"}, status=404)
            return
        self._send_json(payload)

    def _handle_revision_plan_start(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            review_task_id = body.get("review_task_id", "")
            with TASK_LOCK:
                review_task = TASKS.get(review_task_id)
                if not review_task or review_task.get("status") != "complete":
                    raise ValueError("请先完成一轮论文评审，再生成修改计划。")
                manuscript_text = review_task.get("manuscript_text", "")
                review_result = review_task.get("result")
            if not manuscript_text or not review_result:
                raise ValueError("上一轮评审任务缺少原文或评审结果，无法生成修改计划。")
            backend_config = load_backend_config()
            options = {
                **backend_config,
                "provider": backend_config.get("provider") or review_result.get("provider") or "openai",
            }
            task_id = start_revision_plan_task(manuscript_text, review_result, options)
            self._send_json({"task_id": task_id})
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)

    def _handle_revision_plan_import(self) -> None:
        try:
            manuscript_text, review_markdown, options = self._parse_revision_import_request()
            review_result = review_result_from_markdown(review_markdown, title=infer_imported_title(manuscript_text))
            task_id = start_revision_plan_task(manuscript_text, review_result, options)
            self._send_json({"task_id": task_id})
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)

    def _handle_revision_plan_status(self) -> None:
        task_id = get_query_id(self.path)
        with TASK_LOCK:
            task = REVISION_TASKS.get(task_id)
            payload = public_task_payload(task) if task else None
        if not payload:
            self._send_json({"error": "Task not found"}, status=404)
            return
        self._send_json(payload)

    def _handle_review(self) -> dict:
        text, options = self._parse_review_request()
        return run_review(text, options)

    def _parse_review_request(self) -> tuple[str, dict]:
        backend_config = load_backend_config()
        content_type = self.headers.get("Content-Type", "")
        if content_type.startswith("application/json"):
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            text = body.get("text", "")
            options = {
                "mode": body.get("mode", "full"),
                "provider": body.get("provider", "heuristic"),
                "model": body.get("model", ""),
                "base_url": body.get("base_url", ""),
                "disable_proxy": bool(body.get("disable_proxy", False)),
            }
        else:
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                    "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
                },
            )
            text = (form.getfirst("text") or "").strip()
            options = {
                "mode": form.getfirst("mode") or "full",
                "provider": form.getfirst("provider") or "heuristic",
                "model": form.getfirst("model") or "",
                "base_url": form.getfirst("base_url") or "",
                "disable_proxy": (form.getfirst("disable_proxy") or "").lower() in {"1", "true", "on", "yes"},
            }
            file_item = form["file"] if "file" in form else None
            if file_item is not None and getattr(file_item, "filename", ""):
                payload = file_item.file.read()
                text = read_text_from_upload(file_item.filename, payload)

        if not text or len(text.strip()) < 100:
            raise ValueError("Please upload or paste at least 100 characters of manuscript text.")
        options = {**backend_config, **{k: v for k, v in options.items() if v not in {"", None}}}
        return text, options

    def _parse_revision_import_request(self) -> tuple[str, str, dict]:
        backend_config = load_backend_config()
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
            },
        )
        manuscript_text = ""
        manuscript_item = form["manuscript_file"] if "manuscript_file" in form else None
        if manuscript_item is not None and getattr(manuscript_item, "filename", ""):
            manuscript_text = read_text_from_upload(manuscript_item.filename, manuscript_item.file.read())
        review_markdown = ""
        review_item = form["review_markdown_file"] if "review_markdown_file" in form else None
        if review_item is not None and getattr(review_item, "filename", ""):
            review_markdown = read_text_from_upload(review_item.filename, review_item.file.read())
        if not manuscript_text or len(manuscript_text.strip()) < 100:
            raise ValueError("请上传至少 100 个字符的原始论文文件。")
        if not review_markdown or len(review_markdown.strip()) < 100:
            raise ValueError("请上传上一轮评审 Markdown 文件。")
        options = {
            **backend_config,
            "provider": backend_config.get("provider") or "openai",
        }
        return manuscript_text, review_markdown, options

    def _handle_pdf_export(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            pdf = build_pdf(payload)
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", 'attachment; filename="ai-paper-review-report.pdf"')
            self.send_header("Content-Length", str(len(pdf)))
            self.end_headers()
            self.wfile.write(pdf)
        except Exception as exc:
            self._send_json({"error": str(exc)}, status=400)

    def _send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self._send_json({"error": "Not found"}, status=404)
            return
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        payload = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    host = "127.0.0.1"
    port = 8765
    httpd = ThreadingHTTPServer((host, port), ReviewerHandler)
    print(f"AI Paper Reviewer running at http://{host}:{port}")
    print("Press Ctrl+C to stop.")
    httpd.serve_forever()


def make_initial_agents() -> list[dict]:
    return [
        {
            "id": agent_id,
            "label": label,
            "status": "pending",
            "message": "等待中",
            "recommendation": "",
            "confidence": None,
        }
        for agent_id, label in AGENT_ORDER
    ]


def make_initial_revision_agents() -> list[dict]:
    return [
        {
            "id": agent_id,
            "label": label,
            "status": "pending",
            "message": "等待中",
            "recommendation": "",
            "confidence": None,
        }
        for agent_id, label in REVISION_AGENT_ORDER
    ]


def start_review_task(text: str, options: dict) -> str:
    task_id = uuid.uuid4().hex
    with TASK_LOCK:
        TASKS[task_id] = {
            "task_id": task_id,
            "status": "running",
            "created_at": time.time(),
            "updated_at": time.time(),
            "agents": make_initial_agents(),
            "manuscript_text": text,
            "result": None,
            "error": None,
        }
    thread = threading.Thread(target=run_review_task, args=(task_id, text, options), daemon=True)
    thread.start()
    return task_id


def run_review_task(task_id: str, text: str, options: dict) -> None:
    def progress(agent_id: str, status: str, **extra: object) -> None:
        update_task_agent(task_id, agent_id, status, **extra)

    try:
        result = run_review(text, options, progress=progress)
        with TASK_LOCK:
            task = TASKS[task_id]
            task["status"] = "complete"
            task["result"] = result
            task["agents"] = normalize_agents_from_result(result, task["agents"])
            task["updated_at"] = time.time()
    except Exception as exc:
        with TASK_LOCK:
            task = TASKS[task_id]
            task["status"] = "error"
            task["error"] = str(exc)
            for agent in task["agents"]:
                if agent["status"] == "running":
                    agent["status"] = "error"
                    agent["message"] = "运行失败"
            task["updated_at"] = time.time()


def start_revision_plan_task(manuscript_text: str, review_result: dict, options: dict) -> str:
    task_id = uuid.uuid4().hex
    with TASK_LOCK:
        REVISION_TASKS[task_id] = {
            "task_id": task_id,
            "status": "running",
            "created_at": time.time(),
            "updated_at": time.time(),
            "agents": make_initial_revision_agents(),
            "result": None,
            "error": None,
        }
    thread = threading.Thread(
        target=run_revision_plan_task,
        args=(task_id, manuscript_text, review_result, options),
        daemon=True,
    )
    thread.start()
    return task_id


def run_revision_plan_task(task_id: str, manuscript_text: str, review_result: dict, options: dict) -> None:
    def progress(agent_id: str, status: str, **extra: object) -> None:
        update_task_agent(task_id, agent_id, status, task_store=REVISION_TASKS, **extra)

    try:
        result = run_revision_plan(manuscript_text, review_result, options, progress=progress)
        with TASK_LOCK:
            task = REVISION_TASKS[task_id]
            task["status"] = "complete"
            task["result"] = result
            task["agents"] = normalize_agents_from_result(result, task["agents"])
            task["updated_at"] = time.time()
    except Exception as exc:
        with TASK_LOCK:
            task = REVISION_TASKS[task_id]
            task["status"] = "error"
            task["error"] = str(exc)
            for agent in task["agents"]:
                if agent["status"] == "running":
                    agent["status"] = "error"
                    agent["message"] = "运行失败"
            task["updated_at"] = time.time()


def update_task_agent(
    task_id: str,
    agent_id: str,
    status: str,
    task_store: dict[str, dict] | None = None,
    **extra: object,
) -> None:
    with TASK_LOCK:
        task = (task_store or TASKS).get(task_id)
        if not task:
            return
        for agent in task["agents"]:
            if agent["id"] == agent_id:
                agent["status"] = status
                agent["message"] = str(extra.get("message") or status)
                if extra.get("recommendation") is not None:
                    agent["recommendation"] = str(extra["recommendation"])
                if extra.get("confidence") is not None:
                    agent["confidence"] = extra["confidence"]
                break
        task["updated_at"] = time.time()


def get_query_id(path: str) -> str:
    query = urlparse(path).query
    params = dict(part.split("=", 1) for part in query.split("&") if "=" in part)
    return params.get("id", "")


def infer_imported_title(text: str) -> str:
    for line in text.splitlines():
        candidate = line.strip(" #\t")
        if 8 <= len(candidate) <= 180 and not re.match(r"^(abstract|摘要|introduction|引言)\b", candidate, re.I):
            return candidate
    return "Imported Manuscript"


def public_task_payload(task: dict | None) -> dict | None:
    if not task:
        return None
    payload = json.loads(json.dumps(task, ensure_ascii=False))
    payload.pop("manuscript_text", None)
    return payload


def normalize_agents_from_result(result: dict, current_agents: list[dict]) -> list[dict]:
    by_id = {agent.get("id"): agent for agent in result.get("agents", [])}
    normalized = []
    for current in current_agents:
        agent = by_id.get(current["id"], {})
        normalized.append(
            {
                **current,
                "status": "complete",
                "message": "完成",
                "recommendation": agent.get("recommendation") or current.get("recommendation") or "",
                "confidence": agent.get("confidence") or current.get("confidence"),
            }
        )
    return normalized


def build_pdf(result: dict) -> bytes:
    latex = build_latex_report(result)
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        tex_path = tmp / "review_report.tex"
        pdf_path = tmp / "review_report.pdf"
        tex_path.write_text(latex, encoding="utf-8")
        for _ in range(2):
            proc = subprocess.run(
                ["xelatex", "-interaction=nonstopmode", "-halt-on-error", tex_path.name],
                cwd=tmp,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=120,
            )
            if proc.returncode != 0:
                raise RuntimeError(f"XeLaTeX 生成 PDF 失败：{proc.stdout[-1200:]}")
        if not pdf_path.exists():
            raise RuntimeError("XeLaTeX 未生成 PDF 文件。")
        return pdf_path.read_bytes()


def build_latex_report(result: dict) -> str:
    profile = result.get("profile", {})
    agents = result.get("agents", [])
    title = latex_escape(profile.get("title") or "AI Paper Review Report")
    decision = latex_escape((result.get("summary") or {}).get("decision") or "")
    generated = latex_escape(result.get("created_at") or "")
    sections = "\n\n".join(agent_to_latex(agent) for agent in agents)
    return rf"""\documentclass[11pt,a4paper,fontset=none]{{ctexart}}
\usepackage[margin=1.9cm]{{geometry}}
\usepackage{{fontspec}}
\usepackage{{xeCJK}}
\usepackage{{xcolor}}
\usepackage{{tabularx}}
\usepackage{{booktabs}}
\usepackage{{longtable}}
\usepackage{{array}}
\usepackage{{enumitem}}
\usepackage{{hyperref}}
\usepackage{{tcolorbox}}
\tcbuselibrary{{breakable,skins}}
\setmainfont{{Helvetica Neue}}
\setsansfont{{Helvetica Neue}}
\setmonofont{{Menlo}}
\setCJKmainfont{{PingFang SC}}
\setCJKsansfont{{PingFang SC}}
\setCJKmonofont{{PingFang SC}}
\definecolor{{reviewblue}}{{HTML}}{{1E5EFF}}
\definecolor{{reviewteal}}{{HTML}}{{087F74}}
\definecolor{{reviewamber}}{{HTML}}{{AD6B00}}
\definecolor{{reviewred}}{{HTML}}{{B42318}}
\definecolor{{reviewbg}}{{HTML}}{{F6F7F8}}
\definecolor{{reviewline}}{{HTML}}{{DBE1E6}}
\hypersetup{{colorlinks=true,linkcolor=reviewblue,urlcolor=reviewteal}}
\setlist[itemize]{{leftmargin=1.4em,itemsep=0.25em,topsep=0.25em}}
\setlist[enumerate]{{leftmargin=1.6em,itemsep=0.25em,topsep=0.25em}}
\setlength{{\parindent}}{{0pt}}
\setlength{{\parskip}}{{0.55em}}
\title{{\textbf{{AI 论文评审报告}}\\[0.4em]\large {title}}}
\author{{Multi-agent Reviewer}}
\date{{{generated}}}
\begin{{document}}
\maketitle
\begin{{tcolorbox}}[enhanced,breakable,colback=reviewbg,colframe=reviewteal,boxrule=0.8pt,arc=2mm,title={{综合结论 / Decision}}]
\textbf{{{decision}}}

置信度是每个评审角色对自己判断可靠程度的自评，不是论文通过概率，也不是模型准确率。
\end{{tcolorbox}}
\tableofcontents
\newpage
{sections}
\end{{document}}
"""


def agent_to_latex(agent: dict) -> str:
    label = latex_escape(agent.get("label") or "Agent")
    recommendation = latex_escape(agent.get("recommendation") or "")
    confidence = latex_escape(str(agent.get("confidence") or "-"))
    body = markdown_to_latex(agent.get("markdown") or "")
    return rf"""\section{{{label}}}
\begin{{tcolorbox}}[enhanced,breakable,colback=white,colframe=reviewblue,boxrule=0.7pt,arc=2mm]
\textbf{{建议 / Recommendation：}} {recommendation}\quad
\textbf{{置信度 / Confidence：}} {confidence}/5
\end{{tcolorbox}}
{body}
"""


def markdown_to_latex(markdown: str) -> str:
    lines = markdown.splitlines()
    out: list[str] = []
    in_itemize = False
    in_code = False
    code_lines: list[str] = []

    def close_itemize() -> None:
        nonlocal in_itemize
        if in_itemize:
            out.append(r"\end{itemize}")
            in_itemize = False

    def flush_code() -> None:
        nonlocal in_code, code_lines
        if in_code:
            out.append(r"\begin{verbatim}")
            out.extend(code_lines)
            out.append(r"\end{verbatim}")
            code_lines = []
            in_code = False

    i = 0
    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code:
                flush_code()
            else:
                close_itemize()
                in_code = True
            i += 1
            continue
        if in_code:
            code_lines.append(line)
            i += 1
            continue
        if not stripped:
            close_itemize()
            out.append("")
            i += 1
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            close_itemize()
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|") and lines[i].strip().endswith("|"):
                if not is_markdown_separator(lines[i]):
                    table_lines.append(lines[i].strip())
                i += 1
            out.append(markdown_table_to_latex(table_lines))
            continue
        heading = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        if heading:
            close_itemize()
            level = len(heading.group(1))
            text = inline_latex(heading.group(2))
            if level == 1:
                out.append(rf"\subsection*{{{text}}}")
            elif level == 2:
                out.append(rf"\subsection{{{text}}}")
            else:
                out.append(rf"\subsubsection{{{text}}}")
            i += 1
            continue
        bullet = re.match(r"^[-*]\s+(.+)$", stripped)
        numbered = re.match(r"^\d+\.\s+(.+)$", stripped)
        if bullet or numbered:
            if not in_itemize:
                out.append(r"\begin{itemize}")
                in_itemize = True
            out.append(rf"\item {inline_latex((bullet or numbered).group(1))}")
            i += 1
            continue
        close_itemize()
        out.append(inline_latex(stripped))
        i += 1
    close_itemize()
    flush_code()
    return "\n".join(out)


def markdown_table_to_latex(table_lines: list[str]) -> str:
    if not table_lines:
        return ""
    rows = [[inline_latex(cell.strip()) for cell in line.split("|")[1:-1]] for line in table_lines]
    col_count = max((len(row) for row in rows), default=1)
    col_spec = "|".join(["X"] * col_count)
    latex_rows = []
    for row in rows:
        padded = row + [""] * (col_count - len(row))
        latex_rows.append(" & ".join(padded) + r" \\")
    return "\\begin{tcolorbox}[enhanced,breakable,colback=white,colframe=reviewline,boxrule=0.4pt,arc=1mm]\n" + \
        f"\\begin{{tabularx}}{{\\linewidth}}{{{col_spec}}}\n" + \
        "\\toprule\n" + "\n\\midrule\n".join(latex_rows) + "\n\\bottomrule\n" + \
        "\\end{tabularx}\n\\end{tcolorbox}"


def is_markdown_separator(line: str) -> bool:
    cells = [cell.strip() for cell in line.strip().split("|")[1:-1]]
    return bool(cells) and all(re.match(r"^:?-{3,}:?$", cell) for cell in cells)


def inline_latex(text: str) -> str:
    escaped = latex_escape(text)
    escaped = re.sub(r"\*\*(.+?)\*\*", r"\\textbf{\1}", escaped)
    escaped = re.sub(r"`(.+?)`", r"\\texttt{\1}", escaped)
    return escaped


def latex_escape(value: object) -> str:
    text = str(value)
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(ch, ch) for ch in text)


if __name__ == "__main__":
    main()
