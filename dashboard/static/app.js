const projectsEl = document.querySelector("#projects");
const consoleEl = document.querySelector("#console");
const showArchivedEl = document.querySelector("#showArchived");
const showArchivedLabelEl = document.querySelector("#showArchivedLabel");
const refreshBtn = document.querySelector("#refresh");
const languageToggleBtn = document.querySelector("#languageToggle");
const consoleTitleEl = document.querySelector("#consoleTitle");
const sendForm = document.querySelector("#sendForm");
const sendProjectEl = document.querySelector("#sendProject");
const sendTargetEl = document.querySelector("#sendTarget");
const sendMessageEl = document.querySelector("#sendMessage");
const sendButtonEl = document.querySelector("#sendButton");
const quickbarEl = document.querySelector("#quickbar");

let projects = [];
const compactMedia = window.matchMedia("(max-width: 620px)");
const expandedSections = new Set();
let quickProjectId = "";
let language = localStorage.getItem("pevLanguage") || "en";

const copy = {
  en: {
    refresh: "Refresh",
    showArchived: "Show archived/hidden",
    console: "Console",
    sendPlaceholder: "Message to send via /say",
    send: "Send",
    noVisibleProjects: "No visible projects. Toggle archived/hidden if needed.",
    cycle: "Cycle",
    verdict: "Verdict",
    waiting: "Waiting",
    flow: "Flow",
    expectedDone: "Expected Done",
    pendingDone: "Pending Done",
    git: "Git",
    agents: "Agents",
    agentStatus: "Agent status",
    roleExecutor: "Executor",
    roleReviewer: "Planner / Reviewer",
    idle: "idle",
    busy: "busy",
    unknown: "unknown",
    plan: "Plan",
    done: "Done",
    verifier: "Verifier",
    merge: "Merge",
    flowMode: "Flow Mode",
    flowModeDesc: "How much PEV may advance automatically.",
    status: "Status",
    statusDesc: "Print exact flow state",
    safe: "Safe",
    safeDesc: "Auto until ready-to-merge",
    full: "Full",
    fullDesc: "Also request merge/next cycle",
    off: "Off",
    offDesc: "Stop auto advancement",
    cycleStep: "Cycle Step",
    cycleStepDesc: "Manual movement through Planner -> Executor -> Verifier.",
    implement: "Implement",
    implementDesc: "Ask Claude to start plan",
    fix: "Fix",
    fixDesc: "Ask Claude to resolve review",
    review: "Review",
    reviewDesc: "Ask Codex for v1 review",
    recheck: "Recheck",
    recheckDesc: "Ask Codex for next review",
    mergeDesc: "Only when ready_to_merge",
    createDone: "Create Done",
    createDoneDesc: "Manual expected pass signal",
    agentPane: "Agent Pane",
    agentPaneDesc: "Look at or submit current Claude/Codex terminal state.",
    tailClaude: "Tail Claude",
    tailClaudeDesc: "Executor terminal output",
    tailCodex: "Tail Codex",
    tailCodexDesc: "Verifier terminal output",
    enterClaude: "Enter Claude",
    enterCodex: "Enter Codex",
    enterDesc: "Submit current input",
    projectView: "Project View",
    projectViewDesc: "Dashboard-only organization; does not change repo status.",
    archive: "Archive",
    archiveDesc: "Move out of active view",
    unarchive: "Unarchive",
    unarchiveDesc: "Return to active list",
    hide: "Hide",
    hideDesc: "Hide from default view",
    show: "Show",
    showDesc: "Unhide this project",
    hideUntilNext: "Hide Until Next",
    hideUntilNextDesc: "Show when a new cycle appears",
    pin: "Pin",
    pinDesc: "Keep visually important",
    unpin: "Unpin",
    unpinDesc: "Remove top priority",
    notePlaceholder: "Dashboard note",
    saveNote: "Save Note",
    quickProject: "Quick action project",
    ready: "Ready.",
    empty: "(empty)",
    running: "Running",
    noExpectedDone: "No expected done file for this project state.",
    createSummary: "Manual PEV dashboard done signal.",
    checksPrompt: "Checks run, one per line:",
  },
  ko: {
    refresh: "새로고침",
    showArchived: "보관/숨김 표시",
    console: "콘솔",
    sendPlaceholder: "/say로 보낼 메시지",
    send: "보내기",
    noVisibleProjects: "보이는 프로젝트가 없습니다. 필요하면 보관/숨김 표시를 켜세요.",
    cycle: "사이클",
    verdict: "판정",
    waiting: "대기",
    flow: "Flow",
    expectedDone: "예상 Done",
    pendingDone: "대기 Done",
    git: "Git",
    agents: "에이전트",
    agentStatus: "에이전트 상태",
    roleExecutor: "Executor",
    roleReviewer: "Planner / Reviewer",
    idle: "대기",
    busy: "작업 중",
    unknown: "알 수 없음",
    plan: "계획",
    done: "Done",
    verifier: "검증",
    merge: "병합",
    flowMode: "Flow 모드",
    flowModeDesc: "PEV가 어디까지 자동 진행할지 정합니다.",
    status: "상태",
    statusDesc: "정확한 Flow 상태 출력",
    safe: "Safe",
    safeDesc: "ready-to-merge까지 자동 진행",
    full: "Full",
    fullDesc: "merge/다음 cycle 요청까지 진행",
    off: "끄기",
    offDesc: "자동 진행 중지",
    cycleStep: "사이클 단계",
    cycleStepDesc: "Planner -> Executor -> Verifier 수동 진행.",
    implement: "구현",
    implementDesc: "Claude에게 plan 시작 요청",
    fix: "수정",
    fixDesc: "Claude에게 review 해결 요청",
    review: "리뷰",
    reviewDesc: "Codex에게 v1 review 요청",
    recheck: "재검증",
    recheckDesc: "Codex에게 다음 review 요청",
    mergeDesc: "ready_to_merge일 때만",
    createDone: "Done 생성",
    createDoneDesc: "수동 expected pass 신호",
    agentPane: "에이전트 Pane",
    agentPaneDesc: "현재 Claude/Codex 터미널 상태 확인/제출.",
    tailClaude: "Claude 보기",
    tailClaudeDesc: "Executor 터미널 출력",
    tailCodex: "Codex 보기",
    tailCodexDesc: "Verifier 터미널 출력",
    enterClaude: "Claude Enter",
    enterCodex: "Codex Enter",
    enterDesc: "현재 입력 제출",
    projectView: "프로젝트 표시",
    projectViewDesc: "Dashboard 표시만 변경합니다. repo 상태는 바꾸지 않습니다.",
    archive: "보관",
    archiveDesc: "활성 목록에서 제외",
    unarchive: "보관 해제",
    unarchiveDesc: "활성 목록으로 복귀",
    hide: "숨김",
    hideDesc: "기본 화면에서 숨김",
    show: "표시",
    showDesc: "프로젝트 다시 표시",
    hideUntilNext: "다음까지 숨김",
    hideUntilNextDesc: "새 cycle이 생기면 표시",
    pin: "고정",
    pinDesc: "중요 프로젝트로 표시",
    unpin: "고정 해제",
    unpinDesc: "우선 표시 제거",
    notePlaceholder: "Dashboard 메모",
    saveNote: "메모 저장",
    quickProject: "빠른 조작 프로젝트",
    ready: "준비됨.",
    empty: "(비어 있음)",
    running: "실행 중",
    noExpectedDone: "현재 프로젝트 상태에 expected done 파일이 없습니다.",
    createSummary: "수동 PEV dashboard done 신호.",
    checksPrompt: "실행한 check를 줄마다 입력:",
  },
};

function t(key) {
  return copy[language]?.[key] || copy.en[key] || key;
}

function renderStaticText() {
  document.documentElement.lang = language;
  languageToggleBtn.textContent = language === "ko" ? "EN" : "KO";
  languageToggleBtn.setAttribute("aria-label", language === "ko" ? "Switch to English" : "한국어로 전환");
  refreshBtn.textContent = t("refresh");
  showArchivedLabelEl.textContent = t("showArchived");
  consoleTitleEl.textContent = t("console");
  sendMessageEl.placeholder = t("sendPlaceholder");
  sendButtonEl.textContent = t("send");
  if (!consoleEl.dataset.mode) {
    consoleEl.textContent = t("ready");
  }
}

function log(value) {
  consoleEl.dataset.mode = "manual";
  if (typeof value === "string") {
    consoleEl.textContent = value;
  } else {
    consoleEl.textContent = JSON.stringify(value, null, 2);
  }
}

function autoLog(value) {
  consoleEl.dataset.mode = "auto";
  consoleEl.textContent = value;
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok || body.ok === false) throw new Error(body.error || `HTTP ${res.status}`);
  return body;
}

function phaseBadge(phase) {
  const cls = phase === "ready_to_merge" ? "good" : phase === "review_blocked" || phase === "escalated" ? "bad" : "warn";
  return `<span class="badge ${cls}">${phase || "-"}</span>`;
}

function value(v) {
  return v === null || v === undefined || v === "" ? "-" : String(v);
}

function visibleProjects() {
  const showArchived = showArchivedEl.checked;
  return projects.filter((p) => showArchived || (!p.meta.archived && !p.meta.hidden));
}

function sectionKey(project, title) {
  return `${project.id}:${title}`;
}

function isSectionCollapsed(project, title) {
  return compactMedia.matches && !expandedSections.has(sectionKey(project, title));
}

function agentState(agent) {
  if (agent.idle === null) return "unknown";
  return agent.idle ? "idle" : "busy";
}

function agentStatusCard(name, role, state, brand) {
  return `
    <div class="agent-status ${brand} ${state}">
      <div>
        <span class="agent-name">${name}</span>
        <span class="agent-role">${role}</span>
      </div>
      <span class="agent-pill ${state}">
        <span class="agent-dot" aria-hidden="true"></span>
        ${t(state)}
      </span>
    </div>
  `;
}

function agentStatusRow(project) {
  const claudeState = agentState(project.agents.claude);
  const codexState = agentState(project.agents.codex);
  return `
    <div class="agent-status-row" aria-label="${t("agentStatus")}">
      ${agentStatusCard("Claude", t("roleExecutor"), claudeState, "claude")}
      ${agentStatusCard("Codex", t("roleReviewer"), codexState, "codex")}
    </div>
  `;
}

function commandButton(project, label, command, description = "", cls = "") {
  return `
    <button type="button" class="action-btn ${cls}" data-action="command" data-project="${project.id}" data-command="${command}">
      <span class="btn-title">${label}</span>
      ${description ? `<span class="btn-desc">${description}</span>` : ""}
    </button>
  `;
}

function metaButton(project, label, op, description = "", cls = "") {
  return `
    <button type="button" class="action-btn ${cls}" data-action="meta" data-project="${project.id}" data-op="${op}">
      <span class="btn-title">${label}</span>
      ${description ? `<span class="btn-desc">${description}</span>` : ""}
    </button>
  `;
}

function section(project, title, subtitle, body, cls = "") {
  const key = sectionKey(project, title);
  const collapsed = isSectionCollapsed(project, title);
  return `
    <section class="control-section ${cls} ${collapsed ? "is-collapsed" : ""}">
      <button
        type="button"
        class="section-toggle"
        data-action="toggle-section"
        data-project="${project.id}"
        data-section="${key}"
        aria-expanded="${collapsed ? "false" : "true"}"
      >
        <span>
          <span class="section-title">${title}</span>
          <span class="section-subtitle">${subtitle}</span>
        </span>
        <span class="section-caret" aria-hidden="true">v</span>
      </button>
      <div class="section-body button-grid">${body}</div>
    </section>
  `;
}

function render() {
  const visible = visibleProjects();
  if (visible.length === 0) {
    projectsEl.innerHTML = `<div class="panel">${t("noVisibleProjects")}</div>`;
    quickbarEl.innerHTML = "";
    return;
  }
  projectsEl.innerHTML = visible.map((p) => {
    const expected = p.expectedDone?.path || "-";
    const pending = p.pendingDone || "-";
    const hiddenClass = p.meta.archived || p.meta.hidden ? " hidden" : "";
    const flowSteps = [
      [t("plan"), p.cycle],
      ["Executor", p.flow.waitingFor?.startsWith("claude")],
      [t("done"), p.pendingDone || p.expectedDone],
      [t("verifier"), p.flow.waitingFor === "codex_review"],
      [t("merge"), p.phase === "ready_to_merge"],
    ].map(([label, active]) => `<span class="step ${active ? "active" : ""}">${label}</span>`).join("");
    return `
      <article class="card${hiddenClass}" data-project-card="${p.id}">
        <div class="card-head">
          <div>
            <div class="title">${p.meta.pinned ? "★ " : ""}${p.name}</div>
            <div class="root">${p.root}</div>
          </div>
          ${phaseBadge(p.phase)}
        </div>
        <div class="grid">
          <div class="kv"><span class="k">${t("cycle")}</span><span class="v">${value(p.cycle)}</span></div>
          <div class="kv"><span class="k">${t("verdict")}</span><span class="v">${value(p.verdict)}</span></div>
          <div class="kv"><span class="k">${t("waiting")}</span><span class="v">${value(p.flow.waitingFor)}</span></div>
          <div class="kv"><span class="k">${t("flow")}</span><span class="v">${value(p.flow.mode)}</span></div>
          <div class="kv"><span class="k">${t("expectedDone")}</span><span class="v">${expected}</span></div>
          <div class="kv"><span class="k">${t("pendingDone")}</span><span class="v">${pending}</span></div>
          <div class="kv"><span class="k">${t("git")}</span><span class="v">${value(p.git.branch)} @ ${value(p.git.head)} ${p.git.dirty ? "· dirty" : ""}</span></div>
          <div class="kv"><span class="k">${t("agents")}</span><span class="v">Claude ${t(agentState(p.agents.claude))} · Codex ${t(agentState(p.agents.codex))}</span></div>
        </div>
        ${agentStatusRow(p)}
        <div class="flow">${flowSteps}</div>
        <div class="controls">
          ${section(p, t("flowMode"), t("flowModeDesc"), `
            ${commandButton(p, t("status"), "/flow status", t("statusDesc"))}
            ${commandButton(p, t("safe"), "/flow safe", t("safeDesc"))}
            ${commandButton(p, t("full"), "/flow full", t("fullDesc"))}
            ${commandButton(p, t("off"), "/flow off", t("offDesc"), "danger")}
          `)}
          ${section(p, t("cycleStep"), t("cycleStepDesc"), `
            ${commandButton(p, t("implement"), "/implement", t("implementDesc"))}
            ${commandButton(p, t("fix"), "/fix", t("fixDesc"))}
            ${commandButton(p, t("review"), "/review", t("reviewDesc"))}
            ${commandButton(p, t("recheck"), "/recheck", t("recheckDesc"))}
            ${commandButton(p, t("merge"), "/merge", t("mergeDesc"), "good")}
            <button type="button" class="action-btn danger" data-action="done" data-project="${p.id}">
              <span class="btn-title">${t("createDone")}</span>
              <span class="btn-desc">${t("createDoneDesc")}</span>
            </button>
          `)}
          ${section(p, t("agentPane"), t("agentPaneDesc"), `
            <button type="button" class="action-btn" data-action="tail" data-project="${p.id}" data-target="claude">
              <span class="btn-title">${t("tailClaude")}</span>
              <span class="btn-desc">${t("tailClaudeDesc")}</span>
            </button>
            <button type="button" class="action-btn" data-action="tail" data-project="${p.id}" data-target="codex">
              <span class="btn-title">${t("tailCodex")}</span>
              <span class="btn-desc">${t("tailCodexDesc")}</span>
            </button>
            ${commandButton(p, t("enterClaude"), "/enter claude", t("enterDesc"))}
            ${commandButton(p, t("enterCodex"), "/enter codex", t("enterDesc"))}
          `)}
          ${section(p, t("projectView"), t("projectViewDesc"), `
            ${p.meta.archived ? metaButton(p, t("unarchive"), "unarchive", t("unarchiveDesc")) : metaButton(p, t("archive"), "archive", t("archiveDesc"))}
            ${p.meta.hidden ? metaButton(p, t("show"), "show", t("showDesc")) : metaButton(p, t("hide"), "hide", t("hideDesc"))}
            ${metaButton(p, t("hideUntilNext"), "hideUntilNextCycle", t("hideUntilNextDesc"))}
            ${p.meta.pinned ? metaButton(p, t("unpin"), "unpin", t("unpinDesc")) : metaButton(p, t("pin"), "pin", t("pinDesc"))}
          `, "muted-section")}
        </div>
        <div class="note-row">
          <input data-note="${p.id}" value="${(p.meta.note || "").replaceAll('"', "&quot;")}" placeholder="${t("notePlaceholder")}" />
          <button class="action-btn compact" data-action="note" data-project="${p.id}">
            <span class="btn-title">${t("saveNote")}</span>
          </button>
        </div>
      </article>
    `;
  }).join("");
  renderSendProjects();
  renderQuickbar(visible);
}

function renderSendProjects() {
  const previous = sendProjectEl.value;
  sendProjectEl.innerHTML = projects.map((p) => `<option value="${p.id}">${p.name}</option>`).join("");
  if (projects.some((p) => p.id === previous)) {
    sendProjectEl.value = previous;
  }
}

function quickButton(project, label, command, cls = "") {
  return `
    <button type="button" class="quick-btn ${cls}" data-action="command" data-project="${project.id}" data-command="${command}">
      ${label}
    </button>
  `;
}

function renderQuickbar(visible) {
  if (visible.length === 0) {
    quickbarEl.innerHTML = "";
    return;
  }
  const selected = visible.find((p) => p.id === quickProjectId) || visible.find((p) => p.meta.pinned) || visible[0];
  quickProjectId = selected.id;
  const reviewLabel = selected.latestReview ? t("recheck") : t("review");
  const reviewCommand = selected.latestReview ? "/recheck" : "/review";
  quickbarEl.innerHTML = `
    <div class="quickbar-inner">
      <select class="quick-project" data-action="quick-project" aria-label="${t("quickProject")}">
        ${visible.map((p) => `<option value="${p.id}" ${p.id === selected.id ? "selected" : ""}>${p.name}</option>`).join("")}
      </select>
      <div class="quick-actions">
        ${quickButton(selected, t("status"), "/flow status")}
        ${quickButton(selected, t("safe"), "/flow safe")}
        ${quickButton(selected, t("fix"), "/fix")}
        ${quickButton(selected, reviewLabel, reviewCommand, "good")}
      </div>
    </div>
  `;
}

function consoleSummary() {
  if (projects.length === 0) return language === "ko" ? "설정된 프로젝트가 없습니다." : "No projects are configured.";
  return projects.map((p) => {
    const expected = p.expectedDone?.path || "-";
    const pending = p.pendingDone || "-";
    const claude = t(agentState(p.agents.claude));
    const codex = t(agentState(p.agents.codex));
    return [
      `${p.name} (${p.id})`,
      `Phase: ${p.phase} · ${t("cycle")}: ${value(p.cycle)} · ${t("verdict")}: ${value(p.verdict)}`,
      `${t("flow")}: ${value(p.flow.mode)} · ${t("waiting")}: ${value(p.flow.waitingFor)}`,
      `${t("expectedDone")}: ${expected}`,
      `${t("pendingDone")}: ${pending}`,
      `${t("git")}: ${value(p.git.branch)} @ ${value(p.git.head)}${p.git.dirty ? " · dirty" : ""}`,
      `${t("agents")}: Claude ${claude} · Codex ${codex}`,
    ].join("\n");
  }).join("\n\n");
}

async function load(options = {}) {
  const body = await api("/api/projects");
  projects = body.projects;
  render();
  if (options.forceConsole || consoleEl.dataset.mode !== "manual") {
    autoLog(consoleSummary());
  }
}

async function runCommand(projectId, command) {
  log(`${t("running")} ${projectId}: ${command}`);
  const body = await api(`/api/projects/${encodeURIComponent(projectId)}/command`, {
    method: "POST",
    body: JSON.stringify({ command }),
  });
  log(body.result.stdout || body.result.stderr || body.result);
  await load();
}

async function sendMessage() {
  const projectId = sendProjectEl.value;
  const target = sendTargetEl.value;
  const message = sendMessageEl.value.trim();
  if (!projectId || !target || !message) return;
  await runCommand(projectId, `/say ${target} ${message}`);
  sendMessageEl.value = "";
}

async function updateMeta(projectId, op, extra = {}) {
  const body = await api(`/api/projects/${encodeURIComponent(projectId)}/meta`, {
    method: "POST",
    body: JSON.stringify({ op, ...extra }),
  });
  log(body);
  await load();
}

async function createDone(projectId) {
  const project = projects.find((p) => p.id === projectId);
  const expected = project?.expectedDone?.path;
  if (!expected) {
    alert(t("noExpectedDone"));
    return;
  }
  const summary = prompt(`${t("createDone")} ${expected}?\n\nSummary:`, t("createSummary"));
  if (summary === null) return;
  const checks = prompt(t("checksPrompt"), "");
  const body = await api(`/api/projects/${encodeURIComponent(projectId)}/done`, {
    method: "POST",
    body: JSON.stringify({ summary, checks: checks || "" }),
  });
  log(body);
  await load();
}

async function handleAction(button) {
  const project = button.dataset.project;
  if (button.dataset.action === "toggle-section") {
    const key = button.dataset.section;
    if (expandedSections.has(key)) {
      expandedSections.delete(key);
    } else {
      expandedSections.add(key);
    }
    render();
    return;
  }
  if (button.dataset.action === "command") await runCommand(project, button.dataset.command);
  if (button.dataset.action === "meta") await updateMeta(project, button.dataset.op);
  if (button.dataset.action === "tail") {
    const body = await api(`/api/projects/${encodeURIComponent(project)}/tail?target=${encodeURIComponent(button.dataset.target)}`);
    log(body.tail || t("empty"));
  }
  if (button.dataset.action === "done") await createDone(project);
  if (button.dataset.action === "note") {
    const input = document.querySelector(`[data-note="${CSS.escape(project)}"]`);
    await updateMeta(project, "note", { note: input?.value || "" });
  }
}

projectsEl.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  try {
    await handleAction(button);
  } catch (err) {
    log(`ERROR: ${err.message}`);
  }
});

quickbarEl.addEventListener("click", async (event) => {
  const button = event.target.closest("button");
  if (!button) return;
  try {
    await handleAction(button);
  } catch (err) {
    log(`ERROR: ${err.message}`);
  }
});

quickbarEl.addEventListener("change", (event) => {
  if (event.target.dataset.action !== "quick-project") return;
  quickProjectId = event.target.value;
  renderQuickbar(visibleProjects());
});

refreshBtn.addEventListener("click", () => load({ forceConsole: true }).catch((err) => log(`ERROR: ${err.message}`)));
languageToggleBtn.addEventListener("click", () => {
  language = language === "ko" ? "en" : "ko";
  localStorage.setItem("pevLanguage", language);
  renderStaticText();
  render();
  if (consoleEl.dataset.mode !== "manual") {
    autoLog(consoleSummary());
  }
});
showArchivedEl.addEventListener("change", render);
sendForm.addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage().catch((err) => log(`ERROR: ${err.message}`));
});
if (compactMedia.addEventListener) {
  compactMedia.addEventListener("change", render);
} else {
  compactMedia.addListener(render);
}
renderStaticText();
load().catch((err) => log(`ERROR: ${err.message}`));
setInterval(() => load().catch(() => {}), 5000);
