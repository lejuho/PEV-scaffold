const projectsEl = document.querySelector("#projects");
const consoleEl = document.querySelector("#console");
const showArchivedEl = document.querySelector("#showArchived");
const refreshBtn = document.querySelector("#refresh");
const sendForm = document.querySelector("#sendForm");
const sendProjectEl = document.querySelector("#sendProject");
const sendTargetEl = document.querySelector("#sendTarget");
const sendMessageEl = document.querySelector("#sendMessage");
const quickbarEl = document.querySelector("#quickbar");

let projects = [];
const compactMedia = window.matchMedia("(max-width: 620px)");
const expandedSections = new Set();
let quickProjectId = "";

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
    projectsEl.innerHTML = `<div class="panel">No visible projects. Toggle archived/hidden if needed.</div>`;
    quickbarEl.innerHTML = "";
    return;
  }
  projectsEl.innerHTML = visible.map((p) => {
    const expected = p.expectedDone?.path || "-";
    const pending = p.pendingDone || "-";
    const hiddenClass = p.meta.archived || p.meta.hidden ? " hidden" : "";
    const flowSteps = [
      ["Plan", p.cycle],
      ["Executor", p.flow.waitingFor?.startsWith("claude")],
      ["Done", p.pendingDone || p.expectedDone],
      ["Verifier", p.flow.waitingFor === "codex_review"],
      ["Merge", p.phase === "ready_to_merge"],
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
          <div class="kv"><span class="k">Cycle</span><span class="v">${value(p.cycle)}</span></div>
          <div class="kv"><span class="k">Verdict</span><span class="v">${value(p.verdict)}</span></div>
          <div class="kv"><span class="k">Waiting</span><span class="v">${value(p.flow.waitingFor)}</span></div>
          <div class="kv"><span class="k">Flow</span><span class="v">${value(p.flow.mode)}</span></div>
          <div class="kv"><span class="k">Expected Done</span><span class="v">${expected}</span></div>
          <div class="kv"><span class="k">Pending Done</span><span class="v">${pending}</span></div>
          <div class="kv"><span class="k">Git</span><span class="v">${value(p.git.branch)} @ ${value(p.git.head)} ${p.git.dirty ? "· dirty" : ""}</span></div>
          <div class="kv"><span class="k">Agents</span><span class="v">Claude ${p.agents.claude.idle === null ? "-" : p.agents.claude.idle ? "idle" : "busy"} · Codex ${p.agents.codex.idle === null ? "-" : p.agents.codex.idle ? "idle" : "busy"}</span></div>
        </div>
        <div class="flow">${flowSteps}</div>
        <div class="controls">
          ${section(p, "Flow Mode", "How much PEV may advance automatically.", `
            ${commandButton(p, "Status", "/flow status", "Print exact flow state")}
            ${commandButton(p, "Safe", "/flow safe", "Auto until ready-to-merge")}
            ${commandButton(p, "Full", "/flow full", "Also request merge/next cycle")}
            ${commandButton(p, "Off", "/flow off", "Stop auto advancement", "danger")}
          `)}
          ${section(p, "Cycle Step", "Manual movement through Planner → Executor → Verifier.", `
            ${commandButton(p, "Implement", "/implement", "Ask Claude to start plan")}
            ${commandButton(p, "Fix", "/fix", "Ask Claude to resolve review")}
            ${commandButton(p, "Review", "/review", "Ask Codex for v1 review")}
            ${commandButton(p, "Recheck", "/recheck", "Ask Codex for next review")}
            ${commandButton(p, "Merge", "/merge", "Only when ready_to_merge", "good")}
            <button type="button" class="action-btn danger" data-action="done" data-project="${p.id}">
              <span class="btn-title">Create Done</span>
              <span class="btn-desc">Manual expected pass signal</span>
            </button>
          `)}
          ${section(p, "Agent Pane", "Look at or submit current Claude/Codex terminal state.", `
            <button type="button" class="action-btn" data-action="tail" data-project="${p.id}" data-target="claude">
              <span class="btn-title">Tail Claude</span>
              <span class="btn-desc">Executor terminal output</span>
            </button>
            <button type="button" class="action-btn" data-action="tail" data-project="${p.id}" data-target="codex">
              <span class="btn-title">Tail Codex</span>
              <span class="btn-desc">Verifier terminal output</span>
            </button>
            ${commandButton(p, "Enter Claude", "/enter claude", "Submit current input")}
            ${commandButton(p, "Enter Codex", "/enter codex", "Submit current input")}
          `)}
          ${section(p, "Project View", "Dashboard-only organization; does not change repo status.", `
            ${p.meta.archived ? metaButton(p, "Unarchive", "unarchive", "Return to active list") : metaButton(p, "Archive", "archive", "Move out of active view")}
            ${p.meta.hidden ? metaButton(p, "Show", "show", "Unhide this project") : metaButton(p, "Hide", "hide", "Hide from default view")}
            ${metaButton(p, "Hide Until Next", "hideUntilNextCycle", "Show when a new cycle appears")}
            ${p.meta.pinned ? metaButton(p, "Unpin", "unpin", "Remove top priority") : metaButton(p, "Pin", "pin", "Keep visually important")}
          `, "muted-section")}
        </div>
        <div class="note-row">
          <input data-note="${p.id}" value="${(p.meta.note || "").replaceAll('"', "&quot;")}" placeholder="Dashboard note" />
          <button class="action-btn compact" data-action="note" data-project="${p.id}">
            <span class="btn-title">Save Note</span>
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
  const reviewLabel = selected.latestReview ? "Recheck" : "Review";
  const reviewCommand = selected.latestReview ? "/recheck" : "/review";
  quickbarEl.innerHTML = `
    <div class="quickbar-inner">
      <select class="quick-project" data-action="quick-project" aria-label="Quick action project">
        ${visible.map((p) => `<option value="${p.id}" ${p.id === selected.id ? "selected" : ""}>${p.name}</option>`).join("")}
      </select>
      <div class="quick-actions">
        ${quickButton(selected, "Status", "/flow status")}
        ${quickButton(selected, "Safe", "/flow safe")}
        ${quickButton(selected, "Fix", "/fix")}
        ${quickButton(selected, reviewLabel, reviewCommand, "good")}
      </div>
    </div>
  `;
}

function consoleSummary() {
  if (projects.length === 0) return "No projects are configured.";
  return projects.map((p) => {
    const expected = p.expectedDone?.path || "-";
    const pending = p.pendingDone || "-";
    const claude = p.agents.claude.idle === null ? "-" : p.agents.claude.idle ? "idle" : "busy";
    const codex = p.agents.codex.idle === null ? "-" : p.agents.codex.idle ? "idle" : "busy";
    return [
      `${p.name} (${p.id})`,
      `Phase: ${p.phase} · Cycle: ${value(p.cycle)} · Verdict: ${value(p.verdict)}`,
      `Flow: ${value(p.flow.mode)} · Waiting: ${value(p.flow.waitingFor)}`,
      `Expected done: ${expected}`,
      `Pending done: ${pending}`,
      `Git: ${value(p.git.branch)} @ ${value(p.git.head)}${p.git.dirty ? " · dirty" : ""}`,
      `Agents: Claude ${claude} · Codex ${codex}`,
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
  log(`Running ${projectId}: ${command}`);
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
    alert("No expected done file for this project state.");
    return;
  }
  const summary = prompt(`Create ${expected}?\n\nSummary:`, "Manual PEV dashboard done signal.");
  if (summary === null) return;
  const checks = prompt("Checks run, one per line:", "");
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
    log(body.tail || "(empty)");
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
load().catch((err) => log(`ERROR: ${err.message}`));
setInterval(() => load().catch(() => {}), 5000);
