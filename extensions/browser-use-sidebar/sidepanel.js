const BRIDGE_URL = "http://127.0.0.1:8765";
const OBSERVE_INTERVAL_MS = 8000;
const RUN_TIMEOUT_MS = 300000;

const els = {
  status: document.getElementById("status"),
  refresh: document.getElementById("refresh"),
  pageTitle: document.getElementById("pageTitle"),
  pageUrl: document.getElementById("pageUrl"),
  task: document.getElementById("task"),
  includePage: document.getElementById("includePage"),
  autoObserve: document.getElementById("autoObserve"),
  autofillStatus: document.getElementById("autofillStatus"),
  autofill: document.getElementById("autofill"),
  run: document.getElementById("run"),
  output: document.getElementById("output"),
  thinkingSection: document.getElementById("thinkingSection"),
  thinkingTimeline: document.getElementById("thinkingTimeline"),
  stepCounter: document.getElementById("stepCounter"),
  resultTime: document.getElementById("resultTime"),
};

let currentContext = null;
let currentAutofillMatches = [];
let observeTimer = null;
let debounceTimer = null;

// --- Thinking Process Manager ---
const thinking = {
  steps: [],
  clear() {
    this.steps = [];
    els.thinkingTimeline.innerHTML = "";
    els.stepCounter.textContent = "Step 0";
    els.thinkingSection.style.display = "none";
  },
  show() {
    els.thinkingSection.style.display = "";
  },
  addStep(step) {
    this.steps.push(step);
    els.stepCounter.textContent = `Step ${this.steps.length}`;
    const el = document.createElement("div");
    el.className = "step-item";

    const dotClass = step.status === "error" ? "error" : step.status === "running" ? "running" : "success";
    el.innerHTML = `
      <div class="step-dot ${dotClass}"></div>
      <div class="step-content">
        <div class="step-action">${this._escapeHtml(step.action || "thinking...")}</div>
        ${step.detail ? `<div class="step-detail">${this._escapeHtml(step.detail)}</div>` : ""}
        ${step.thinking ? `<div class="step-thinking">💭 ${this._escapeHtml(step.thinking)}</div>` : ""}
      </div>
    `;
    els.thinkingTimeline.appendChild(el);
    els.thinkingTimeline.scrollTop = els.thinkingTimeline.scrollHeight;
  },
  updateLastStep(updates) {
    if (!this.steps.length) return;
    const last = this.steps[this.steps.length - 1];
    Object.assign(last, updates);
    const lastEl = els.thinkingTimeline.lastElementChild;
    if (lastEl) {
      const dot = lastEl.querySelector(".step-dot");
      if (dot && updates.status) {
        dot.className = `step-dot ${updates.status}`;
      }
    }
  },
  _escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  },
};

// --- Page Context ---

async function activeTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  return tabs[0] || null;
}

function canInspectTab(tab) {
  const url = tab?.url || "";
  return Boolean(tab?.id && /^https?:\/\//i.test(url));
}

async function readPageContext({ quiet = false } = {}) {
  const tab = await activeTab();
  if (!canInspectTab(tab)) {
    currentContext = tab
      ? {
          tabId: tab.id,
          browserTitle: tab.title || "",
          browserUrl: tab.url || "",
          title: tab.title || "Unsupported page",
          url: tab.url || "",
          text: "",
          links: [],
        }
      : null;
    renderContext();
    if (!quiet) throw new Error("Only http/https pages can be inspected.");
    return currentContext;
  }

  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func: () => {
      const text = document.body ? document.body.innerText : "";
      const links = Array.from(document.querySelectorAll("a[href]"))
        .slice(0, 120)
        .map((anchor) => ({
          text: anchor.innerText.trim().slice(0, 120),
          href: anchor.href,
        }))
        .filter((item) => item.text || item.href);
      return {
        title: document.title,
        url: location.href,
        text: text.replace(/\s+/g, " ").trim().slice(0, 16000),
        links,
        observedAt: new Date().toISOString(),
      };
    },
  });

  currentContext = {
    tabId: tab.id,
    browserTitle: tab.title || "",
    browserUrl: tab.url || "",
    ...result,
  };
  renderContext();
  previewAutofill(currentContext).catch(() => renderAutofill([]));
  return currentContext;
}

function renderContext() {
  if (!currentContext) {
    els.pageTitle.textContent = "No page attached";
    els.pageUrl.textContent = "";
    return;
  }
  const title = currentContext.title || currentContext.browserTitle || "Untitled";
  const url = currentContext.url || currentContext.browserUrl || "";
  els.pageTitle.textContent = title;
  els.pageUrl.textContent = url;
}

// --- Autofill ---

function renderAutofill(matches) {
  currentAutofillMatches = Array.isArray(matches) ? matches : [];
  if (!currentAutofillMatches.length) {
    els.autofillStatus.textContent = "No matching local profile.";
    els.autofill.disabled = true;
    return;
  }
  const profile = currentAutofillMatches[0];
  const maskedCount = (profile.fields || []).filter((field) => field.masked).length;
  els.autofillStatus.textContent = `${profile.label} | ${profile.field_count} fields${maskedCount ? `, ${maskedCount} sensitive` : ""}`;
  els.autofill.disabled = false;
}

async function previewAutofill(context) {
  const url = context?.url || context?.browserUrl || "";
  if (!/^https?:\/\//i.test(url)) {
    renderAutofill([]);
    return;
  }
  const response = await fetch(`${BRIDGE_URL}/autofill/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
  renderAutofill(data.matches || []);
}

async function autofillCurrentPage() {
  const tab = await activeTab();
  if (!canInspectTab(tab)) throw new Error("Only http/https pages can be autofilled.");

  const context = currentContext || (await readPageContext());
  const profileId = currentAutofillMatches[0]?.id || null;
  const response = await fetch(`${BRIDGE_URL}/autofill/resolve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url: context.url || context.browserUrl, profile_id: profileId }),
  });
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);

  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    args: [data.profile],
    func: (profile) => {
      function normalize(value) {
        return String(value || "").toLowerCase().replace(/[\s_\-:.]/g, "");
      }
      function candidatesFor(field) {
        const selectors = Array.isArray(field.selectors) ? field.selectors : [];
        const aliases = [field.name, ...(Array.isArray(field.aliases) ? field.aliases : [])].map(normalize);
        const inputs = Array.from(document.querySelectorAll("input, textarea, select"));
        const typed = normalize(field.field_type);
        return [
          ...selectors.flatMap((s) => { try { return Array.from(document.querySelectorAll(s)); } catch { return []; } }),
          ...inputs.filter((input) => {
            const attrs = [input.name, input.id, input.autocomplete, input.placeholder, input.getAttribute("aria-label"), input.type].map(normalize).filter(Boolean);
            if (typed === "password" && input.type === "password") return true;
            return aliases.some((alias) => attrs.some((attr) => attr.includes(alias) || alias.includes(attr)));
          }),
        ];
      }
      function setValue(element, value) {
        element.focus();
        element.value = value;
        element.dispatchEvent(new Event("input", { bubbles: true }));
        element.dispatchEvent(new Event("change", { bubbles: true }));
      }
      const filled = [], failed = [];
      for (const field of profile.fields || []) {
        const target = candidatesFor(field).find((el) => !el.disabled && !el.readOnly);
        if (!target) { failed.push(field.name); continue; }
        setValue(target, field.value);
        filled.push(field.name);
      }
      return { filled, failed };
    },
  });
  return result;
}

// --- Auto Observe ---

function scheduleObserve() {
  if (!els.autoObserve.checked) return;
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    readPageContext({ quiet: true }).catch(() => renderContext());
  }, 600);
}

function startAutoObserve() {
  stopAutoObserve();
  if (!els.autoObserve.checked) return;
  scheduleObserve();
  observeTimer = setInterval(scheduleObserve, OBSERVE_INTERVAL_MS);
}

function stopAutoObserve() {
  clearInterval(observeTimer);
  clearTimeout(debounceTimer);
  observeTimer = null;
  debounceTimer = null;
}

// --- Utilities ---

function inferLocale(task, context) {
  const combined = `${task || ""} ${context?.title || ""} ${context?.text || ""}`;
  return /[㐀-鿿]/.test(combined) ? "zh-CN" : "en-US";
}

function formatDuration(ms) {
  if (ms < 1000) return `${ms}ms`;
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

// --- Bridge Check ---

async function checkBridge() {
  try {
    const response = await fetch(`${BRIDGE_URL}/health`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    const features = [];
    if (data.use_vision) features.push("👁️ vision");
    if (data.accounts_loaded) features.push("🔑 accounts");
    const extras = features.length ? ` · ${features.join(" · ")}` : "";
    els.status.textContent = `✅ ${data.model || "ready"}${extras}`;
  } catch (error) {
    els.status.textContent = "❌ Bridge offline — run: uv run python -m browser_use.skill_cli.sidepanel_server";
  }
}

// --- Run Task (with thinking process) ---

async function runTask() {
  const task = els.task.value.trim();
  if (!task) return;

  els.run.disabled = true;
  els.output.className = "output-content";
  els.output.textContent = "";
  els.resultTime.textContent = "";

  // Show thinking panel
  thinking.clear();
  thinking.show();
  thinking.addStep({ action: "Sending task to agent...", status: "running" });

  const controller = new AbortController();
  const startedAt = Date.now();
  const timeoutId = setTimeout(() => controller.abort(), RUN_TIMEOUT_MS);

  // Progress ticker
  let progressStep = 0;
  const progressId = setInterval(() => {
    progressStep++;
    const elapsed = formatDuration(Date.now() - startedAt);
    thinking.updateLastStep({ detail: `waiting for response... (${elapsed})` });
  }, 5000);

  try {
    const context = els.includePage.checked ? (currentContext || (await readPageContext())) : null;

    thinking.updateLastStep({ status: "success", action: "Task submitted", detail: task.slice(0, 80) });
    thinking.addStep({ action: "Agent is browsing...", status: "running", thinking: "Analyzing task and planning steps" });

    const response = await fetch(`${BRIDGE_URL}/assistant`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
      body: JSON.stringify({
        task,
        page_context: context,
        locale: inferLocale(task, context),
        max_steps: 12,
        llm_timeout: 90,
        use_vision: true,
      }),
    });

    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);

    // Parse thinking steps from response
    thinking.updateLastStep({ status: "success", action: "Agent completed" });

    if (data.stage_results && data.stage_results.length > 0) {
      for (const stage of data.stage_results) {
        const source = stage.source || stage.source_type || "unknown";
        const candidateCount = (stage.candidates || []).length;
        thinking.addStep({
          action: `📊 Gathered from ${source}`,
          detail: `${candidateCount} candidate(s) found`,
          status: "success",
        });
      }
    }

    if (data.task_plan) {
      const plan = data.task_plan;
      if (plan.mode) {
        thinking.addStep({
          action: `🎯 Mode: ${plan.mode}`,
          detail: plan.topic || "",
          thinking: plan.budget ? `Budget: ${plan.budget}` : null,
          status: "success",
        });
      }
    }

    // Show result
    const elapsed = formatDuration(Date.now() - startedAt);
    els.resultTime.textContent = elapsed;
    els.output.className = "output-content success";
    els.output.textContent = data.result || JSON.stringify(data, null, 2);

  } catch (error) {
    const elapsed = formatDuration(Date.now() - startedAt);
    els.resultTime.textContent = elapsed;
    thinking.updateLastStep({ status: "error", action: "Failed" });
    thinking.addStep({
      action: "❌ Error",
      detail: error.name === "AbortError" ? "Timed out after 5 minutes" : error.message,
      status: "error",
    });
    els.output.className = "output-content error";
    els.output.textContent =
      error.name === "AbortError"
        ? "Request timed out. Try a narrower task or restart the bridge."
        : String(error.message || error);
  } finally {
    clearTimeout(timeoutId);
    clearInterval(progressId);
    els.run.disabled = false;
  }
}

// --- Event Listeners ---

els.refresh.addEventListener("click", async () => {
  try {
    await readPageContext();
  } catch (error) {
    els.output.className = "output-content error";
    els.output.textContent = String(error.message || error);
  }
});

els.autoObserve.addEventListener("change", startAutoObserve);

els.autofill.addEventListener("click", async () => {
  els.autofill.disabled = true;
  els.output.className = "output-content";
  els.output.textContent = "Autofilling...";
  try {
    const result = await autofillCurrentPage();
    els.output.textContent = `✅ Autofill done\nFilled: ${(result.filled || []).join(", ") || "none"}\nNot found: ${(result.failed || []).join(", ") || "none"}`;
  } catch (error) {
    els.output.className = "output-content error";
    els.output.textContent = String(error.message || error);
  } finally {
    els.autofill.disabled = currentAutofillMatches.length === 0;
  }
});

els.run.addEventListener("click", runTask);

// Keyboard shortcut: Ctrl+Enter to run
els.task.addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
    e.preventDefault();
    runTask();
  }
});

chrome.tabs.onActivated.addListener(scheduleObserve);
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "complete" || changeInfo.url) scheduleObserve();
});

// --- Init ---
checkBridge();
startAutoObserve();
