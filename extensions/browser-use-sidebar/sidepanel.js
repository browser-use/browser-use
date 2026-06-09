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
};

let currentContext = null;
let currentAutofillMatches = [];
let observeTimer = null;
let debounceTimer = null;

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
  const observedAt = currentContext.observedAt ? ` | observed ${new Date(currentContext.observedAt).toLocaleTimeString()}` : "";
  els.pageTitle.textContent = `${title}${observedAt}`;
  els.pageUrl.textContent = url;
}

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

function scheduleObserve() {
  if (!els.autoObserve.checked) return;
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => {
    readPageContext({ quiet: true }).catch(() => renderContext());
  }, 600);
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
          ...selectors.flatMap((selector) => {
            try {
              return Array.from(document.querySelectorAll(selector));
            } catch {
              return [];
            }
          }),
          ...inputs.filter((input) => {
            const attrs = [
              input.name,
              input.id,
              input.autocomplete,
              input.placeholder,
              input.getAttribute("aria-label"),
              input.getAttribute("data-testid"),
              input.type,
            ]
              .map(normalize)
              .filter(Boolean);
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

      const filled = [];
      const failed = [];
      for (const field of profile.fields || []) {
        const target = candidatesFor(field).find((element) => !element.disabled && !element.readOnly);
        if (!target) {
          failed.push(field.name);
          continue;
        }
        setValue(target, field.value);
        filled.push(field.name);
      }
      return { filled, failed };
    },
  });

  return result;
}

function startAutoObserve() {
  stopAutoObserve();
  if (!els.autoObserve.checked) {
    els.status.textContent = "Auto observe paused.";
    return;
  }
  scheduleObserve();
  observeTimer = setInterval(scheduleObserve, OBSERVE_INTERVAL_MS);
}

function stopAutoObserve() {
  clearInterval(observeTimer);
  clearTimeout(debounceTimer);
  observeTimer = null;
  debounceTimer = null;
}

function inferLocale(task, context) {
  const combined = `${task || ""} ${context?.title || ""} ${context?.text || ""}`;
  return /[\u3400-\u9fff]/.test(combined) ? "zh-CN" : "en-US";
}

async function checkBridge() {
  try {
    const response = await fetch(`${BRIDGE_URL}/health`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const data = await response.json();
    els.status.textContent = `Bridge ready (${data.model || "configured model"}). Observing current tab.`;
  } catch (error) {
    els.status.textContent = "Bridge offline. Run: browser-use sidepanel-server --model gpt-5.4";
  }
}

async function runTask() {
  const task = els.task.value.trim();
  if (!task) return;

  els.run.disabled = true;
  els.output.classList.remove("error");
  els.output.textContent = "Running... The assistant may need a few minutes for model calls and browser navigation.";
  const controller = new AbortController();
  const startedAt = Date.now();
  const timeoutId = setTimeout(() => controller.abort(), RUN_TIMEOUT_MS);
  const progressId = setInterval(() => {
    const seconds = Math.round((Date.now() - startedAt) / 1000);
    els.output.textContent = `Running... ${seconds}s elapsed.\nThe assistant is still waiting for model/browser results.`;
  }, 15000);

  try {
    const context = els.includePage.checked ? (currentContext || (await readPageContext())) : null;
    const response = await fetch(`${BRIDGE_URL}/assistant`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
      body: JSON.stringify({
        task,
        page_context: context,
        locale: inferLocale(task, context),
        max_steps: 8,
        llm_timeout: 60,
      }),
    });
    const data = await response.json();
    if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
    els.output.textContent = data.result || JSON.stringify(data, null, 2);
  } catch (error) {
    els.output.classList.add("error");
    els.output.textContent =
      error.name === "AbortError"
        ? "Request timed out after 5 minutes. Try a narrower task, disable Include current page, or restart the local bridge."
        : String(error.message || error);
  } finally {
    clearTimeout(timeoutId);
    clearInterval(progressId);
    els.run.disabled = false;
  }
}

els.refresh.addEventListener("click", async () => {
  try {
    await readPageContext();
  } catch (error) {
    els.output.classList.add("error");
    els.output.textContent = String(error.message || error);
  }
});

els.autoObserve.addEventListener("change", startAutoObserve);
els.autofill.addEventListener("click", async () => {
  els.autofill.disabled = true;
  els.output.classList.remove("error");
  els.output.textContent = "Autofilling current page...";
  try {
    const result = await autofillCurrentPage();
    els.output.textContent = `Autofill finished.\nFilled: ${(result.filled || []).join(", ") || "none"}\nNot found: ${(result.failed || []).join(", ") || "none"}`;
  } catch (error) {
    els.output.classList.add("error");
    els.output.textContent = String(error.message || error);
  } finally {
    els.autofill.disabled = currentAutofillMatches.length === 0;
  }
});
els.run.addEventListener("click", runTask);

chrome.tabs.onActivated.addListener(scheduleObserve);
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "complete" || changeInfo.url) scheduleObserve();
});

checkBridge();
startAutoObserve();
