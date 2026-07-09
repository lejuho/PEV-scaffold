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
const themeToggleBtn = document.querySelector("#themeToggle");
const newProjectBtn = document.querySelector("#newProject");
const initDialog = document.querySelector("#initDialog");
const initForm = document.querySelector("#initForm");
const initCancelBtn = document.querySelector("#initCancel");
const contextDialog = document.querySelector("#contextDialog");
const contextForm = document.querySelector("#contextForm");
const contextCancelBtn = document.querySelector("#ctxCancel");
const ctxUploadEl = document.querySelector("#ctxUpload");
const ctxListEl = document.querySelector("#ctxList");
let contextProjectId = "";

let projects = [];
const compactMedia = window.matchMedia("(max-width: 620px)");
const expandedSections = new Set();
const metricsCache = {};
const metricsExpanded = new Set();
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
    planHint: "cycle plan exists",
    executor: "Executor",
    executorHint: "Claude turn active",
    done: "Done",
    doneHint: "executor done signal",
    verifier: "Verifier",
    verifierHint: "Codex review turn",
    merge: "Merge",
    mergeHint: "ready to merge",
    flowMode: "⚙ Flow Mode",
    flowModeDesc: "How much PEV may advance automatically.",
    status: "📍 Status",
    statusDesc: "Print exact flow state",
    safe: "🛡 Safe",
    safeDesc: "Auto until ready-to-merge",
    full: "🚀 Full",
    fullDesc: "Also request merge/next cycle",
    off: "⏸ Off",
    offDesc: "Stop auto advancement",
    cycleStep: "🔁 Cycle Step",
    cycleStepDesc: "Manual movement through Planner -> Executor -> Verifier.",
    implement: "🛠 Implement",
    implementDesc: "Ask Claude to start plan",
    fix: "🧩 Fix",
    fixDesc: "Ask Claude to resolve review",
    review: "🔎 Review",
    reviewDesc: "Ask Codex for v1 review",
    recheck: "✅ Recheck",
    recheckDesc: "Ask Codex for next review",
    mergeDesc: "Only when ready_to_merge",
    createDone: "📄 Create Done",
    createDoneDesc: "Manual expected pass signal",
    agentPane: "🖥 Agent Pane",
    agentPaneDesc: "Look at or submit current Claude/Codex terminal state.",
    tailClaude: "📜 Tail Claude",
    tailClaudeDesc: "Executor terminal output",
    tailCodex: "📜 Tail Codex",
    tailCodexDesc: "Verifier terminal output",
    enterClaude: "↵ Enter Claude",
    enterCodex: "↵ Enter Codex",
    enterDesc: "Submit current input",
    projectView: "🗂 Project View",
    projectViewDesc: "Dashboard-only organization; does not change repo status.",
    archive: "📦 Archive",
    archiveDesc: "Move out of active view",
    unarchive: "📤 Unarchive",
    unarchiveDesc: "Return to active list",
    hide: "🙈 Hide",
    hideDesc: "Hide from default view",
    show: "👁 Show",
    showDesc: "Unhide this project",
    hideUntilNext: "⏭ Hide Until Next",
    hideUntilNextDesc: "Show when a new cycle appears",
    pin: "📌 Pin",
    pinDesc: "Keep visually important",
    unpin: "📍 Unpin",
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
    metrics: "📊 Metrics",
    loadMetrics: "Load metrics",
    refreshMetrics: "Refresh metrics",
    metricsLoading: "Computing metrics…",
    elapsed: "cycle elapsed",
    thisCycle: "this cycle",
    firstPassStreak: "first-pass streak",
    cumulativeAutonomy: "autonomy total",
    autonomyTooltip: "v1: autonomy = full cycle duration (a human did not drive it). Interventions are counted separately so you can discount them.",
    history: "Cycle history",
    colCycle: "cycle",
    colVerdict: "verdict",
    colPasses: "passes",
    colDuration: "duration",
    colCost: "cost",
    colRework: "rework",
    colInterventions: "interventions",
    colFindFix: "find→fix",
    colTag: "tag",
    errorFeed: "Error feed",
    showMore: "Show more",
    showLess: "Show less",
    noErrors: "No errors recorded.",
    networkUnstable: "Network instability",
    unknownErrors: "Errors",
    firstPassRate: "first-pass rate",
    reworkTotal: "rework total",
    tag_executor: "executor",
    tag_plan: "plan",
    tag_reviewer: "reviewer FP",
    tag_infra: "infra",
    trend: "Trend (last 20)",
    metaBanner: "Meta-cycle suggested — retro PEV against itself.",
    metaCopy: "📋 Copy meta-cycle prompt",
    metaCopied: "Meta-cycle prompt copied to clipboard.",
    newProject: "＋ New",
    ctaEscalated: "⚠ Needs decision",
    ctaEscalatedDesc: "escalated — open Claude tail",
    ctaBusy: "⏳ Working…",
    ctaBusyDesc: "open live output",
    ctaPrepareNext: "🗺 Prepare next cycle",
    ctaPrepareNextDesc: "ask Codex for a plan",
    moreActions: "All actions",
    confirmMerge: "Send /merge? This asks Codex to merge the cycle branch.",
    startAgent: "▶ Start",
    stopAgent: "■ Stop",
    startAgentDesc: "start/resume session",
    stopAgentDesc: "stop current turn/pane",
    initTitle: "New Project",
    initRunning: "Bootstrapping project…",
    initDone: "Project ready.",
    initFailed: "Bootstrap failed — see steps above.",
    themeAria: "Toggle light/dark theme",
    context: "📎 Context",
    contextDesc: "spec / design files",
    ctxTitle: "Context files",
    ctxCategory: "Category",
    ctxName: "Filename",
    ctxContent: "Content",
    ctxUpload: "Attach file (read as text)",
    ctxAdd: "Add",
    ctxClose: "Close",
    ctxEmpty: "No context files yet.",
    ctxAdded: "Context file added.",
    initClaudeModel: "Executor model",
    initClaudeEffort: "Executor effort",
    initSpec: "Spec (optional)",
    initDesign: "Design system (optional)",
    noSpec: "no spec",
    noSpecTitle: "No spec file in docs/spec/ — requirements live only in chat prompts. Add one via 📎 Context.",
    noSpecWarn: "This project has no spec file (docs/spec/). Requirements will come only from the cycle prompt, not a durable artifact. Send /implement anyway?",
    deploy: "🚀 Deploy",
    deployDesc: "run deploy/redeploy.sh",
    confirmDeploy: "Run this project's redeploy script (deploy/redeploy.sh)?",
    deploying: "Deploying…",
    deployDone: "Deployed.",
    deployFailed: "Deploy failed — see output above.",
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
    plan: "계획 있음",
    planHint: "plan.md 확인",
    executor: "Claude 차례",
    executorHint: "Claude 구현/수정 중",
    done: "Done",
    doneHint: "done 파일/신호",
    verifier: "검증",
    verifierHint: "Codex review 차례",
    merge: "병합",
    mergeHint: "merge 가능",
    flowMode: "⚙ Flow 모드",
    flowModeDesc: "PEV가 어디까지 자동 진행할지 정합니다.",
    status: "📍 상태",
    statusDesc: "정확한 Flow 상태 출력",
    safe: "🛡 Safe",
    safeDesc: "ready-to-merge까지 자동 진행",
    full: "🚀 Full",
    fullDesc: "merge/다음 cycle 요청까지 진행",
    off: "⏸ 끄기",
    offDesc: "자동 진행 중지",
    cycleStep: "🔁 사이클 단계",
    cycleStepDesc: "Planner -> Executor -> Verifier 수동 진행.",
    implement: "🛠 구현",
    implementDesc: "Claude에게 plan 시작 요청",
    fix: "🧩 수정",
    fixDesc: "Claude에게 review 해결 요청",
    review: "🔎 리뷰",
    reviewDesc: "Codex에게 v1 review 요청",
    recheck: "✅ 재검증",
    recheckDesc: "Codex에게 다음 review 요청",
    mergeDesc: "ready_to_merge일 때만",
    createDone: "📄 Done 생성",
    createDoneDesc: "수동 expected pass 신호",
    agentPane: "🖥 에이전트 Pane",
    agentPaneDesc: "현재 Claude/Codex 터미널 상태 확인/제출.",
    tailClaude: "📜 Claude 보기",
    tailClaudeDesc: "Executor 터미널 출력",
    tailCodex: "📜 Codex 보기",
    tailCodexDesc: "Verifier 터미널 출력",
    enterClaude: "↵ Claude Enter",
    enterCodex: "↵ Codex Enter",
    enterDesc: "현재 입력 제출",
    projectView: "🗂 프로젝트 표시",
    projectViewDesc: "Dashboard 표시만 변경합니다. repo 상태는 바꾸지 않습니다.",
    archive: "📦 보관",
    archiveDesc: "활성 목록에서 제외",
    unarchive: "📤 보관 해제",
    unarchiveDesc: "활성 목록으로 복귀",
    hide: "🙈 숨김",
    hideDesc: "기본 화면에서 숨김",
    show: "👁 표시",
    showDesc: "프로젝트 다시 표시",
    hideUntilNext: "⏭ 다음까지 숨김",
    hideUntilNextDesc: "새 cycle이 생기면 표시",
    pin: "📌 고정",
    pinDesc: "중요 프로젝트로 표시",
    unpin: "📍 고정 해제",
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
    metrics: "📊 지표",
    loadMetrics: "지표 불러오기",
    refreshMetrics: "지표 새로고침",
    metricsLoading: "지표 계산 중…",
    elapsed: "사이클 경과",
    thisCycle: "이번 사이클",
    firstPassStreak: "first-pass 연속",
    cumulativeAutonomy: "누적 자동",
    autonomyTooltip: "v1 정의: 자동 시간 = 사이클 전체 길이(사람이 직접 조작하지 않은 시간). 개입 횟수는 따로 세어 해석에 참고하세요.",
    history: "사이클 히스토리",
    colCycle: "사이클",
    colVerdict: "판정",
    colPasses: "passes",
    colDuration: "소요",
    colCost: "비용",
    colRework: "재작업",
    colInterventions: "개입",
    colFindFix: "발견→수정",
    colTag: "태그",
    errorFeed: "오류 피드",
    showMore: "더보기",
    showLess: "접기",
    noErrors: "기록된 오류 없음.",
    networkUnstable: "네트워크 불안정",
    unknownErrors: "오류",
    firstPassRate: "first-pass 비율",
    reworkTotal: "누적 재작업",
    tag_executor: "실행자",
    tag_plan: "플랜",
    tag_reviewer: "리뷰어 오탐",
    tag_infra: "인프라",
    trend: "추세 (최근 20)",
    metaBanner: "메타 사이클 제안 — PEV 자체를 회고할 시점입니다.",
    metaCopy: "📋 메타 사이클 프롬프트 복사",
    metaCopied: "메타 사이클 프롬프트를 클립보드에 복사했습니다.",
    newProject: "＋ 새 프로젝트",
    ctaEscalated: "⚠ 판단 필요",
    ctaEscalatedDesc: "escalated — Claude 화면 확인",
    ctaBusy: "⏳ 작업 중…",
    ctaBusyDesc: "실시간 출력 보기",
    ctaPrepareNext: "🗺 다음 사이클 준비",
    ctaPrepareNextDesc: "Codex에게 plan 요청",
    moreActions: "전체 동작",
    confirmMerge: "/merge를 보낼까요? Codex에게 사이클 브랜치 병합을 요청합니다.",
    startAgent: "▶ 시작",
    stopAgent: "■ 중단",
    startAgentDesc: "세션 시작/재개",
    stopAgentDesc: "현재 턴/pane 중단",
    initTitle: "새 프로젝트",
    initRunning: "프로젝트 부트스트랩 중…",
    initDone: "프로젝트 준비 완료.",
    initFailed: "부트스트랩 실패 — 위 단계를 확인하세요.",
    themeAria: "라이트/다크 테마 전환",
    context: "📎 컨텍스트",
    contextDesc: "명세 / 디자인 파일",
    ctxTitle: "컨텍스트 파일",
    ctxCategory: "카테고리",
    ctxName: "파일명",
    ctxContent: "내용",
    ctxUpload: "파일 첨부 (텍스트로 읽음)",
    ctxAdd: "추가",
    ctxClose: "닫기",
    ctxEmpty: "아직 컨텍스트 파일이 없습니다.",
    ctxAdded: "컨텍스트 파일을 추가했습니다.",
    initClaudeModel: "Executor 모델",
    initClaudeEffort: "Executor effort",
    initSpec: "명세 (선택)",
    initDesign: "디자인 시스템 (선택)",
    noSpec: "명세 없음",
    noSpecTitle: "docs/spec/에 명세 파일이 없습니다 — 요구사항이 프롬프트(대화)에만 존재합니다. 📎 컨텍스트로 추가하세요.",
    noSpecWarn: "이 프로젝트에는 명세 파일(docs/spec/)이 없습니다. 요구사항이 지속 아티팩트가 아니라 사이클 프롬프트에서만 옵니다. 그래도 /implement를 보낼까요?",
    deploy: "🚀 배포",
    deployDesc: "deploy/redeploy.sh 실행",
    confirmDeploy: "이 프로젝트의 재배포 스크립트(deploy/redeploy.sh)를 실행할까요?",
    deploying: "배포 중…",
    deployDone: "배포 완료.",
    deployFailed: "배포 실패 — 위 출력을 확인하세요.",
  },
};

function t(key) {
  return copy[language]?.[key] || copy.en[key] || key;
}

/* ── theme (해도 light ↔ 반전 dark, VS Code식 토글) ── */
let theme = localStorage.getItem("pevTheme") || "";
const darkMedia = window.matchMedia("(prefers-color-scheme: dark)");

function effectiveTheme() {
  return theme || (darkMedia.matches ? "dark" : "light");
}

function applyTheme() {
  if (theme) {
    document.documentElement.dataset.theme = theme;
  } else {
    delete document.documentElement.dataset.theme;
  }
  const dark = effectiveTheme() === "dark";
  themeToggleBtn.textContent = dark ? "☀" : "☾";
  themeToggleBtn.setAttribute("aria-label", t("themeAria"));
  let meta = document.querySelector('meta[name="theme-color"]');
  if (!meta) {
    meta = document.createElement("meta");
    meta.name = "theme-color";
    document.head.appendChild(meta);
  }
  meta.content = dark ? "#131C21" : "#E9EFEA";
}

function renderStaticText() {
  document.documentElement.lang = language;
  languageToggleBtn.textContent = language === "ko" ? "EN" : "KO";
  languageToggleBtn.setAttribute("aria-label", language === "ko" ? "Switch to English" : "한국어로 전환");
  refreshBtn.textContent = t("refresh");
  newProjectBtn.textContent = t("newProject");
  document.querySelector("#initTitle").textContent = t("initTitle");
  document.querySelector("#fClaudeModel").textContent = t("initClaudeModel");
  document.querySelector("#fClaudeEffort").textContent = t("initClaudeEffort");
  document.querySelector("#fInitSpec").textContent = t("initSpec");
  document.querySelector("#fInitDesign").textContent = t("initDesign");
  document.querySelector("#ctxTitle").textContent = t("ctxTitle");
  document.querySelector("#fCtxCategory").textContent = t("ctxCategory");
  document.querySelector("#fCtxName").textContent = t("ctxName");
  document.querySelector("#fCtxContent").textContent = t("ctxContent");
  document.querySelector("#fCtxUpload").textContent = t("ctxUpload");
  document.querySelector("#ctxSubmit").textContent = t("ctxAdd");
  document.querySelector("#ctxCancel").textContent = t("ctxClose");
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

function triageRank(p) {
  if (p.phase === "escalated") return 0;
  if (p.phase === "review_blocked") return 1;
  if (p.pendingDone) return 2;
  if (p.phase === "ready_to_merge") return 3;
  if (p.phase === "in_progress") return 4;
  return 5;
}

function visibleProjects() {
  const showArchived = showArchivedEl.checked;
  return projects
    .filter((p) => showArchived || (!p.meta.archived && !p.meta.hidden))
    .slice()
    .sort((a, b) =>
      (b.meta.pinned - a.meta.pinned) ||
      (triageRank(a) - triageRank(b)) ||
      String(a.name).localeCompare(String(b.name)));
}

function sectionKey(project, title) {
  return `${project.id}:${title}`;
}

function isSectionCollapsed(project, title) {
  return !expandedSections.has(sectionKey(project, title));
}

/* phase가 결정하는 카드당 주 액션 하나 */
function primaryAction(p) {
  const claudeBusy = p.agents?.claude?.idle === false;
  const codexBusy = p.agents?.codex?.idle === false;
  if (p.phase === "escalated") {
    return { kind: "tail", target: "claude", cls: "bad", label: t("ctaEscalated"), desc: t("ctaEscalatedDesc") };
  }
  if (claudeBusy || codexBusy) {
    const target = claudeBusy ? "claude" : "codex";
    return { kind: "tail", target, cls: "neutral", label: t("ctaBusy"), desc: `${target} · ${t("ctaBusyDesc")}` };
  }
  if (p.phase === "ready_to_merge") {
    return { kind: "command", command: "/merge", cls: "good", label: `🔀 ${t("merge")}`, desc: t("mergeDesc") };
  }
  if (p.pendingDone) {
    const cmd = p.latestReview ? "/recheck" : "/review";
    const label = p.latestReview ? t("recheck") : t("review");
    return { kind: "command", command: cmd, cls: "good", label: `🔎 ${label}`, desc: t("reviewDesc") };
  }
  if (p.phase === "review_blocked") {
    return { kind: "command", command: "/fix", cls: "", label: `🧩 ${t("fix")}`, desc: t("fixDesc") };
  }
  if (p.phase === "in_progress") {
    return { kind: "command", command: "/implement", cls: "", label: `🛠 ${t("implement")}`, desc: t("implementDesc") };
  }
  return { kind: "command", command: "/prepare_next", cls: "neutral", label: t("ctaPrepareNext"), desc: t("ctaPrepareNextDesc") };
}

function ctaRow(p) {
  const action = primaryAction(p);
  const attrs = action.kind === "tail"
    ? `data-action="tail" data-project="${p.id}" data-target="${action.target}"`
    : `data-action="command" data-project="${p.id}" data-command="${action.command}"`;
  return `
    <div class="cta-row">
      <button type="button" class="cta-btn ${action.cls}" ${attrs}>
        <span class="btn-title">${action.label}</span>
        <span class="btn-desc">${action.desc}</span>
      </button>
      <button type="button" class="cta-more" data-action="toggle-all" data-project="${p.id}" title="${t("moreActions")}" aria-label="${t("moreActions")}">⋯</button>
    </div>`;
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

function flowStep(label, hint, active) {
  return `
    <span class="step ${active ? "active" : ""}">
      <span class="step-label">${label}</span>
      <span class="step-hint">${hint}</span>
    </span>
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

function esc(s) {
  return String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function formatDuration(sec) {
  if (sec === null || sec === undefined) return "-";
  sec = Math.max(0, Math.round(sec));
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m`;
  return `${sec}s`;
}

function formatUsd(v) {
  if (v === null || v === undefined) return "-";
  return `$${Number(v).toFixed(2)}`;
}

function hhmm(iso) {
  if (!iso) return "?";
  const d = new Date(iso);
  if (isNaN(d)) return "?";
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function firstPassStreak(cycles) {
  let streak = 0;
  for (let i = cycles.length - 1; i >= 0; i--) {
    if (cycles[i].finalVerdict === null || cycles[i].finalVerdict === undefined) continue;
    if (cycles[i].firstPass) streak++;
    else break;
  }
  return streak;
}

function currentElapsedSec(project, cycles) {
  const last = cycles[cycles.length - 1];
  if (!last) return null;
  if (last.durationSec !== null && last.durationSec !== undefined) return last.durationSec;
  if (last.startedAt) {
    const start = new Date(last.startedAt).getTime();
    if (!isNaN(start)) return (Date.now() - start) / 1000;
  }
  return null;
}

function metricsSummaryLine(project, m) {
  const cycles = m.cycles || [];
  const last = cycles[cycles.length - 1] || {};
  const parts = [
    `${t("elapsed")} ${formatDuration(currentElapsedSec(project, cycles))}`,
    `${t("thisCycle")} ${formatUsd(last.costUsd)}`,
    `${t("firstPassStreak")} ${firstPassStreak(cycles)}`,
    `${t("cumulativeAutonomy")} ${(m.totals?.autonomyHours ?? 0).toFixed(1)}h`,
  ];
  return `<div class="metrics-summary" title="${esc(t("autonomyTooltip"))}">${parts.map(esc).join(" · ")}</div>`;
}

function sparkline(m) {
  const cycles = (m.cycles || []).slice(-20);
  if (cycles.length === 0) return "";
  const maxCost = Math.max(1e-6, ...cycles.map((c) => c.costUsd || 0));
  const n = cycles.length;
  const slot = 200 / n;
  const bw = Math.max(2, slot * 0.7);
  const bars = cycles.map((c, i) => {
    const h = Math.max(1, ((c.costUsd || 0) / maxCost) * 30);
    const x = i * slot + (slot - bw) / 2;
    const y = 32 - h;
    const fill = c.firstPass ? "var(--good)" : c.passes > 1 ? "var(--warn)" : "var(--muted)";
    return `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${h.toFixed(1)}" rx="1" fill="${fill}"><title>cycle ${c.cycle}: ${formatUsd(c.costUsd)}${c.firstPass ? " · first-pass" : ""}</title></rect>`;
  }).join("");
  return `
    <div class="metrics-subtitle">${t("trend")}</div>
    <svg class="metrics-sparkline" viewBox="0 0 200 34" preserveAspectRatio="none" role="img" aria-label="${t("trend")}">${bars}</svg>`;
}

function verdictShort(v) {
  if (v === "READY_TO_MERGE") return "RTM";
  if (v === "BLOCKED") return "BLK";
  return v || "-";
}

const FAILURE_TAGS = ["executor", "plan", "reviewer", "infra"];

function tagLabel(tag) {
  return t(`tag_${tag}`);
}

function failureTagCell(project, c) {
  const hadBlocked = c.finalVerdict && (!c.firstPass || c.passes > 1 || c.blockedToFixSec !== null);
  if (!hadBlocked) {
    return c.failureTag ? `<span class="tag-chip">${esc(tagLabel(c.failureTag))}</span>` : "-";
  }
  const buttons = FAILURE_TAGS.map((tag) => `
    <button type="button" class="tag-btn ${c.failureTag === tag ? "active" : ""}"
            data-action="tag" data-project="${project.id}" data-cycle="${c.cycle}" data-tag="${tag}">
      ${esc(tagLabel(tag))}
    </button>`).join("");
  return `<div class="tag-buttons">${buttons}</div>`;
}

function historyTable(project, m) {
  const cycles = (m.cycles || []).slice().reverse();
  const expanded = metricsExpanded.has(project.id);
  const shown = expanded ? cycles : cycles.slice(0, 20);
  const rows = shown.map((c) => {
    const tagCell = failureTagCell(project, c);
    return `
      <tr class="${c.firstPass ? "fp-good" : c.passes > 1 ? "fp-rework" : ""}">
        <td>${c.cycle}</td>
        <td>${verdictShort(c.finalVerdict)}</td>
        <td>${c.passes}</td>
        <td>${formatDuration(c.durationSec)}</td>
        <td>${formatUsd(c.costUsd)}</td>
        <td>${formatUsd(c.reworkCostUsd)}</td>
        <td>${c.interventions}</td>
        <td>${formatDuration(c.blockedToFixSec)}</td>
        <td>${tagCell}</td>
      </tr>`;
  }).join("");
  const moreBtn = cycles.length > 20
    ? `<button type="button" class="action-btn compact" data-action="metrics-more" data-project="${project.id}">
         <span class="btn-title">${expanded ? t("showLess") : t("showMore")} (${cycles.length})</span>
       </button>`
    : "";
  return `
    <div class="metrics-history">
      <div class="metrics-subtitle">${t("history")}</div>
      <div class="table-scroll">
        <table class="metrics-table">
          <thead><tr>
            <th>${t("colCycle")}</th><th>${t("colVerdict")}</th><th>${t("colPasses")}</th>
            <th>${t("colDuration")}</th><th>${t("colCost")}</th><th>${t("colRework")}</th>
            <th>${t("colInterventions")}</th><th>${t("colFindFix")}</th><th>${t("colTag")}</th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
      ${moreBtn}
    </div>`;
}

function errorFeed(m) {
  const errors = m.errors || [];
  if (errors.length === 0) return `<div class="metrics-errors"><div class="metrics-subtitle">${t("errorFeed")}</div><div class="muted-line">${t("noErrors")}</div></div>`;
  const items = errors.slice().reverse().slice(0, 12).map((e) => {
    const label = e.kind === "infra" ? t("networkUnstable") : t("unknownErrors");
    const cls = e.kind === "infra" ? "warn" : "bad";
    return `<li class="err-${cls}"><span class="err-label">${esc(label)}</span> ${hhmm(e.firstTs)}–${hhmm(e.lastTs)} (${e.count})</li>`;
  }).join("");
  return `
    <div class="metrics-errors">
      <div class="metrics-subtitle">${t("errorFeed")}</div>
      <ul class="err-list">${items}</ul>
    </div>`;
}

function metaCycleDue(m) {
  const total = m.totals?.cycles || 0;
  if (total === 0 || total % 10 !== 0) return false;
  const last = m.totals?.lastMetaCycleAt;
  return last === null || last === undefined || total - last >= 10;
}

function metaBanner(project, m) {
  if (!metaCycleDue(m)) return "";
  return `
    <div class="meta-banner">
      <span>${esc(t("metaBanner"))}</span>
      <button type="button" class="action-btn compact" data-action="meta-copy" data-project="${project.id}">
        <span class="btn-title">${t("metaCopy")}</span>
      </button>
    </div>`;
}

function metaCyclePrompt(project, m) {
  const tt = m.totals || {};
  const tagCounts = {};
  (m.cycles || []).slice(-20).forEach((c) => {
    if (c.failureTag) tagCounts[c.failureTag] = (tagCounts[c.failureTag] || 0) + 1;
  });
  const tagLine = FAILURE_TAGS.map((tag) => `${tag} ${tagCounts[tag] || 0}`).join(" · ");
  return [
    `Run a PEV meta-cycle for project "${project.name}" using templates/multi-agent-artifact/meta-cycle-template.md.`,
    "",
    "Baseline (from logs/pev-metrics.json → totals):",
    `- cycles: ${tt.cycles}`,
    `- first-pass rate: ${tt.firstPassRate}`,
    `- autonomy hours: ${tt.autonomyHours}`,
    `- cost: $${tt.costUsd} · rework: $${tt.reworkCostUsd}`,
    `- failure tags (last 20): ${tagLine}`,
    "",
    "Follow the template: read the signal, propose ≤3 concrete diffs (each naming",
    "a target metric + value), define the comparison, and append the result to",
    "logs/meta-cycles.jsonl. Do not auto-apply — produce the decision.",
  ].join("\n");
}

function renderMetricsContent(project) {
  const entry = metricsCache[project.id];
  if (!entry) {
    return `<button type="button" class="action-btn" data-action="metrics" data-project="${project.id}">
      <span class="btn-title">${t("metrics")}</span>
      <span class="btn-desc">${t("loadMetrics")}</span>
    </button>`;
  }
  if (entry.loading) {
    return `<div class="metrics-summary">${t("metricsLoading")}</div>`;
  }
  const m = entry.data;
  return `
    ${metaBanner(project, m)}
    ${metricsSummaryLine(project, m)}
    ${sparkline(m)}
    ${historyTable(project, m)}
    ${errorFeed(m)}
    <button type="button" class="action-btn compact" data-action="metrics" data-project="${project.id}">
      <span class="btn-title">${t("refreshMetrics")}</span>
    </button>`;
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
      [t("plan"), t("planHint"), p.cycle],
      [t("executor"), t("executorHint"), p.flow.waitingFor?.startsWith("claude")],
      [t("done"), t("doneHint"), p.pendingDone || p.expectedDone],
      [t("verifier"), t("verifierHint"), p.flow.waitingFor === "codex_review"],
      [t("merge"), t("mergeHint"), p.phase === "ready_to_merge"],
    ].map(([label, hint, active]) => flowStep(label, hint, active)).join("");
    return `
      <article class="card${hiddenClass}" data-project-card="${p.id}">
        <div class="card-head">
          <div>
            <div class="title">${p.meta.pinned ? "★ " : ""}${p.name}<span class="driver-chip">${p.driver || "tmux"}</span>${p.hasSpec === false ? `<span class="driver-chip warn" title="${esc(t("noSpecTitle"))}">⚠ ${t("noSpec")}</span>` : ""}</div>
            <div class="root">${p.root}</div>
          </div>
          ${phaseBadge(p.phase)}
        </div>
        ${ctaRow(p)}
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
        <div class="metrics-block" data-metrics-block="${p.id}">${renderMetricsContent(p)}</div>
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
            <button type="button" class="action-btn good" data-action="deploy" data-project="${p.id}">
              <span class="btn-title">${t("deploy")}</span>
              <span class="btn-desc">${t("deployDesc")}</span>
            </button>
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
            <button type="button" class="action-btn" data-action="agent" data-project="${p.id}" data-agent="claude" data-op="start">
              <span class="btn-title">${t("startAgent")} Claude</span><span class="btn-desc">${t("startAgentDesc")}</span>
            </button>
            <button type="button" class="action-btn danger" data-action="agent" data-project="${p.id}" data-agent="claude" data-op="stop">
              <span class="btn-title">${t("stopAgent")} Claude</span><span class="btn-desc">${t("stopAgentDesc")}</span>
            </button>
            <button type="button" class="action-btn" data-action="agent" data-project="${p.id}" data-agent="codex" data-op="start">
              <span class="btn-title">${t("startAgent")} Codex</span><span class="btn-desc">${t("startAgentDesc")}</span>
            </button>
            <button type="button" class="action-btn danger" data-action="agent" data-project="${p.id}" data-agent="codex" data-op="stop">
              <span class="btn-title">${t("stopAgent")} Codex</span><span class="btn-desc">${t("stopAgentDesc")}</span>
            </button>
          `)}
          ${section(p, t("projectView"), t("projectViewDesc"), `
            <button type="button" class="action-btn" data-action="context" data-project="${p.id}">
              <span class="btn-title">${t("context")}</span><span class="btn-desc">${t("contextDesc")}</span>
            </button>
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

async function loadMetrics(projectId, force = false) {
  metricsCache[projectId] = { loading: true, data: metricsCache[projectId]?.data };
  render();
  try {
    const body = await api(`/api/projects/${encodeURIComponent(projectId)}/metrics${force ? "?force=1" : ""}`);
    metricsCache[projectId] = { loading: false, data: body.metrics };
  } catch (err) {
    delete metricsCache[projectId];
    render();
    throw err;
  }
  render();
}

async function handleAction(button) {
  const project = button.dataset.project;
  if (button.dataset.action === "metrics") {
    await loadMetrics(project, metricsCache[project] && !metricsCache[project].loading);
    return;
  }
  if (button.dataset.action === "meta-copy") {
    const m = metricsCache[project]?.data;
    if (!m) return;
    const text = metaCyclePrompt(projects.find((p) => p.id === project) || { name: project }, m);
    try {
      await navigator.clipboard.writeText(text);
      log(t("metaCopied"));
    } catch {
      log(text);
    }
    return;
  }
  if (button.dataset.action === "tag") {
    const cycle = button.dataset.cycle;
    const current = metricsCache[project]?.data?.cycles?.find((c) => String(c.cycle) === cycle)?.failureTag;
    const next = current === button.dataset.tag ? "" : button.dataset.tag;
    await api(`/api/projects/${encodeURIComponent(project)}/cycles/${encodeURIComponent(cycle)}/tag`, {
      method: "POST",
      body: JSON.stringify({ tag: next }),
    });
    await loadMetrics(project, true);
    return;
  }
  if (button.dataset.action === "metrics-more") {
    if (metricsExpanded.has(project)) metricsExpanded.delete(project);
    else metricsExpanded.add(project);
    render();
    return;
  }
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
  if (button.dataset.action === "toggle-all") {
    const proj = projects.find((p) => p.id === project);
    const titles = [t("flowMode"), t("cycleStep"), t("agentPane"), t("projectView")];
    const keys = titles.map((title) => sectionKey(proj || { id: project }, title));
    const anyOpen = keys.some((key) => expandedSections.has(key));
    keys.forEach((key) => (anyOpen ? expandedSections.delete(key) : expandedSections.add(key)));
    render();
    return;
  }
  if (button.dataset.action === "agent") {
    const body = await api(`/api/projects/${encodeURIComponent(project)}/agent`, {
      method: "POST",
      body: JSON.stringify({ agent: button.dataset.agent, op: button.dataset.op }),
    });
    log(typeof body.result === "string" ? body.result : body.result);
    await load();
    return;
  }
  if (button.dataset.action === "command") {
    const command = button.dataset.command;
    if (command === "/merge" && !window.confirm(t("confirmMerge"))) return;
    if (command === "/implement") {
      const proj = projects.find((p) => p.id === project);
      if (proj && proj.hasSpec === false && !window.confirm(t("noSpecWarn"))) return;
    }
    await runCommand(project, command);
    return;
  }
  if (button.dataset.action === "meta") await updateMeta(project, button.dataset.op);
  if (button.dataset.action === "tail") {
    const body = await api(`/api/projects/${encodeURIComponent(project)}/tail?target=${encodeURIComponent(button.dataset.target)}`);
    log(body.tail || t("empty"));
  }
  if (button.dataset.action === "context") await openContextDialog(project);
  if (button.dataset.action === "deploy") {
    if (!window.confirm(t("confirmDeploy"))) return;
    const body = await api(`/api/projects/${encodeURIComponent(project)}/deploy`, { method: "POST" });
    log(`${t("deploying")} (job ${body.job})`);
    pollDeployJob(body.job);
    return;
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

/* ── theme wiring ── */
themeToggleBtn.addEventListener("click", () => {
  theme = effectiveTheme() === "dark" ? "light" : "dark";
  localStorage.setItem("pevTheme", theme);
  applyTheme();
});
if (darkMedia.addEventListener) darkMedia.addEventListener("change", applyTheme);

/* ── New Project 위저드 ── */
function formatInitStep(s) {
  return `${s.ok === false ? "✗" : "✓"} ${s.step}${s.detail ? ` — ${s.detail}` : ""}`;
}

function pollJob(job, base, labels) {
  const started = Date.now();
  const poll = async () => {
    let status;
    try {
      status = await api(`${base}/${encodeURIComponent(job)}`);
    } catch (err) {
      log(`ERROR: ${err.message}`);
      return;
    }
    const lines = [labels.running, "", ...status.steps.map(formatInitStep)];
    if (!status.running) {
      if (status.summary && status.summary.ok) {
        lines[0] = labels.done(status.summary);
        if (status.summary.next) lines.push("", ...status.summary.next);
      } else {
        lines[0] = labels.failed;
      }
      log(lines.join("\n"));
      await load();
      return;
    }
    log(lines.join("\n"));
    if (Date.now() - started < 20 * 60 * 1000) setTimeout(poll, 2000);
  };
  poll();
}

function pollInitJob(job) {
  pollJob(job, "/api/init", {
    running: t("initRunning"),
    done: (s) => `${t("initDone")} (${s.root})`,
    failed: t("initFailed"),
  });
}

function pollDeployJob(job) {
  pollJob(job, "/api/deploy", {
    running: t("deploying"),
    done: (s) => `${t("deployDone")} (exit ${s.exit})`,
    failed: t("deployFailed"),
  });
}

function syncInitSourceFields() {
  const source = initForm.querySelector('[name="source"]').value;
  initForm.querySelector('[data-init-field="repo"]').style.display = source === "new" ? "none" : "";
  initForm.querySelector('[data-init-field="visibility"]').style.display = source === "new" ? "" : "none";
}
newProjectBtn.addEventListener("click", () => {
  syncInitSourceFields();
  initDialog.showModal();
});
initCancelBtn.addEventListener("click", () => initDialog.close());
initForm.querySelector('[name="source"]').addEventListener("change", syncInitSourceFields);
initForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(initForm).entries());
  const body = {};
  const contextFields = new Set(["spec", "design"]);
  for (const [key, value] of Object.entries(data)) {
    if (!contextFields.has(key) && String(value).trim()) body[key] = String(value).trim();
  }
  const context = [];
  if (String(data.spec || "").trim()) context.push({ category: "spec", content: String(data.spec) });
  if (String(data.design || "").trim()) context.push({ category: "design", content: String(data.design) });
  if (context.length) body.context = context;
  try {
    const res = await api("/api/projects/init", { method: "POST", body: JSON.stringify(body) });
    initDialog.close();
    log(`${t("initRunning")} (job ${res.job})`);
    pollInitJob(res.job);
  } catch (err) {
    log(`ERROR: ${err.message}`);
  }
});

/* ── Context files (spec / design) manager ── */
function renderContextList(context) {
  const cats = ["spec", "design"];
  const parts = cats.map((cat) => {
    const files = (context?.[cat] || []);
    const rows = files.length
      ? files.map((f) => `<li><code>${esc(f.path)}</code> <span class="muted-line">${f.bytes}B</span></li>`).join("")
      : `<li class="muted-line">${t("ctxEmpty")}</li>`;
    return `<div class="ctx-cat"><div class="metrics-subtitle">${cat}</div><ul>${rows}</ul></div>`;
  });
  ctxListEl.innerHTML = parts.join("");
}

async function openContextDialog(projectId) {
  contextProjectId = projectId;
  contextForm.reset();
  ctxListEl.innerHTML = `<div class="muted-line">${t("metricsLoading")}</div>`;
  contextDialog.showModal();
  try {
    const body = await api(`/api/projects/${encodeURIComponent(projectId)}/context`);
    renderContextList(body.context);
  } catch (err) {
    ctxListEl.innerHTML = `<div class="muted-line">ERROR: ${esc(err.message)}</div>`;
  }
}

ctxUploadEl.addEventListener("change", async () => {
  const file = ctxUploadEl.files?.[0];
  if (!file) return;
  const text = await file.text();
  contextForm.querySelector('[name="content"]').value = text;
  const nameField = contextForm.querySelector('[name="name"]');
  if (!nameField.value.trim()) nameField.value = file.name.replace(/[^A-Za-z0-9._-]/g, "-");
});

contextCancelBtn.addEventListener("click", () => contextDialog.close());
contextForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(contextForm).entries());
  const content = String(data.content || "").trim();
  if (!content) return;
  const payload = { category: data.category, content: String(data.content), push: false };
  if (String(data.name || "").trim()) payload.name = String(data.name).trim();
  try {
    const body = await api(`/api/projects/${encodeURIComponent(contextProjectId)}/context`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    log(`${t("ctxAdded")} ${body.result?.path || ""}`.trim());
    contextForm.querySelector('[name="content"]').value = "";
    contextForm.querySelector('[name="name"]').value = "";
    ctxUploadEl.value = "";
    const listBody = await api(`/api/projects/${encodeURIComponent(contextProjectId)}/context`);
    renderContextList(listBody.context);
  } catch (err) {
    log(`ERROR: ${err.message}`);
  }
});

renderStaticText();
applyTheme();
load().catch((err) => log(`ERROR: ${err.message}`));
setInterval(() => {
  if (document.visibilityState === "visible") load().catch(() => {});
}, 5000);
