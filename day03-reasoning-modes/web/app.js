const METHODS = ["direct", "cot", "self_prompt", "panel"];
const METHOD_META = {
  direct: {
    label: "Прямой ответ",
    short: "Direct",
    color: "#4f8cff",
    idea: "Без указаний о рассуждении — только задача и контракт ответа.",
    stages: ["solve"],
  },
  cot: {
    label: "Решай пошагово",
    short: "Step by step",
    color: "#2dd4bf",
    idea: "К задаче добавлена инструкция «решай пошагово, покажи рассуждение».",
    stages: ["reasoning"],
  },
  self_prompt: {
    label: "Мета-промпт",
    short: "Self prompt",
    color: "#b46cff",
    idea: "Модель сначала сама составляет промпт, затем решает по нему (2 вызова).",
    stages: ["generate_prompt", "leak_check", "solve"],
  },
  panel: {
    label: "Группа экспертов",
    short: "Expert group",
    color: "#f6b84b",
    idea: "Три роли (аналитик, инженер, критик) заданы внутри одного промпта.",
    stages: ["experts"],
  },
};

// Человекочитаемые подписи активности для каждого метода/stage.
const STAGE_ACTIVITY = {
  direct: { solve: "Модель формирует прямой ответ" },
  cot: { reasoning: "Модель решает задачу пошагово" },
  self_prompt: {
    generate_prompt: "Call 1/2 · модель создаёт мета-промпт",
    leak_check: "Проверяем промпт на утечку ответа",
    solve: "Call 2/2 · модель решает по созданному промпту",
  },
  panel: { experts: "Группа экспертов анализирует задачу" },
};

const STATUS_LABELS = {
  waiting: "WAITING",
  running: "RUNNING",
  cancelled: "CANCELLED",
  ok: "DONE",
  correct: "CORRECT",
  wrong: "WRONG",
  truncated: "TRUNCATED",
  contaminated: "CONTAMINATED",
  blocked: "BLOCKED",
  unparseable: "UNPARSEABLE",
  error: "ERROR",
  skipped: "SKIPPED",
};

const REQUEST_LABELS = {
  connecting: "CONNECTING",
  waiting_first_token: "WAITING FIRST TOKEN",
  streaming: "STREAMING RESPONSE",
  finalizing: "FINALIZING",
  complete: "COMPLETE",
};

const state = {
  tasks: [],
  selectedTaskId: null,
  activeTaskId: null,
  currentTask: null,
  document: null,
  raw: {},
  runs: [],
  methodStates: {},
  failures: {},
  runId: null,
  running: false,
  startedAt: null,
  elapsedTimer: null,
  eventSource: null,
  callsEstimate: 5,
  activeMethod: null,
  activeStage: null,
  stageStartedAt: null,
  lastHeartbeatAt: null,
  cancelSummary: null,
};

const $ = (id) => document.getElementById(id);

function resetMethodStates() {
  state.methodStates = Object.fromEntries(
    METHODS.map((method) => [
      method,
      {
        status: "waiting",
        answer: "-",
        correct: null,
        calls: 0,
        tokens: 0,
        latency: 0,
        prompts: [],
        answerRaw: "",
        outputs: {},
        requestStates: {},
        stages: METHOD_META[method].stages.map((name) => ({
          name,
          status: "waiting",
          tokens: 0,
          latency: 0,
        })),
      },
    ]),
  );
}

function resetFailures() {
  state.failures = {
    wrong: 0,
    unparseable: 0,
    truncated: 0,
    blocked: 0,
    contaminated: 0,
    error: 0,
  };
}

function compactNumber(value) {
  if (!value) return "0";
  if (value >= 1000) return `${(value / 1000).toFixed(1)}k`;
  return String(value);
}

function statusText(status) {
  return STATUS_LABELS[status] || String(status).toUpperCase();
}

function setStatus(status, label) {
  const dot = $("statusDot");
  dot.className = `status-dot ${status}`;
  $("statusLabel").textContent = label;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function methodRuns(method) {
  return state.runs.filter((run) => run.method === method);
}

function activityLabel(method, stage) {
  return (STAGE_ACTIVITY[method] && STAGE_ACTIVITY[method][stage]) || "Запрос выполняется";
}

function setButtons(running) {
  $("runButton").disabled = running;
  $("stopButton").disabled = !running;
  $("taskInput").disabled = running;
  $("modelInput").disabled = running;
  $("thinkingInput").disabled = running;
  if (running) {
    $("runButton").textContent = "▶ Выполняется…";
    $("stopButton").textContent = "■ Остановить";
  } else {
    $("runButton").textContent = "▶ Сравнить 4 способа";
    $("stopButton").textContent = "■ Остановить";
  }
}

function getSelectedTask() {
  return state.tasks.find((task) => task.id === state.selectedTaskId) || null;
}

function liveOutputText(item) {
  return Object.entries(item.outputs || {})
    .filter(([, text]) => text)
    .map(([stage, text]) => {
      const label = stage === "generate_prompt"
        ? "CALL 1/2 · META-PROMPT"
        : stage === "solve" && item.outputs.generate_prompt
          ? "CALL 2/2 · SOLUTION"
          : stage.toUpperCase();
      return `## ${label}\n${text}`;
    })
    .join("\n\n");
}

function updateLiveIndicator(method) {
  const item = state.methodStates[method];
  if (!item || state.activeMethod !== method) return;
  const requestState = state.activeStage
    ? item.requestStates[state.activeStage]
    : null;
  const requestLabel = REQUEST_LABELS[requestState] || "REQUEST ACTIVE";
  const label = document.querySelector(`.method-card.active [data-live-label="${method}"]`);
  if (label) {
    label.textContent = `${requestLabel} · ${activityLabel(method, state.activeStage)}`;
  }
}

function updateStreamingResponse(method) {
  const item = state.methodStates[method];
  if (!item) return;
  const response = item.answerRaw || liveOutputText(item);
  const el = document.querySelector(`.method-card.active [data-stream-response="${method}"]`);
  if (el) {
    el.textContent = response ? `${response}\n▋` : "";
    el.scrollTop = el.scrollHeight;
  }
}

function resetLiveRunView() {
  state.document = null;
  state.raw = {};
  state.runs = [];
  state.runId = null;
  state.activeTaskId = null;
  state.running = false;
  state.startedAt = null;
  state.activeMethod = null;
  state.activeStage = null;
  state.stageStartedAt = null;
  state.lastHeartbeatAt = null;
  state.cancelSummary = null;
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
  resetMethodStates();
  resetFailures();
}

function markRunningMethodsCancelled() {
  for (const method of METHODS) {
    const item = state.methodStates[method];
    if (!item || item.status !== "running") continue;
    item.status = "cancelled";
    for (const stage of item.stages) {
      if (stage.status === "running" || stage.status === "waiting") {
        stage.status = "skipped";
      }
    }
  }
}

function renderTask() {
  const task = state.currentTask || getSelectedTask();
  if (!task) return;
  const taskId = task.id || task.task_id;
  $("taskFamilyLabel").textContent = `Задача · ${task.family}`;
  $("taskTitle").textContent = taskId;
  $("taskPrompt").textContent = task.prompt;
  const baseline = task.baseline
    ? `≈ ${Math.round(task.baseline * 100)}%`
    : "≈ 0%";
  $("baselineLabel").textContent = `baseline ${baseline}`;
}

function renderMethodCards() {
  $("methodGrid").innerHTML = METHODS.map((method, index) => {
    const meta = METHOD_META[method];
    const item = state.methodStates[method];
    const isActive = state.activeMethod === method;
    const isDone = item.status === "correct" || item.status === "ok" || item.status === "wrong" ||
      ["truncated", "contaminated", "blocked", "unparseable", "error"].includes(item.status);
    const resultStatus = item.correct === true ? "correct" : item.status;
    const answer = item.answer || "-";
    const response = liveOutputText(item) || item.answerRaw;
    const prompts = item.prompts || [];
    const requestState = state.activeStage
      ? item.requestStates[state.activeStage]
      : null;
    const requestLabel = REQUEST_LABELS[requestState] || "REQUEST ACTIVE";

    // Индикатор активности (только для активной карточки).
    const liveIndicator = isActive
      ? `
        <div class="live-indicator">
          <div class="activity-bar"></div>
          <div class="live-row">
            <span class="live-dot"></span>
            <span class="live-label" data-live-label="${method}">${escapeHtml(requestLabel)} · ${escapeHtml(activityLabel(method, state.activeStage))}</span>
            <span class="stage-elapsed">0.0s</span>
          </div>
        </div>
      `
      : "";

    const promptBlocks = prompts.length
      ? prompts
          .map(
            (p, i) => `
              <div class="prompt-call">
                <span class="prompt-call-label">${
                  prompts.length > 1 ? `CALL ${i + 1}` : "PROMPT"
                }</span>
                <pre class="prompt-text">${escapeHtml(p.slice(0, 1400))}</pre>
              </div>
            `,
          )
          .join("")
      : "";

    const responseBlock = response
      ? `
        <div class="flow-block">
          <p class="flow-label">MODEL RESPONSE${isActive ? " · LIVE" : ""}</p>
          <pre class="trace" data-stream-response="${method}">${escapeHtml(response.slice(0, 5000))}${isActive ? "\n▋" : ""}</pre>
        </div>
      `
      : isActive
        ? `
          <div class="flow-block">
            <p class="flow-label">MODEL RESPONSE · LIVE</p>
            <pre class="trace" data-stream-response="${method}"></pre>
          </div>
        `
        : "";

    const answerBlock = isDone
      ? `
        <div class="answer-block">
          <p class="answer-label">FINAL ANSWER</p>
          <div class="answer-value">
            ${escapeHtml(answer)}
            <span class="correct-mark ${item.correct === true ? "ok" : item.correct === false ? "wrong" : ""}">${
              item.correct === true ? "✓" : item.correct === false ? "✕" : ""
            }</span>
          </div>
        </div>
      `
      : "";

    const statusPill = isActive
      ? `<span class="status-pill status-running">● LIVE</span>`
      : `<span class="status-pill status-${resultStatus}">${statusText(resultStatus)}</span>`;

    return `
      <article class="method-card ${isActive ? "active" : ""} ${isDone ? "done" : ""}" style="--method-color:${meta.color}">
        <div class="method-head">
          <h3 class="method-title">
            <span class="method-num">${index + 1}</span> ${meta.label}
          </h3>
          ${statusPill}
        </div>
        <p class="method-idea">${meta.idea}</p>

        ${liveIndicator}

        ${
          prompts.length
            ? `<div class="flow-block">
                <p class="flow-label">PROMPT SENT</p>
                ${promptBlocks}
              </div>`
            : ""
        }

        ${responseBlock}
        ${answerBlock}

        <div class="method-stats">
          <span><b>${item.calls}</b> calls</span>
          <span><b>${compactNumber(item.tokens)}</b> tokens</span>
          <span><b>${item.latency ? item.latency.toFixed(1) : "-"}</b> sec</span>
        </div>
      </article>
    `;
  }).join("");
  $("methodGrid").classList.toggle("has-active", state.activeMethod != null);
}

function renderGlobalStatus() {
  const doneCount = METHODS.filter((m) => methodRuns(m).length > 0).length;
  const calls = state.runs.reduce((sum, r) => sum + (r.calls || 0), 0);

  let text;
  let dotClass = "waiting";
  if (state.running && state.activeMethod) {
    const meta = METHOD_META[state.activeMethod];
    text = `Сейчас: ${meta.label} · ${activityLabel(state.activeMethod, state.activeStage)}`;
    dotClass = "running";
  } else if (state.runs.length > 0 && !state.running) {
    text = `Завершено · ${doneCount} метода · ${calls} API-запросов`;
    dotClass = "complete";
  } else {
    text = "Готов к запуску";
    dotClass = "waiting";
  }

  $("globalDot").className = `status-dot ${dotClass}`;
  $("globalText").textContent = text;
  $("globalMethods").textContent = `Методы ${doneCount}/4`;
  $("globalCalls").textContent = `API ${calls}/5`;
}

function renderScore() {
  $("scoreBody").innerHTML = METHODS.map((method) => {
    const row = methodRuns(method)[0];
    const answer = row ? row.answer_norm || "-" : "-";
    const correct = row ? row.correct : null;
    const calls = row ? row.calls || 0 : 0;
    const tokens = row
      ? (row.prompt_tokens || 0) + (row.output_tokens || 0)
      : 0;
    const latency = row ? row.latency_s || 0 : 0;
    const mark = correct === true ? "✓" : correct === false ? "✕" : "-";
    return `
      <tr>
        <td style="color:${METHOD_META[method].color}">${METHOD_META[method].label}</td>
        <td>${escapeHtml(answer)}</td>
        <td>${mark}</td>
        <td>${calls}</td>
        <td>${compactNumber(tokens)}</td>
        <td>${latency ? `${latency.toFixed(1)}s` : "-"}</td>
      </tr>
    `;
  }).join("");

  const correct = METHODS.filter((m) => {
    const row = methodRuns(m)[0];
    return row && row.correct === true;
  });
  const wrong = METHODS.filter((m) => {
    const row = methodRuns(m)[0];
    return row && row.correct === false;
  });

  if (state.cancelSummary) {
    $("summaryLine").textContent = state.cancelSummary;
  } else if (state.runs.length === 0) {
    $("summaryLine").textContent = "Запустите сравнение, чтобы увидеть результат.";
  } else if (correct.length === METHODS.length) {
    $("summaryLine").textContent = "Все четыре способа дали правильный ответ.";
  } else if (correct.length === 0) {
    $("summaryLine").textContent = "Ни один способ не дал правильного ответа.";
  } else {
    $("summaryLine").textContent =
      `Правильно: ${correct.map((m) => METHOD_META[m].label).join(", ")}. ` +
      `Ошибка: ${wrong.map((m) => METHOD_META[m].label).join(", ") || "—"}.`;
  }
}

function renderProgress() {
  const calls = state.runs.reduce((sum, r) => sum + (r.calls || 0), 0);
  const total = state.callsEstimate || 1;
  $("progressFill").style.width = `${Math.min(100, Math.round((calls / total) * 100))}%`;
  $("progressText").textContent = `${calls} / ~${total} API calls`;
}

function renderResults() {
  const rows = METHODS.map((method) => {
    const row = methodRuns(method)[0];
    return {
      method,
      row,
      correct: row ? row.correct : null,
      tokens: row ? (row.prompt_tokens || 0) + (row.output_tokens || 0) : 0,
    };
  });

  const correct = rows.filter((r) => r.correct === true);
  const wrong = rows.filter((r) => r.correct === false);

  let verdict;
  if (state.runs.length === 0) {
    verdict = "Запустите сравнение, чтобы увидеть итог.";
  } else if (correct.length === METHODS.length) {
    verdict = "По точности: ничья — все четыре способа дали правильный ответ.";
  } else if (correct.length === 0) {
    verdict = "Ни один способ не дал правильного ответа на этой задаче.";
  } else {
    verdict =
      `Правильно: ${correct.map((r) => METHOD_META[r.method].label).join(", ")}. ` +
      `Ошибка: ${wrong.map((r) => METHOD_META[r.method].label).join(", ") || "—"}.`;
  }

  const cheapest = correct.slice().sort((a, b) => a.tokens - b.tokens)[0];
  if (cheapest) {
    verdict += ` Самый экономичный правильный: ${METHOD_META[cheapest.method].label}.`;
  }

  $("verdictBox").textContent = verdict;

  const maxTokens = Math.max(1, ...rows.map((r) => r.tokens));
  $("barComparison").innerHTML = rows
    .map((row) => {
      const mark = row.correct === true ? "✓" : row.correct === false ? "✕" : "—";
      return `
        <div class="bar-row" style="--method-color:${METHOD_META[row.method].color}">
          <strong>${METHOD_META[row.method].label}</strong>
          <div class="bar-track"><span class="bar-fill" style="width:${(row.tokens / maxTokens) * 100}%"></span></div>
          <span class="cost-value">${compactNumber(row.tokens)} tok</span>
          <span class="correct-mark ${row.correct === true ? "ok" : row.correct === false ? "wrong" : ""}">${mark}</span>
        </div>
      `;
    })
    .join("");
}

function renderRaw() {
  $("rawJson").textContent = JSON.stringify(state.raw || {}, null, 2);
}

function renderAll() {
  renderTask();
  renderMethodCards();
  renderGlobalStatus();
  renderScore();
  renderProgress();
  renderResults();
  renderRaw();
}

function applyResult(result) {
  state.runs.push(result);
  const item = state.methodStates[result.method];
  if (!item) return;
  if (result.correct) item.status = "correct";
  else if (result.status === "ok") item.status = "wrong";
  else item.status = result.status;
  item.answer = result.answer_norm || "-";
  item.correct = result.correct;
  item.calls = result.calls || 0;
  item.tokens = (result.prompt_tokens || 0) + (result.output_tokens || 0);
  item.latency = result.latency_s || 0;
  item.answerRaw = result.answer_raw || "";
  item.prompts = result.prompts || [];
  item.stages = (result.stages || []).map((stage) => ({
    name: stage.name,
    status: stage.status,
    tokens: (stage.prompt_tokens || 0) + (stage.output_tokens || 0),
    latency: stage.latency_s || 0,
  }));

  if (result.status === "ok" && !result.correct) state.failures.wrong += 1;
  else if (result.status !== "ok") {
    const key = state.failures[result.status] == null ? "error" : result.status;
    state.failures[key] += 1;
  }
}

function stageUpdate(method, stage) {
  const item = state.methodStates[method];
  if (!item) return;
  const found = item.stages.find((s) => s.name === stage.name);
  if (found) {
    found.status = stage.status;
    found.tokens = (stage.prompt_tokens || 0) + (stage.output_tokens || 0);
    found.latency = stage.latency_s || 0;
  }
}

function handleEvent(event) {
  const { type, data } = event;
  let shouldRender = true;
  if (type === "ExperimentStarted") {
    state.callsEstimate = data.total_calls_estimate || 5;
    state.startedAt = Date.now();
    state.runs = [];
    state.cancelSummary = null;
    resetMethodStates();
    resetFailures();
    setStatus("running", "RUNNING");
  } else if (type === "TaskStarted") {
    state.currentTask = data;
    state.activeTaskId = data.task_id;
    resetMethodStates();
  } else if (type === "MethodStarted") {
    state.activeMethod = data.method;
    state.activeStage = null;
    state.stageStartedAt = null;
    state.methodStates[data.method].status = "running";
  } else if (type === "StageStarted") {
    state.activeMethod = data.method;
    state.activeStage = data.stage;
    state.stageStartedAt = performance.now();
    const item = state.methodStates[data.method];
    item.status = "running";
    // Показываем отправленный промпт сразу, не дожидаясь ответа.
    if (data.prompt && !item.prompts.includes(data.prompt)) {
      item.prompts.push(data.prompt);
    }
    const stage = item.stages.find((s) => s.name === data.stage);
    if (stage) stage.status = "running";
  } else if (type === "RequestStateChanged") {
    const item = state.methodStates[data.method];
    if (item) item.requestStates[data.stage] = data.state;
    updateLiveIndicator(data.method);
    shouldRender = false;
  } else if (type === "RequestRetrying") {
    const item = state.methodStates[data.method];
    if (item) {
      item.requestStates[data.stage] = `retry_${data.attempt}`;
      item.outputs[data.stage] = [
        item.outputs[data.stage] || "",
        `\n[retry ${data.attempt}: ${data.reason}; next attempt in ${data.wait_s}s]\n`,
      ].join("");
    }
    updateLiveIndicator(data.method);
    updateStreamingResponse(data.method);
    shouldRender = false;
  } else if (type === "StageOutputDelta") {
    const item = state.methodStates[data.method];
    if (item) {
      item.outputs[data.stage] = (item.outputs[data.stage] || "") + (data.text || "");
    }
    updateStreamingResponse(data.method);
    shouldRender = false;
  } else if (type === "StageFinished") {
    stageUpdate(data.method, data.stage);
    state.activeStage = null;
    state.stageStartedAt = null;
  } else if (type === "MethodFinished") {
    applyResult(data.result);
    state.activeMethod = null;
    state.activeStage = null;
    state.stageStartedAt = null;
  } else if (type === "ExperimentFinished") {
    setStatus("complete", "RESULTS");
    state.running = false;
    state.activeMethod = null;
    state.activeStage = null;
    state.stageStartedAt = null;
    setButtons(false);
  } else if (type === "ExperimentCancelled") {
    setStatus("waiting", "STOPPED");
    state.running = false;
    markRunningMethodsCancelled();
    state.activeMethod = null;
    state.activeStage = null;
    state.stageStartedAt = null;
    setButtons(false);
    const done = METHODS.filter((m) => methodRuns(m).length > 0);
    const pending = METHODS.filter((m) => methodRuns(m).length === 0);
    state.cancelSummary =
      `Запуск остановлен. Выполнено методов: ${data.completed_methods ?? done.length}. ` +
      `Готово: ${done.map((m) => METHOD_META[m].label).join(", ") || "—"}. ` +
      `Не выполнено: ${pending.map((m) => METHOD_META[m].label).join(", ") || "—"}.`;
  } else if (type === "RunSaved") {
    state.raw = data.document;
    state.document = data.document;
    loadHistory();
  } else if (type === "RunError") {
    setStatus("error", "ERROR");
    state.running = false;
    state.activeMethod = null;
    state.activeStage = null;
    state.stageStartedAt = null;
    setButtons(false);
    state.raw = { error: data.message };
  }
  if (shouldRender) renderAll();
}

function loadDocument(doc) {
  state.document = doc;
  state.raw = doc;
  state.runs = [];
  state.callsEstimate = estimateCalls(doc);
  resetMethodStates();
  resetFailures();

  const taskById = Object.fromEntries(state.tasks.map((task) => [task.id, task]));
  for (const result of doc.runs || []) {
    const task = taskById[result.task_id];
    if (task) state.currentTask = task;
    applyResult(result);
  }
  setStatus(doc.error ? "error" : "complete", doc.error ? "ERROR" : "RESULTS");
  renderAll();
}

function estimateCalls(doc) {
  const cost = { direct: 1, cot: 1, self_prompt: 2, panel: 1 };
  const methods = doc.methods || METHODS;
  return (doc.repeats || 1) * methods.reduce((sum, m) => sum + (cost[m] || 1), 0);
}

async function startRun() {
  const task = getSelectedTask();
  if (!task) {
    state.raw = { error: "No task selected" };
    setStatus("error", "ERROR");
    renderAll();
    return;
  }
  resetLiveRunView();
  state.selectedTaskId = task.id;
  state.currentTask = task;
  setButtons(true);
  setStatus("running", "STARTING");
  const payload = {
    task_id: task.id,
    thinking: $("thinkingInput").value,
    model: $("modelInput").value || null,
  };
  const response = await fetch("/api/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = await response.json();
  if (!response.ok) {
    state.raw = body;
    setStatus("error", "ERROR");
    setButtons(false);
    renderAll();
    return;
  }
  state.runId = body.run_id;
  state.activeTaskId = body.task?.id || task.id;
  state.currentTask = body.task || task;
  state.callsEstimate = body.calls_estimate;
  state.running = true;
  state.startedAt = Date.now();
  state.lastHeartbeatAt = performance.now();
  setButtons(true);
  setStatus("running", "RUNNING");
  const source = new EventSource(`/api/runs/${body.run_id}/events`);
  state.eventSource = source;
  source.onmessage = (message) => {
    const event = JSON.parse(message.data);
    if (event.type === "StreamClosed") {
      source.close();
      if (state.eventSource === source) state.eventSource = null;
    } else if (event.type === "Heartbeat") {
      state.lastHeartbeatAt = performance.now();
    } else {
      handleEvent(event);
    }
  };
  source.onerror = () => {
    if (!state.running) return;
    $("globalElapsed").textContent = "Backend connection unstable";
  };
}

async function stopRun() {
  if (!state.runId) return;
  const runId = state.runId;
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
  state.running = false;
  markRunningMethodsCancelled();
  state.activeMethod = null;
  state.activeStage = null;
  state.stageStartedAt = null;
  state.cancelSummary = null;
  setStatus("waiting", "STOPPED");
  setButtons(false);
  const done = METHODS.filter((m) => methodRuns(m).length > 0);
  const pending = METHODS.filter((m) => methodRuns(m).length === 0);
  state.cancelSummary =
    `Запуск остановлен. Выполнено: ${done.map((m) => METHOD_META[m].label).join(", ") || "—"}. ` +
    `Не выполнено: ${pending.map((m) => METHOD_META[m].label).join(", ") || "—"}.`;
  renderAll();
  await fetch(`/api/runs/${runId}/cancel`, { method: "POST" }).catch(() => {});
}

async function loadHistory() {
  const list = await fetch("/api/results").then((r) => r.json()).catch(() => []);
  $("historyList").innerHTML = list.length
    ? list
        .map(
          (item) => `
            <div class="history-item">
              <div>
                <strong>${escapeHtml(item.name)}</strong>
                <div class="history-meta">
                  ${escapeHtml(item.model || "-")} · thinking ${escapeHtml(item.thinking || "-")} ·
                  runs ${item.runs}
                </div>
              </div>
              <button type="button" data-result-id="${escapeHtml(item.id)}">Open</button>
            </div>
          `,
        )
        .join("")
    : `<p class="history-meta">Сохранённых Day 3 JSON пока нет.</p>`;

  $("historyList").querySelectorAll("[data-result-id]").forEach((button) => {
    button.addEventListener("click", async () => {
      const id = button.getAttribute("data-result-id");
      const doc = await fetch(`/api/result?id=${encodeURIComponent(id)}`).then((r) => r.json());
      loadDocument(doc);
      activateTab("live");
    });
  });
}

async function loadModels() {
  const models = await fetch("/api/models").then((r) => r.json()).catch(() => []);
  const select = $("modelInput");
  select.innerHTML = `<option value="">Gemini fallback chain</option>`;
  for (const item of models) {
    const option = document.createElement("option");
    option.value = item.availableForDay3 ? (item.id || item.model) : "";
    option.disabled = !item.availableForDay3;
    option.textContent = item.availableForDay3
      ? `${item.provider} · ${item.model}`
      : `${item.provider} · ${item.model} (planned)`;
    select.appendChild(option);
  }
}

async function loadTasks() {
  const tasks = await fetch("/api/tasks").then((r) => r.json()).catch(() => []);
  state.tasks = tasks;
  const select = $("taskInput");
  const familyLabel = { logic: "Логическая", counting: "Алгоритмическая", analytic: "Аналитическая" };
  select.innerHTML = tasks
    .map(
      (task) =>
        `<option value="${escapeHtml(task.id)}">${familyLabel[task.family] || task.family} · ${escapeHtml(task.id)}</option>`,
    )
    .join("");
  if (tasks.length) {
    state.selectedTaskId = select.value || tasks[0].id;
    state.currentTask = tasks[0];
    renderTask();
  }
}

function activateTab(tabName) {
  document.querySelectorAll(".tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === tabName);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("active", panel.id === tabName);
  });
}

function demoDocument() {
  const task = state.tasks[0] || {
    id: "logic-01",
    family: "logic",
    prompt: "Пять человек стоят в очереди…",
    baseline: 0.2,
  };
  return {
    day: 3,
    model_used: "gemini-3.5-flash-lite",
    thinking_level: "low",
    repeats: 1,
    methods: METHODS,
    tasks: [task],
    failures: { wrong: 1, unparseable: 0, truncated: 0, blocked: 0, contaminated: 0, error: 0 },
    runs: [
      makeRun("direct", task.id, true, "вера", 1, 186, ["solve"]),
      makeRun("cot", task.id, true, "вера", 1, 742, ["reasoning"]),
      makeRun("self_prompt", task.id, false, "дина", 2, 1490, ["generate_prompt", "leak_check", "solve"]),
      makeRun("panel", task.id, true, "вера", 1, 1200, ["experts"]),
    ],
  };
}

function makeRun(method, taskId, correct, answer, calls, tokens, stages, status = "ok") {
  const perStage = Math.max(1, Math.round(tokens / stages.length));
  return {
    method,
    task_id: taskId,
    repeat: 0,
    status,
    answer_raw: `Рассуждение для ${method}.\nANSWER: ${answer || "-"}`,
    answer_norm: answer,
    correct,
    calls,
    prompt_tokens: Math.round(tokens * 0.62),
    output_tokens: Math.round(tokens * 0.38),
    latency_s: Math.round((0.9 + calls * 1.25) * 10) / 10,
    model: "gemini-3.5-flash-lite",
    prompts: [method === "self_prompt" ? "Составь промпт…" : "Задача + контракт ответа."],
    stages: stages.map((name, index) => ({
      name,
      status: "ok",
      finish_reason: "STOP",
      prompt_tokens: Math.round(perStage * 0.6),
      output_tokens: Math.round(perStage * 0.4),
      latency_s: 0.8 + index * 0.4,
    })),
  };
}

function bootElapsedTimer() {
  clearInterval(state.elapsedTimer);
  state.elapsedTimer = setInterval(() => {
    // Общий таймер запуска: тикает, только пока идёт прогон.
    if (state.running && state.startedAt) {
      const elapsed = Math.floor((Date.now() - state.startedAt) / 1000);
      const mm = String(Math.floor(elapsed / 60)).padStart(2, "0");
      const ss = String(elapsed % 60).padStart(2, "0");
      $("elapsedText").textContent = `${mm}:${ss} elapsed`;
    }

    // Таймер активного API-вызова.
    if (state.running && state.stageStartedAt != null) {
      const sec = (performance.now() - state.stageStartedAt) / 1000;
      const methodState = state.activeMethod ? state.methodStates[state.activeMethod] : null;
      const requestState = methodState && state.activeStage
        ? methodState.requestStates[state.activeStage]
        : null;
      const stateLabel = REQUEST_LABELS[requestState] || (sec >= 15 ? "REQUEST ACTIVE" : "WAITING");
      const label = `${stateLabel} · ${sec.toFixed(1)}s`;
      const el = document.querySelector(".method-card.active .stage-elapsed");
      if (el) el.textContent = label;
      const heartbeatAge = state.lastHeartbeatAt == null
        ? null
        : (performance.now() - state.lastHeartbeatAt) / 1000;
      const backend = heartbeatAge == null || heartbeatAge <= 6
        ? "Backend alive"
        : "Backend connection unstable";
      $("globalElapsed").textContent = `${sec.toFixed(1)}s · ${backend}`;
    } else if (!state.running) {
      $("globalElapsed").textContent = "";
    }
  }, 100);
}

async function init() {
  resetMethodStates();
  resetFailures();
  renderAll();
  bootElapsedTimer();
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => activateTab(button.dataset.tab));
  });
  $("taskInput").addEventListener("change", () => {
    if (state.running) return;
    state.selectedTaskId = $("taskInput").value;
    const task = getSelectedTask();
    if (task) {
      resetLiveRunView();
      state.selectedTaskId = task.id;
      state.currentTask = task;
      renderAll();
    }
  });
  $("runButton").addEventListener("click", startRun);
  $("stopButton").addEventListener("click", stopRun);
  $("demoButton")?.addEventListener("click", () => loadDocument(demoDocument()));
  $("refreshHistory").addEventListener("click", loadHistory);
  $("copyRaw").addEventListener("click", () => navigator.clipboard?.writeText(JSON.stringify(state.raw || {}, null, 2)));
  $("fileInput").addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    loadDocument(JSON.parse(await file.text()));
    activateTab("live");
  });

  await loadTasks();
  await loadModels();
  await loadHistory();
  renderAll();
}

init();
