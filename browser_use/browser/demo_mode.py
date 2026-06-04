"""Demo mode helper for injecting and updating the in-browser log panel."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from browser_use.browser.session import BrowserSession

# Embedded JavaScript for demo panel (injected into browser pages)
_DEMO_PANEL_SCRIPT = r"""(function () {
  // SESSION_ID_PLACEHOLDER will be replaced by DemoMode with actual session ID
  const SESSION_ID = '__BROWSER_USE_SESSION_ID_PLACEHOLDER__';
  const EXCLUDE_ATTR = 'data-browser-use-exclude-' + SESSION_ID;
  const PANEL_ID = 'browser-use-demo-panel';
  const STYLE_ID = 'browser-use-demo-panel-style';
  const STORAGE_KEY = '__browserUseDemoLogs__';
  const STORAGE_HTML_KEY = '__browserUseDemoLogsHTML__';
  const PANEL_STATE_KEY = '__browserUseDemoPanelState__';
  const TOGGLE_BUTTON_ID = 'browser-use-demo-toggle';
  const MAX_MESSAGES = 100;
  const EXPANDED_IDS_KEY = '__browserUseExpandedEntries__';
  const LEVEL_ICONS = {
    info: 'ℹ️',
    action: '▶️',
    thought: '💭',
    success: '✅',
    warning: '⚠️',
    error: '❌',
  };
  const LEVEL_LABELS = {
    info: 'info',
    action: 'action',
    thought: 'thought',
    success: 'success',
    warning: 'warning',
    error: 'error',
  };

  if (window.__browserUseDemoPanelLoaded) {
    const existingPanel = document.getElementById(PANEL_ID);
    if (!existingPanel) {
      initializePanel();
    }
    return;
  }
  window.__browserUseDemoPanelLoaded = true;

  const state = {
    panel: null,
    list: null,
    messages: [],
    isOpen: true,
    toggleButton: null,
  };
  state.messages = restoreMessages();

  function initializePanel() {
    console.log('Browser-use demo panel initialized with session ID:', SESSION_ID);
    addStyles();
    state.isOpen = loadPanelState();
    state.panel = buildPanel();
    state.list = state.panel.querySelector('[data-role="log-list"]');
    appendToHost(state.panel);
    state.toggleButton = buildToggleButton();
    appendToHost(state.toggleButton);
    const savedWidth = loadPanelWidth();
    if (savedWidth) {
      document.documentElement.style.setProperty('--browser-use-demo-panel-width', `${savedWidth}px`);
    }

    if (!hydrateFromStoredMarkup()) {
      state.messages.forEach((entry) => appendEntry(entry, false));
    }
    attachCloseHandler();
    if (state.isOpen) {
      openPanel(false);
    } else {
      closePanel(false);
    }
    adjustLayout();
    window.addEventListener('resize', debounce(adjustLayout, 150));
  }

  function appendToHost(node) {
    if (!node) {
      return;
    }

    const host = document.body || document.documentElement;
    if (!host.contains(node)) {
      host.appendChild(node);
    }

    if (!document.body) {
      document.addEventListener(
        'DOMContentLoaded',
        () => {
          if (document.body && node.parentNode !== document.body) {
            document.body.appendChild(node);
          }
        },
        { once: true }
      );
    }
  }

  function addStyles() {
    if (document.getElementById(STYLE_ID)) {
      return;
    }
    const style = document.createElement('style');
    style.id = STYLE_ID;
    style.setAttribute(EXCLUDE_ATTR, 'true');
    style.textContent = `
      #${PANEL_ID} {
        position: fixed;
        top: 0;
        right: 0;
        width: var(--browser-use-demo-panel-width, 340px);
        max-width: calc(100vw - 64px);
        height: 100vh;
        display: flex;
        flex-direction: column;
        background: #05070d;
        color: #f8f9ff;
        font-family: 'JetBrains Mono', 'Fira Code', 'Monaco', 'Menlo', monospace;
        font-size: 13px;
        line-height: 1.4;
        box-shadow: -6px 0 25px rgba(0, 0, 0, 0.35);
        z-index: 2147480000;
        border-left: 1px solid rgba(255, 255, 255, 0.14);
        backdrop-filter: blur(10px);
        pointer-events: auto;
        transform: translateX(0);
        opacity: 1;
        transition: transform 0.25s ease, opacity 0.25s ease;
      }

      #${PANEL_ID}[data-open="false"] {
        transform: translateX(110%);
        opacity: 0;
        pointer-events: none;
      }

      #${PANEL_ID} .browser-use-demo-header {
        padding: 16px 18px 12px;
        border-bottom: 1px solid rgba(255, 255, 255, 0.14);
        display: flex;
        align-items: baseline;
        justify-content: space-between;
        gap: 8px;
        flex-wrap: wrap;
      }

      #${PANEL_ID} .browser-use-demo-header h1 {
        font-size: 15px;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        margin: 0;
        color: #f8f9ff;
      }

      #${PANEL_ID} .browser-use-badge {
        font-size: 11px;
        padding: 2px 10px;
        border-radius: 999px;
        border: 1px solid rgba(255, 255, 255, 0.4);
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: #f8f9ff;
      }

      #${PANEL_ID} .browser-use-logo img {
        height: 36px;
      }

      #${PANEL_ID} .browser-use-header-actions {
        margin-left: auto;
        display: flex;
        align-items: center;
        gap: 8px;
      }

      #${PANEL_ID} .browser-use-close-btn {
        width: 28px;
        height: 28px;
        border-radius: 50%;
        border: 1px solid rgba(255, 255, 255, 0.2);
        background: rgba(255, 255, 255, 0.05);
        color: #f8f9ff;
        cursor: pointer;
        font-size: 16px;
        line-height: 1;
        display: flex;
        align-items: center;
        justify-content: center;
        transition: background 0.2s ease, border 0.2s ease;
      }

      #${PANEL_ID} .browser-use-close-btn:hover {
        background: rgba(255, 255, 255, 0.15);
        border-color: rgba(255, 255, 255, 0.35);
      }

      #${PANEL_ID} .browser-use-demo-body {
        flex: 1;
        overflow-y: auto;
        scrollbar-width: thin;
        scrollbar-color: rgba(255, 255, 255, 0.3) transparent;
        padding: 8px 0 12px;
      }

      #${PANEL_ID} .browser-use-demo-body::-webkit-scrollbar {
        width: 8px;
      }

      #${PANEL_ID} .browser-use-demo-body::-webkit-scrollbar-thumb {
        background: rgba(255, 255, 255, 0.25);
        border-radius: 999px;
      }

      .browser-use-demo-entry {
        display: flex;
        gap: 12px;
        padding: 10px 18px;
        border-left: 2px solid transparent;
        border-bottom: 1px solid rgba(255, 255, 255, 0.04);
        animation: browser-use-fade-in 0.25s ease;
        background: #000000;
      }

      .browser-use-demo-entry:last-child {
        border-bottom-color: transparent;
      }

      .browser-use-entry-icon {
        font-size: 16px;
        line-height: 1.2;
        width: 20px;
      }

      .browser-use-entry-content {
        flex: 1;
        min-width: 0;
      }

      .browser-use-entry-meta {
        font-size: 11px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: white;
        margin-bottom: 4px;
        display: flex;
        justify-content: space-between;
        gap: 12px;
      }

      .browser-use-entry-message {
        margin: 0;
        word-break: break-word;
        font-size: 12px;
        color: #f8f9ff;
        display: flex;
        flex-direction: column;
        gap: 6px;
      }

      .browser-use-markdown-content {
        margin: 0;
        line-height: 1.5;
      }

      .browser-use-markdown-content p {
        margin: 0 0 8px 0;
      }

      .browser-use-markdown-content p:last-child {
        margin-bottom: 0;
      }

      .browser-use-markdown-content h1,
      .browser-use-markdown-content h2,
      .browser-use-markdown-content h3 {
        margin: 8px 0 4px 0;
        font-weight: 600;
        color: #f8f9ff;
      }

      .browser-use-markdown-content h1 {
        font-size: 16px;
      }

      .browser-use-markdown-content h2 {
        font-size: 14px;
      }

      .browser-use-markdown-content h3 {
        font-size: 13px;
      }

      .browser-use-markdown-content code {
        background: rgba(255, 255, 255, 0.1);
        padding: 2px 6px;
        border-radius: 3px;
        font-family: 'JetBrains Mono', 'Fira Code', 'Monaco', 'Menlo', monospace;
        font-size: 11px;
        color: #60a5fa;
      }

      .browser-use-markdown-content pre {
        background: rgba(0, 0, 0, 0.3);
        padding: 8px 12px;
        border-radius: 4px;
        overflow-x: auto;
        margin: 8px 0;
        border: 1px solid rgba(255, 255, 255, 0.1);
      }

      .browser-use-markdown-content pre code {
        background: transparent;
        padding: 0;
        color: #f8f9ff;
        font-size: 11px;
        white-space: pre;
      }

      .browser-use-markdown-content ul,
      .browser-use-markdown-content ol {
        margin: 4px 0 4px 16px;
        padding: 0;
      }

      .browser-use-markdown-content li {
        margin: 2px 0;
      }

      .browser-use-markdown-content a {
        color: #60a5fa;
        text-decoration: underline;
      }

      .browser-use-markdown-content a:hover {
        color: #93c5fd;
      }

      .browser-use-markdown-content strong {
        font-weight: 600;
        color: #f8f9ff;
      }

      .browser-use-markdown-content em {
        font-style: italic;
      }

      .browser-use-demo-entry:not(.expanded) .browser-use-markdown-content {
        max-height: 120px;
        overflow: hidden;
        mask-image: linear-gradient(to bottom, rgba(0,0,0,1), rgba(0,0,0,0));
      }

      .browser-use-entry-toggle {
        align-self: flex-start;
        background: rgba(255, 255, 255, 0.1);
        border: 1px solid rgba(255, 255, 255, 0.2);
        color: #f8f9ff;
        padding: 2px 10px;
        font-size: 11px;
        border-radius: 999px;
        cursor: pointer;
      }

      .browser-use-demo-entry.level-info { border-left-color: #60a5fa; }
      .browser-use-demo-entry.level-action { border-left-color: #34d399; }
      .browser-use-demo-entry.level-thought { border-left-color: #f97316; }
      .browser-use-demo-entry.level-warning { border-left-color: #fbbf24; }
      .browser-use-demo-entry.level-success { border-left-color: #22c55e; }
      .browser-use-demo-entry.level-error { border-left-color: #f87171; }

      @keyframes browser-use-fade-in {
        from { opacity: 0; transform: translateY(6px); }
        to { opacity: 1; transform: translateY(0); }
      }

      @media (max-width: 1024px) {
        #${PANEL_ID} {
          font-size: 12px;
        }
        #${PANEL_ID} .browser-use-demo-header {
          padding: 12px 16px 10px;
        }
      }

      #${TOGGLE_BUTTON_ID} {
        position: fixed;
        top: 20px;
        right: 20px;
        width: 44px;
        height: 44px;
        border-radius: 50%;
        border: 1px solid rgba(255, 255, 255, 0.2);
        background: rgba(5, 7, 13, 0.92);
        color: #f8f9ff;
        font-size: 18px;
        display: none;
        align-items: center;
        justify-content: center;
        cursor: pointer;
        z-index: 2147480001;
        box-shadow: 0 8px 20px rgba(0, 0, 0, 0.4);
        transition: transform 0.2s ease, background 0.2s ease;
      }

      #${TOGGLE_BUTTON_ID}:hover {
        transform: scale(1.05);
        background: rgba(5, 7, 13, 0.98);
      }

      #${TOGGLE_BUTTON_ID} img {
        display: block;
        width: 24px;
        height: auto;
        max-width: 100%;
        max-height: 100%;
        object-fit: contain;
        pointer-events: none;
        user-select: none;
      }
    `;
    document.head.appendChild(style);
  }

  function buildPanel() {
    const panel = document.createElement('section');
    panel.id = PANEL_ID;
    panel.setAttribute('role', 'complementary');
    panel.setAttribute('aria-label', 'Browser-use demo panel');
    panel.setAttribute(EXCLUDE_ATTR, 'true');

    const header = document.createElement('header');
    header.className = 'browser-use-demo-header';
    const title = document.createElement('div');
    title.className = 'browser-use-logo';
    const logo = document.createElement('img');
    logo.src = 'https://raw.githubusercontent.com/browser-use/browser-use/main/static/browser-use-dark.png';
    logo.alt = 'Browser-use';
    logo.loading = 'lazy';
    title.appendChild(logo);
    const actions = document.createElement('div');
    actions.className = 'browser-use-header-actions';
    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'browser-use-close-btn';
    closeBtn.setAttribute(EXCLUDE_ATTR, 'true');
    closeBtn.setAttribute('aria-label', 'Hide demo panel');
    closeBtn.dataset.role = 'close-toggle';
    closeBtn.innerHTML = '&times;';
    actions.appendChild(closeBtn);
    header.appendChild(title);
    header.appendChild(actions);

    const body = document.createElement('div');
    body.className = 'browser-use-demo-body';
    body.setAttribute('data-role', 'log-list');

    panel.appendChild(header);
    panel.appendChild(body);
    panel.setAttribute('data-open', 'true');
    return panel;
  }

  function buildToggleButton() {
    const button = document.createElement('button');
    button.id = TOGGLE_BUTTON_ID;
    button.type = 'button';
    button.setAttribute(EXCLUDE_ATTR, 'true');
    button.setAttribute('aria-label', 'Open demo panel');
    const img = document.createElement('img');
    img.alt = 'Browser-use';
    img.loading = 'eager';
    // Use embedded SVG as data URI to avoid CSP issues
    const logoSvg = '<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" fill="none" viewBox="0 0 1000 1000"><path fill="#fff" d="M585.941 28.655C672.468-.3 755.454-7.585 825.373 10.74l1.022.272.605.144.641.19c19.554 5.302 37.541 12.489 53.914 21.402l.672.343.537.32c23.35 12.898 43.372 29.338 59.918 48.857l.691.755.872 1.108a213 213 0 0 1 5.969 7.545l.091.09.05.06.409.582a219 219 0 0 1 13.063 19.595l.355.469h-.077a217 217 0 0 1 3.518 6.192l.113.213.055.101.345.592c.282.517.537 1.036.814 1.555l.223.408a234 234 0 0 1 3.591 7.094l.427.859.077.19a227 227 0 0 1 3.232 7.029l.168.332.173.442a251 251 0 0 1 9.154 24.407l.037.035.032.117.122.453a277 277 0 0 1 6.105 22.763l.095.286.018.056.61 2.895.077.448q.83 3.96 1.559 7.986l.095.419h.096v.619a318 318 0 0 1 3.459 25.541l.009.063a352 352 0 0 1 1.491 26.558l.018.179.005.056.041.44-.041.536c.059 3.969.063 7.973 0 12.009v.773l-.005.427c-.173 9.126-.686 18.422-1.504 27.874v.213c-1.187 13.544-3.055 27.412-5.591 41.568l-.309 1.849-.414 2.106c-5.773 30.846-14.759 63.039-27.064 96.242l-.477 1.39-.327.936-.432-.75a.46.46 0 0 1-.145-.245l-8.828-15.26-9.054-15.393-9.387-15.049-.245-.385-9.627-14.811-.064-.096-10.118-15.101-6.037-8.599-4.372-6.338-.132-.179-10.741-14.616-6.341-8.455-4.686-6.345-.114-.155.032-.177c0-.004 0 .005 0 0l1.354-7.983v-.29l1.06-7.584.836-6.28.077-.541.041-.214.105-.528.75-7.52.454-7.382.45-7.083.15-7.095.005-.063v-.381l.15-6.329-.141-4.696-.009-.408v-1.533l-.305-6.492-.418-5.006-.036-.414v-.764l-.6-6.156-.75-5.733-.905-5.725-.782-4.821-.122-.749-.596-2.091-.614-3.212-1.2-4.943-.018-.061-1.241-4.14h-.113v-.382l-.005-.07v-.235l-1.486-4.606-1.509-4.53-1.196-2.839-.459-1.367-1.8-4.053-1.782-3.856-.027-.058-.041-.081-1.913-3.683-1.955-3.603-2.1-3.454-2.259-3.314-2.255-3.157-4.672-6.028-5.119-5.417-3.754-3.451-3.896-3.45-4.218-3.313-3.909-2.696-.445-.309-3.459-2.231-1.21-.78-2.85-1.499-2.127-1.214-5.259-2.704-5.554-2.402-5.878-2.261-4.659-1.352-1.65-.601-6.645-1.812-6.923-1.656-7.377-1.505-.523-.082-7.168-1.125-8.141-.905-8.577-.603-8.873-.3h-9.318l-9.564.149-9.95.754-4.9.433-5.368.475-10.395 1.203-10.864 1.659-11.018 2.115-11.314 2.414-.05.011-11.491 2.685-.077.02-11.768 3.167-11.914 3.466-.441.141-11.777 3.782-12.232 4.38-9.354 3.62-2.9 1.104-.269.104-12.522 5.127-12.66 5.426-12.854 5.897-12.673 6.261-.141.074-.095.05-12.891 6.587-12.986 6.949-12.982 7.245-12.977 7.695-9.055 5.585-4.086 2.42-3.428 2.191-9.545 6.106-2.55 1.8-10.273 6.796-.248.175-8.358 5.867-4.385 3.022-12.829 9.206-12.197 9.147-.481.361-6.037 4.677-6.643 5.135-9.422 7.646-.941.763-.05.041-2.121 1.667-12.366 10.402-12.226 10.716-12.02 10.97-.057.053-11.932 11.023-11.62 11.469-.15.148-11.476 11.478-11.164 11.763-5.587 6.044-5.479 5.773-.111.119-10.712 12.216-10.556 12.214-.119.179-10.31 12.368-1.808 2.259-8.306 10.269-3.769 4.973-5.337 6.978-.553.726-9.509 12.672-9.207 12.832-8.909 12.836-8.599 12.971-8.018 12.536-.286.445-.078.127-7.733 12.79-.038.064-4.53 7.701-3.172 5.289-.029.05-5.551 10.204-1.658 2.708-.126.246-6.516 12.59-.034.063-.052.05-.094.096-6.459 12.912-1.055 2.267-4.983 10.564-5.706 12.762-3.2 7.465-2.262 5.275-4.797 12.44-.028.078-4.656 12.312.001.219.001.458h-.135l-4.123 11.777-.901 2.999-2.869 9.069-1.658 5.874-1.814 6.052-2.111 8.138-.904 3.471-2.286 9.855-.129.559-.303 1.208-2.262 11.159-1.96 11-.01.077-1.498 10.641-.027.241-.728 6.692-.443 3.394-.009.068-.748 10.032-.002.046.002.454-.608 9.391-.002 1.481.002 1.509v.454l-.152 6.052.152 6.32v2.731l.451 8.705.105.959.046.4.603 7.101.754 5.27.295 2.663.008.059 1.351 7.674 1.508 7.383 1.61 6.734.053.209 1.948 6.451 1.556 4.38.089.255.017.045.412 1.377.041.136 2.261 5.725L126.55 824l2.555 5.261 2.712 4.521.064.109v.286l1.029 1.545 1.906 2.858 3.168 4.375 3.292 4.04 3.467 3.771 3.606 3.757.17.155 3.555 3.271.035.032 3.916 3.312 4.205 3.158 3.801 2.485.141.091.375.281.202.15 4.8 2.854 1.288.681 3.834 2.031 5.276 2.563 5.686 2.39 4.544 1.708 1.508.563 5.803 1.799.508.155 6.792 1.813 7.07 1.504 7.532 1.354 3.13.45.05.004 4.681.754 6.777.618 1.486.132 4.16.295 4.435.309 9.054.3 9.348-.15 9.797-.45 9.956-.604 10.395-1.054 10.561-1.508 10.824-1.804.236-.046.162.123.258.195.345.259 1.693 1.268.092.068.037.027.16.137 3.643 2.749.281.19.097.064.039.027.479.359h.305v.232l.899.677h-.049l6.421 4.848.096.072.174.128 14.619 10.59 5.65 3.994 7.333 5.062 1.96 1.508 10.567 6.943 4.529 3.171.587.377 14.665 9.437.286.177 4.087 2.54 10.867 6.788.084.05 15.315 9.009.35.2 1.126.646 13.674 7.919a.45.45 0 0 1 .356.082h2.283l-1.541.549-.917.332-4.23 1.508-.072.028-2.341.822a639 639 0 0 1-9.93 3.494l-3.059 1.095-.074.023-11.116 3.607-4.073 1.354-8.207 2.44h.435l-3.425.891-2.642.686a599 599 0 0 1-11.746 3.194l-.719.195-.911.227a514 514 0 0 1-8.024 2.008l-2.606.655h.449l-3.981.881-.05.014-2.65.586-1.426.318-10.729 2.267-3.5.627a500 500 0 0 1-8.442 1.559l-2.869.536-1.455.204a482 482 0 0 1-10.892 1.69l-2.313.373-1.811.2c-2.585.345-5.159.672-7.723.972l-4.825.641-.277.018-2.974.213q-4.341.429-8.64.768l-2.327.214-4.538.3-2.75.131q-3.054.172-6.085.296l-.541.027h-.116l-.067.005c-4.394.167-8.75.267-13.066.287l-.204.01h-.71c-3.748.01-7.465-.03-11.153-.13l-2.047-.02-1.422-.09a335 335 0 0 1-6.562-.289l-5.317-.227-2.857-.3-1.66-.15a299 299 0 0 1-4.522-.404l-3.938-.355-3.058-.304-9.784-1.354-.055-.005-2.982-.45-.052-.009-9.362-1.658-3.03-.604-9.217-1.968-2.888-.758-8.91-2.268-1.047-.313-1.992-.595-.05-.018-2.909-.868h.153l-5.737-1.813-.101-.032-2.589-1.009a249 249 0 0 1-4.897-1.753l-3.602-1.286-.087-.027-2.718-1.059-8.162-3.326-2.587-1.368-7.852-3.621-2.092-1.226a229 229 0 0 1-3.892-2.063l-4.154-2.158-2.588-1.522-7.253-4.38-3.769-2.631a236 236 0 0 1-3.54-2.413l-2.064-1.308-8.944-6.815-.6-.455-3.58-3.035q-.964-.811-1.919-1.631l-2.526-2.14-1.101-1.045a214 214 0 0 1-4.673-4.33l-2.394-2.19-2.215-2.358a209 209 0 0 1-8.774-9.482l-2.938-3.294-1.224-1.527-6.8-8.764-.046-.077-.146-.286-.543-.777a216 216 0 0 1-4.077-5.821l-1.559-2.23-.128-.182-1.077-1.686-.1-.159-.342-.536-3.034-4.898-.045-.086-.127-.255-.117-.236-.29-.481-.447-.559-.043-.05-.025-.064-.248-.622q-.09-.151-.18-.309l-.131-.196-.436-.781-.575-1-.663-1.104-.344-.686q-.577-1.029-1.143-2.072l-.625-1.013-1.095-2.053-.09-.169-.036-.068-.182-.363-.128-.25-.902-1.813-.023-.045-.305-.614-.322-.718a258 258 0 0 1-1.675-3.421l-.12-.241-.098-.195-.026-.055-.328-.654-1.024-2.194-.281-.423-.031-.05-.436-.654h.167L23.785 865l-.984-2.294q-.21-.484-.418-.968l-1.472-3.239-.603-1.659-.637-1.535-.126-.296-.251-.609-1.108-3.166-.164-.459a255 255 0 0 1-1.275-3.512l-.666-1.595-.768-2.299-1.362-4.385-1.506-4.525-.024-.068v-.318l-.47-1.758a272 272 0 0 1-1.603-5.789l-.628-2.203-.305-1.223-.314-1.467a284 284 0 0 1-1.955-8.51l-.445-1.481-.012-.055-.516-3.194a299 299 0 0 1-1.475-8.083l-.117-.468-.14-.558h.057l-.216-1.513q-.518-3.237-.971-6.507l-.55-3.389-.155-1.84-.108-1.095a333 333 0 0 1-1.368-14.203l-.035-.423-.021-.331a349 349 0 0 1-.4-6.252l-.032-.514-.001-.136a361 361 0 0 1-.442-12.526l-.011-.177v-.35c-.272-16.243.516-32.913 2.328-49.924l.241-2.644.221-1.5q.67-5.778 1.495-11.604l.007-.059a482 482 0 0 1 2.073-13.276l.133-1.063.886-4.712q.515-2.822 1.065-5.652l.015-.086a543 543 0 0 1 7.405-32.636c3.818-14.739 8.309-29.66 13.442-44.649l.126-.399.19-.609.095-.296.454-1.204a681 681 0 0 1 10.567-28.369l.366-.945.078-.173q1.072-2.686 2.169-5.366C85.014 443.52 154.799 339.427 246.82 247.415l4.322-4.297q2.311-2.283 4.633-4.548h-.096l.671-.56c50.277-49.001 103.949-91.419 158.66-126.292h-1.118l2.317-.765a901 901 0 0 1 14.8-9.198l.2-.122a882 882 0 0 1 15.303-9.093l.045-.027c32.543-18.892 65.288-35.085 97.752-48.369a678 678 0 0 1 41.632-15.49m86.295 146.339a.45.45 0 0 1 .528-.087l.077.05 4.386 3.566c185.218 151.444 311.755 364.181 322.091 542.24l.223 4.194c1.149 24.021.127 46.775-2.941 68.134l-.036.241c-1.746 12.094-4.15 23.739-7.187 34.912l.146.031-.296.596-.027.063-.032.059c-5.318 19.337-12.541 37.261-21.559 53.654l-.145.327-.023.046-.027.041-.128.163a218 218 0 0 1-2.941 5.157l-.363.654-.105.255-.168.2-.059.095h.25l-.7.713a212 212 0 0 1-3.905 6.248l-.622.986-3.328 4.993-1.054 1.404a215 215 0 0 1-4.314 5.87l-1.286 1.799-2.5 3.044a205 205 0 0 1-3.677 4.426l-1.091 1.313-.605.654a216 216 0 0 1-5.75 6.316l-1.209 1.349-3.8 3.798-4.227 4.08-2.027 1.795a213 213 0 0 1-10.037 8.569l-.65.532-4.536 3.63-4.323 3.026a214 214 0 0 1-7.923 5.388l-1.677 1.118-4.991 3.176-4.854 2.735-2.146 1.159q-1.44.798-2.9 1.576l-.25.137-.15.077a247 247 0 0 1-5.591 2.871l-4.691 2.345-5.154 2.271-5.591 2.422-5.455 2.117-.545.2a236 236 0 0 1-5.096 1.877l-.104.041-.1.031a255 255 0 0 1-10.014 3.331l-1.222.418-2.346.659a266 266 0 0 1-6.141 1.731l-3.318.94-2.545.568c-2.16.532-4.337 1.045-6.532 1.527l-3.173.777-2.018.345-.782.132a300 300 0 0 1-8.123 1.504l-1.482.29-.05.01-2.018.286q-4.656.737-9.409 1.345l-1.232.172-.05.005-2.168.241c-1.073.127-2.15.245-3.232.363l-1.359.15-6.2.604-2.068.128q-3.803.298-7.654.508l-3.578.273h-.104l-3.937.072q-4.001.135-8.05.18l-1.518.05-1.791-.02q-5.345.015-10.786-.12l-1.186-.01-5.096-.152h-.054l-8.86-.45h-.045l-4.023-.313a514 514 0 0 1-3.632-.273l-6.559-.477-4.572-.554a489 489 0 0 1-7.15-.814l-2.641-.295-3.723-.518c-.577-.077-1.155-.163-1.732-.241l-1.05-.145-.295-.045a516 516 0 0 1-6.078-.9l-1.74-.259-.055-.005-6.645-1.058-8.164-1.513-3.555-.727a597 597 0 0 1-5.8-1.177l-5.604-1.118-4.605-1.126a549 549 0 0 1-8.868-2.113l-1.645-.391-2.514-.654a587 587 0 0 1-5.314-1.386l-7.286-1.885-7.109-2.118-8.305-2.417-7.041-2.244-.072-.023-.237-.077-2.527-.809h.059l-5.6-1.836-3.732-1.349a681 681 0 0 1-6.891-2.413l-4.94-1.676-7.11-2.726-8.459-3.167-6.345-2.644-2.796-1.132-6.427-2.571-7.254-3.176-8.459-3.626-4.596-2.199a753 753 0 0 1-5.736-2.649l-5.382-2.403-7.268-3.63-8.45-4.076-7.264-3.78-8.454-4.38-7.255-3.93-8.209-4.475-.109-.06-.059-.036-1.491-.809h.068l-5.812-3.325-.109-.059-.1-.059-1.374-.787-6.831-3.989-7.144-4.166-.112-.064-.078-.045-1.362-.795-6.872-4.148-7.137-4.462-.115-.068-.387-.246-.947-.59-2.742-1.731-.042-.028-.037-.036-.109-.109-.182-.109-.528-.318-1.1-.686-.119-.073-1.661-1.058-.234-.16-.228-.149-1.813-1.209-2.56-1.658-.122-.078-1.163-.754-.775-.541c-.606-.395-1.211-.795-1.817-1.19l-3.068-1.963-4.085-2.726-.193-.182-2.002-1.354a617 617 0 0 1-3.456-2.339l-4.205-2.845-.118-.077-.166-.113-1.054-.714-4.066-2.799-.333-.222-.128-.086-1.23-.818h.099l-3.513-2.549a969 969 0 0 1-8.648-6.197l-1.495-.996-4.7-3.489-7.252-5.434-3.162-2.263-4.398-3.484-7.847-6.039-1.343-1.104a951 951 0 0 1-6.351-5.025l-.466-.368-8.461-6.797-.755-.604-1.007-.804-6.852-5.693-6.798-5.743-1.964-1.659-4.449-3.921a901 901 0 0 1-5.375-4.689l-2.558-2.108-4.952-4.552a1066 1066 0 0 1-3.364-3.022l-5.894-5.275-.773-.772-2.731-2.553a1045 1045 0 0 1-14.523-13.713l-1.313-1.24-1.704-1.677a1023 1023 0 0 1-16.366-16.247l-3.844-3.844-6.645-6.942-6.359-6.657-.137-.14-3.019-3.172-9.51-10.413-.451-.455-4.35-4.939a972 972 0 0 1-6.839-7.728l-1.514-1.695-5.592-6.497-.511-.604a1009 1009 0 0 1-5.003-5.889l-1.286-1.517-.634-.745-1.932-2.276-9.08-11.014-.164-.2-.304-.454-.114-.173.054-.195 1.812-6.797 1.058-4.23.755-2.722 2.118-7.101 2.225-6.974.043-.137.052-.163 1.87-5.739.193-.595.265-.795.037-.109 2.416-7.251 2.722-7.561 3.016-7.537.145-.573.019-.063 2.869-6.947 2.113-5.28 1.061-2.426 3.323-7.706.906-2.108 2.725-5.757.025-.054 2.704-5.943.295-.659.404-.804.2-.4.127-.25 5.494-10.99 2.233-4.467 4.234-8.014.344-.65.424.6.037.05 8.831 12.426.04.055 9.055 12.371 5.134 6.648 4.247 5.561.134.177 9.658 12.222 9.966 12.231 10.108 12.067 6.048 6.838 3.615 4.035.765.913 10.559 11.768 10.866 11.617 4.075 4.226 6.645 6.797.053.064.277.418 11.288 11.136 3.17 3.021 8.304 8.001.093.086 11.444 10.55.086.078 11.776 10.568 1.051.795h-.142l11.01 9.614 11.956 9.864.123.1 12.233 9.814 12.252 9.414.133.1.086.068 12.271 9.278 7.401 5.134 5.133 3.775 12.534 8.606 12.532 8.455 12.668 7.992 12.682 7.851 3.009 1.654 1.541.85h-.114l8.241 4.889 11.632 6.492 1.059.609 12.664 6.783 8.609 4.38 3.873 2.086.059.032 12.518 6.029 12.373 5.738 12.372 5.43.137.054 12.209 4.912 12.114 4.693 2.409.877 9.65 3.494 11.918 3.925 11.623 3.472 11.468 3.166.072.019.532.136 10.705 2.712 11.177 2.417 10.814 2.104 10.6 1.663 8.759 1.209 1.673.304 9.927 1.054 9.818.754.382.019 9.118.436 9.114.15h.068l8.913-.155h.06l8.363-.45 8.287-.754 7.69-1.054 4.187-.681 3.191-.523 7.086-1.504 6.641-1.663 6.464-1.953 4.709-1.573 1.172-.39 5.705-2.249 5.436-2.417 5.1-2.549 4.819-2.713 4.504-2.849 2.268-1.622 1.959-1.394.705-.568.532-.427h-.068l1.086-.814 1.786-1.336 3.764-3.316 3.618-3.462 3.464-3.612 3.309-3.762 3.154-4.058 3.009-4.216 2.846-4.494 2.718-4.679 2.546-5.089 2.259-5.271 2.259-5.724 2.113-6.039 1.805-6.315 1.804-6.615.246-1.268 1.114-5.825.754-4.516.6-3.021.905-7.829.004-.045.75-8.092.6-8.437.155-8.737-.15-9.205-.305-9.492-.718-8.946-.036-.418v-.304l-.314-3.017-.741-7.074-.009-.06-.441-2.953-.9-7.188-.009-.059-.023-.145-1.786-10.559-2.109-10.864-2.409-10.99-.455-1.672-2.418-9.669-.055-.204-3.09-11.322-.028-.096-3.463-11.599-3.323-9.973-.6-1.949-4.268-11.632-.118-.313-4.523-12.209-1.65-3.762-3.309-8.41-.023-.059-5.427-12.362-5.732-12.527-5.768-11.822h-.05l-.1-.313-.141-.423-6.309-12.472-1.359-2.267-5.441-10.427-2.868-4.98-4.228-7.697-.309-.518-7.241-12.013-.145-.236-6.064-9.814-.132-.218-.427-.69-.927-1.718-8.127-12.644-.119-.118-.054-.069-8.305-12.376-8.6-12.526-4.077-5.584-4.932-6.88-.054-.071-6.187-8.299-3.018-4.07-9.659-12.38-9.682-12.061-.05-.059-.082-.105-9.959-12.075-.032-.033-3.454-3.885-.146-.161-.045-.057-.614-.689-5.927-7.04-.055-.064-.049-.058-10.51-11.71-9.063-9.815-1.673-1.977-11.005-11.457-1.049-1.052-10.119-10.264-11.259-10.961-.063-.06-7.55-7.249-3.919-3.765-11.195-9.999-.145-.134-.451-.447-11.913-10.556-.064-.056-11.854-10.053-.159-.131-12.041-9.807-.037-.029-12.218-9.655-12.386-9.362-.123-.094-12.259-9.117-10.705-7.389-1.777-1.333-.041-.028-.6-.42.646-.351 7.854-4.228 8.014-4.082 4.327-2.164h-.345l2.072-.864 1.814-.756 7.85-3.771 7.709-3.478 7.705-3.474 7.677-3.162 7.586-3.186 7.409-2.871 5.014-1.843h-.382l2.746-.871 7.441-2.578 7.259-2.269 7.1-2.265 7.113-1.968 6.946-1.964 6.504-1.663.055-.014zm105.978 377.474 4.231 8.001 4.078 8.01 3.782 7.861 3.59 7.787.096.091.782.772h-.396l3.182 6.911 3.327 7.715 3.318 7.701 2.914 7.429h.046l.077.309 2.863 7.378 2.723 7.561.041.131 2.527 7.274 2.419 7.252.454 1.358 1.759 5.575.05.164 1.968 7.115.605 1.958 1.364 4.998 1.59 6.665a.44.44 0 0 1 .119.486l-.018.046a1 1 0 0 1-.05.082c-.091.109-.178.222-.269.331l-1.909 2.449-4.586 5.489a1023 1023 0 0 1-27.155 31.536l-1.195 1.354-.391.404a1027 1027 0 0 1-22.182 23.844l-2.059 2.19-1.591 1.591a1035 1035 0 0 1-50.45 48.615l-.023.054-.068.059-2.177 1.927a992 992 0 0 1-8.359 7.397l-1.241 1.09-.791.722h.136l-1.004.786-.127.119-.769.586a951 951 0 0 1-8.9 7.628l-2.445 2.099-.805.645c-4.804 4.031-9.64 8.02-14.509 11.954l-.081.078-.182.163-.241-.063-.2-.055-6.546-1.74-.045-.014-6.95-1.813-7.105-1.967-7.113-2.267-4.837-1.613-2.413-.804-7.4-2.417-7.418-2.726-7.555-2.872-7.482-3.139-.082-.032-3.995-1.631-.086-.032-3.45-1.504-7.641-3.294-.091-.036-7.859-3.631-.059-.027-7.255-3.403-.118-.055-.259-.172-.2-.137-7.823-3.757-7.868-4.085-7.855-4.08-.241-.122v-.427l-.004-.232.191-.136 14.709-10.505.868-.622.282-.2 15.4-11.441.45-.336.041-.027 15.65-12.19 15.55-12.686 15.25-13.13 15.086-13.426 3.473-3.322 11.177-10.572 2.391-2.39.677-.682.096-.091.132-.131 10.745-10.455.45-.441 8.618-8.891.741-.764.127-.14 4.705-4.844 1.804-1.958 6.491-7.092 5.446-5.748 13.423-15.08.754-.904 6.5-7.556 5.764-6.651.563-.736.128-.168 6.068-7.533 6.041-7.252.277-.418 6.064-7.728 5.463-7.006.423-.546 11.768-15.843 11.327-16.006.428-.6zM183.482 8.61c56.203-12.83 122.13-10.008 193.358 8.84l1.423.34h-.14c17.617 4.705 35.557 10.386 53.752 17.054l3.58 1.323.081.04a.44.44 0 0 1 .161.18l.519.188-.617.349a.45.45 0 0 1-.174.098l-.063.038-12.8 7.276-2.675 1.524-15.323 9.162-8.699 5.288-11.53 7.24-5.888 3.778-6.201 3.984-6.351 4.256-6.167 4.136-11.443 7.98-.116.119-.059.048-8.539 6.034-1.584 1.148-.325.234-7.82 5.665-1.508 1.11-2.718 2.053h.063l-1.102.799-.124.107-.474.329-2.563 1.936v.127l-.247.125-.256.126-.685.518-.576.463h.239l-1.219.813-.112.094-.252.15-.784.523-2.482 1.873-.572.509-.157.139-.07-.01-.173.087-.123.063-.136-.018-.701-.087-.508-.063-6.796-1.207-3.857-.531-3.842-.527-7.702-.904-7.515-.753-7.236-.602-3.54-.223-3.734-.233-6.93-.151h-3.928l-2.841-.15-1.326.147-5.315.003-6.482.3-6.344.457-6.022.599-5.87.752-5.586.907-5.41.901-4.681 1.068-.603.139-4.977 1.208-4.731 1.328-.085.024-2.378.691-2.301.669-4.342 1.495-4.211 1.654-4.077 1.814-3.92 1.809-3.752 1.949-3.613 1.957-3.454 2.104-3.312 2.259-3.117 2.224-2.606 2.083-3.453 2.764-5.394 5.093-5.123 5.422-4.826 6.033-2.251 3.151-2.243 3.283-1.048 1.954-.861 1.427-.052.091-2.106 3.61-1.953 3.756-.632 1.472-.258.604-.024.052-.897 1.792-1.654 4.059-1.652 4.208-.352 1.054-.099.302-1.212 3.178-1.352 4.653-.07.258-.985 3.52-.303 1.054-1.356 4.97-.945 4.726-.089.454-.018.083-1.028 5.423-.029.162-.903 5.728-.077.768-.07.715-.041.408-.567 3.842-.6 6.146.001 1.945-.304 4.248-.3 6.493-.151 6.635v6.776l.151 7.094.426 6.658.027.416.521 6.421.081.97.605 6.04.141 1.423.009.087.904 7.528 1.206 7.845 1.359 8.005.032.189-.114.154-1.661 2.265-9.381 12.356-.131.175-10.723 14.799-10.403 14.922-.107.216-8.06 11.881-2.071 2.958-.042.065-.119.181-6.068 9.474-3.619 5.427-4.531 7.4-4.98 7.846-.045.081-2.82 4.898-6.141 10.328-.052.09-1.357 2.415-5.135 9.062-2.188 3.789a.45.45 0 0 1-.14.245l-.414.718-.34-.886-1.51-3.928-3.173-9.063-.907-2.417-3.478-10.435-.958-3.164a613 613 0 0 1-1.268-4.001l-1.854-5.674-2.12-7.415-1.509-5.438-2.72-9.666-.757-3.033-2.868-12.08-.153-.604-3.023-14.06-.01-.047v-.31l-.094-.493a510 510 0 0 1-1.846-9.777l-.615-3.251-.302-1.208-1.97-12.574-.14-2.049a465 465 0 0 1-.942-7.254l-.128-.977-.4-3.079-.056-.406-.005-.053-.06-.447-.387-3.88-.714-7.145-.045-.408-.106-1.1-.044-.431-.044-.476-.2-4.37a418 418 0 0 1-.462-7.661l-.04-.607-.801-.802h.632l-.141-6.632-.152-5.739v-2.331q-.044-4.108 0-8.173v-4.319l.174-3.721q.098-3.05.245-6.074l.034-.915-.001-1.963.455-6.225.268-3.745.03-.437.005-.047.151-1.522.604-5.742.603-4.967v-.611l.712-4.155q.172-1.223.355-2.441l.387-3.182.061-.517.15-1.056.76-3.801.905-4.678.604-3.171.303-1.367.907-4.229.785-3.53.122-.564.456-1.811.608-2.129.272-.971q.553-2.12 1.138-4.22l.41-1.631.143-.585.082-.321.374-1.188.423-1.379.161-.526.019-.06.098-.32.961-3.008.321-.966q.406-1.261.825-2.515l.511-1.789 1.367-3.951 2.114-5.435.302-.903.892-2.086q1.158-2.896 2.383-5.746l.503-1.238.301-.898.034-.076.657-1.188.203-.449.527-1.314h-.066l.328-.655.1-.251.952-1.851.905-1.962.61-1.322h-.084l.4-.681.97-1.663q.324-.64.652-1.278l.328-.657.125-.251.228-.398q.429-.82.864-1.634l.444-.888.126-.25.63-1.11.605-1.208.033-.065.05-.05.112-.115.062-.097q.564-1.008 1.136-2.011l.115-.229.029-.049.11-.168c.181-.315.367-.626.55-.94l.385-.687.112-.219.243-.368.05-.083h-.105l.443-.668.283-.426.034-.049.134-.271.101-.202v-.197l.19-.002.85-1.509.383-.687.036-.062.089-.157.33-.535 5.032-7.62h-.1l.498-.68.114-.226h.055l5.752-7.82.044-.052.144-.145.6-.756q1.88-2.446 3.83-4.834l1.886-2.38 1.948-2.188a212 212 0 0 1 4.135-4.643l1.333-1.494.873-.875a210 210 0 0 1 5.674-5.777l1.167-1.214 1.85-1.679a212 212 0 0 1 5.452-4.956h-.072l.906-.752.718-.602a212 212 0 0 1 7.003-5.765l.947-.778 1.104-.82a219 219 0 0 1 25.577-16.938l1.466-.859.924-.476q4.356-2.4 8.843-4.623l.367-.196.509-.235a237 237 0 0 1 9.335-4.327l.599-.279.455-.183a248 248 0 0 1 14.16-5.598h-.146l2.35-.785a263 263 0 0 1 13.598-4.349h-.37l3.027-.758a278 278 0 0 1 11.728-3.002l.582-.153z"></path></svg>';
    img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(logoSvg);
    button.appendChild(img);
    button.addEventListener('click', () => openPanel(true));
    return button;
  }

  function attachCloseHandler() {
    const closeBtn = state.panel?.querySelector('[data-role="close-toggle"]');
    if (closeBtn) {
      closeBtn.addEventListener('click', () => closePanel(true));
    }
  }

  function openPanel(saveState = true) {
    state.isOpen = true;
    if (state.panel) {
      state.panel.setAttribute('data-open', 'true');
    }
    if (state.toggleButton) {
      state.toggleButton.style.display = 'none';
    }
    adjustLayout();
    if (saveState) {
      persistPanelState();
    }
  }

  function closePanel(saveState = true) {
    state.isOpen = false;
    if (state.panel) {
      state.panel.setAttribute('data-open', 'false');
    }
    document.body.style.marginRight = '';
    if (state.toggleButton) {
      state.toggleButton.style.display = 'flex';
    }
    if (saveState) {
      persistPanelState();
    }
  }

  function persistPanelState() {
    try {
      sessionStorage.setItem(PANEL_STATE_KEY, state.isOpen ? 'open' : 'closed');
    } catch (err) {
      // Ignore storage errors
    }
  }

  function loadPanelState() {
    try {
      const stored = sessionStorage.getItem(PANEL_STATE_KEY);
      if (!stored) return true;
      return stored === 'open';
    } catch (err) {
      return true;
    }
  }

  function adjustLayout() {
    const width = computePanelWidth();
    document.documentElement.style.setProperty('--browser-use-demo-panel-width', `${width}px`);
    if (state.isOpen) {
      document.body.style.marginRight = `${width + 16}px`;
      if (state.toggleButton) {
        state.toggleButton.style.display = 'none';
      }
    } else {
      document.body.style.marginRight = '';
      if (state.toggleButton) {
        state.toggleButton.style.display = 'flex';
      }
    }
  }

  function computePanelWidth() {
    const viewport = Math.max(window.innerWidth, 320);
    const maxAvailable = Math.max(220, viewport - 240);
    const target = Math.min(380, Math.max(260, viewport * 0.3));
    const width = Math.max(220, Math.min(target, maxAvailable));
    try {
      sessionStorage.setItem('__browserUsePanelWidth__', String(width));
    } catch {
      // fallthrough
    }
    return width;
  }

  function loadPanelWidth() {
    try {
      const saved = sessionStorage.getItem('__browserUsePanelWidth__');
      return saved ? Number(saved) : null;
    } catch {
      return null;
    }
  }

  function restoreMessages() {
    try {
      const raw = sessionStorage.getItem(STORAGE_KEY);
      if (!raw) return [];
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch (err) {
      return [];
    }
  }

  function persistMessages() {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state.messages.slice(-MAX_MESSAGES)));
      if (state.list) {
        sessionStorage.setItem(STORAGE_HTML_KEY, state.list.innerHTML);
      }
    } catch (err) {
      // Ignore sessionStorage errors (private mode, etc.)
    }
  }

  function hydrateFromStoredMarkup() {
    if (!state.list) return false;
    try {
      const html = sessionStorage.getItem(STORAGE_HTML_KEY);
      if (html) {
        state.list.innerHTML = html;
        for (const entryNode of state.list.querySelectorAll('.browser-use-demo-entry')) {
          const toggle = entryNode.querySelector('.browser-use-entry-toggle');
          if (toggle) {
            toggle.addEventListener('click', () =>
              toggleEntryExpansion(entryNode, toggle, entryNode.getAttribute('data-id'))
            );
          }
          applyPersistedExpansion(entryNode);
        }
        state.list.scrollTop = state.list.scrollHeight;
        return true;
      }
    } catch (err) {
      // ignore hydration failures
    }
    return false;
  }

  function normalizeEntry(detail) {
    if (!detail) return null;
    const entry = typeof detail === 'string' ? { message: detail } : { ...detail };
    entry.message = typeof entry.message === 'string' ? entry.message : JSON.stringify(entry.message ?? '');
    entry.level = (entry.level || 'info').toLowerCase();
    if (!LEVEL_ICONS[entry.level]) {
      entry.level = 'info';
    }

    if (!entry.metadata || typeof entry.metadata !== 'object') {
      entry.metadata = {};
    }

    entry.timestamp = entry.timestamp || new Date().toISOString();
    entry.id = entry.id || `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    return entry;
  }

  function appendEntry(entry, shouldPersist = true) {
    if (shouldPersist) {
      state.messages.push(entry);
      if (state.messages.length > MAX_MESSAGES) {
        state.messages = state.messages.slice(-MAX_MESSAGES);
      }
      persistMessages();
    }

    if (!state.list) {
      return;
    }

    const node = createEntryNode(entry);
    applyPersistedExpansion(node);
    state.list.appendChild(node);
    state.list.scrollTop = state.list.scrollHeight;
  }

  function createEntryNode(entry) {
    const row = document.createElement('article');
    row.className = `browser-use-demo-entry level-${entry.level}`;
    row.setAttribute('data-id', entry.id);

    const icon = document.createElement('span');
    icon.className = 'browser-use-entry-icon';
    icon.textContent = LEVEL_ICONS[entry.level] || LEVEL_ICONS.info;

    const content = document.createElement('div');
    content.className = 'browser-use-entry-content';

    const meta = document.createElement('div');
    meta.className = 'browser-use-entry-meta';
    const time = formatTime(entry.timestamp);
    const label = LEVEL_LABELS[entry.level] || entry.level;
    meta.innerHTML = `<span>${time}</span><span>${label}</span>`;

    const messageWrapper = document.createElement('div');
    messageWrapper.className = 'browser-use-entry-message';
    const messageText = entry.message.trim();
    const messageHtml = messageText;
    const message = document.createElement('div');
    message.className = 'browser-use-markdown-content';
    message.textContent = messageHtml;
    messageWrapper.appendChild(message);

    if (messageText.length > 160) {
      const toggle = document.createElement('button');
      toggle.type = 'button';
      toggle.className = 'browser-use-entry-toggle';
      toggle.setAttribute(EXCLUDE_ATTR, 'true');
      toggle.textContent = 'Expand';
      toggle.addEventListener('click', () => toggleEntryExpansion(row, toggle, entry.id));
      messageWrapper.appendChild(toggle);
    } else {
      row.classList.add('expanded');
    }

    content.appendChild(meta);
    content.appendChild(messageWrapper);
    row.appendChild(icon);
    row.appendChild(content);
    return row;
  }

  function applyPersistedExpansion(node) {
    if (!node) return;
    try {
      const expanded = new Set(JSON.parse(sessionStorage.getItem(EXPANDED_IDS_KEY) || '[]'));
      const id = node.getAttribute('data-id');
      if (id && expanded.has(id)) {
        node.classList.add('expanded');
        const toggle = node.querySelector('.browser-use-entry-toggle');
        if (toggle) {
          toggle.textContent = 'Collapse';
        }
      }
    } catch {
      // ignore
    }
  }

  function toggleEntryExpansion(row, toggle, entryId) {
    if (!row) return;
    const isExpanded = row.classList.toggle('expanded');
    if (toggle) {
      toggle.textContent = isExpanded ? 'Collapse' : 'Expand';
    }
    try {
      const expanded = new Set(JSON.parse(sessionStorage.getItem(EXPANDED_IDS_KEY) || '[]'));
      if (isExpanded) {
        expanded.add(entryId);
      } else {
        expanded.delete(entryId);
      }
      sessionStorage.setItem(EXPANDED_IDS_KEY, JSON.stringify(Array.from(expanded)));
    } catch {
      // ignore persistence issues
    }
  }

  function formatTime(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) {
      return new Date().toLocaleTimeString();
    }
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }

  function debounce(fn, delay) {
    let frame;
    return (...args) => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => fn.apply(null, args));
    };
  }

  function handleLogEvent(event) {
    const entry = normalizeEntry(event?.detail);
    if (!entry) return;
    appendEntry(entry, true);
  }

  const boot = () => {
    if (window.__browserUseDemoPanelBootstrapped) {
      return;
    }

    const start = () => {
      if (window.__browserUseDemoPanelBootstrapped) {
        return;
      }
      if (!document.body) {
        requestAnimationFrame(start);
        return;
      }
      window.__browserUseDemoPanelBootstrapped = true;
      initializePanel();
    };

    start();
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }
  window.addEventListener('browser-use-log', handleLogEvent);
})();
"""


class DemoMode:
	"""Encapsulates browser overlay injection and log broadcasting for demo mode."""

	VALID_LEVELS = {'info', 'action', 'thought', 'error', 'success', 'warning'}

	def __init__(self, session: BrowserSession):
		self.session = session
		self.logger = logging.getLogger(f'{__name__}.DemoMode')
		self._script_identifier: str | None = None
		self._script_source: str | None = None
		self._panel_ready = False
		self._lock = asyncio.Lock()

	def reset(self) -> None:
		self._script_identifier = None
		self._panel_ready = False

	def _load_script(self) -> str:
		if self._script_source is None:
			self._script_source = _DEMO_PANEL_SCRIPT

		# Replace placeholder with actual session ID
		session_id = self.session.id
		script_with_session_id = self._script_source.replace('__BROWSER_USE_SESSION_ID_PLACEHOLDER__', session_id)
		self.logger.debug(f'Injecting session ID {session_id} into demo panel script')
		return script_with_session_id

	async def ensure_ready(self) -> None:
		"""Add init script and inject overlay into currently open pages."""
		if not self.session.browser_profile.demo_mode:
			return
		if self.session._cdp_client_root is None:
			raise RuntimeError('Root CDP client not initialized')

		async with self._lock:
			script = self._load_script()

			if self._script_identifier is None:
				self._script_identifier = await self.session._cdp_add_init_script(script)
				self.logger.debug('Added auto-injection script for demo overlay')

			await self._inject_into_open_pages(script)
			self._panel_ready = True
			self.logger.debug('Demo overlay injected successfully')

	async def send_log(self, message: str, level: str = 'info', metadata: dict[str, Any] | None = None) -> None:
		"""Send a log entry to the in-browser panel."""
		if not message or not self.session.browser_profile.demo_mode:
			return

		try:
			await self.ensure_ready()
		except Exception as exc:
			self.logger.warning(f'Failed to ensure demo mode is ready: {exc}')
			return

		if self.session.agent_focus_target_id is None:
			self.logger.debug('Cannot send demo log: no active target')
			return

		level_value = level.lower()
		if level_value not in self.VALID_LEVELS:
			level_value = 'info'

		payload = {
			'message': message,
			'level': level_value,
			'metadata': metadata or {},
			'timestamp': datetime.now(timezone.utc).isoformat(),
		}

		script = self._build_event_expression(json.dumps(payload, ensure_ascii=False))

		try:
			session = await self.session.get_or_create_cdp_session(target_id=None, focus=False)
		except Exception as exc:
			self.logger.debug(f'Cannot acquire CDP session for demo log: {exc}')
			return

		try:
			await session.cdp_client.send.Runtime.evaluate(
				params={'expression': script, 'awaitPromise': False}, session_id=session.session_id
			)
		except Exception as exc:
			self.logger.debug(f'Failed to send demo log: {exc}')

	def _build_event_expression(self, payload: str) -> str:
		return f"""
(() => {{
	const detail = {payload};
	const event = new CustomEvent('browser-use-log', {{ detail }});
	window.dispatchEvent(event);
}})();
""".strip()

	async def _inject_into_open_pages(self, script: str) -> None:
		targets = await self.session._cdp_get_all_pages(  # - intentional private access
			include_http=True,
			include_about=True,
			include_pages=True,
			include_iframes=False,
			include_workers=False,
			include_chrome=False,
			include_chrome_extensions=False,
			include_chrome_error=False,
		)

		target_ids = [t['targetId'] for t in targets]
		if not target_ids and self.session.agent_focus_target_id:
			target_ids = [self.session.agent_focus_target_id]

		for target_id in target_ids:
			try:
				await self._inject_into_target(target_id, script)
			except Exception as exc:
				self.logger.debug(f'Failed to inject demo overlay into {target_id}: {exc}')

	async def _inject_into_target(self, target_id: str, script: str) -> None:
		session = await self.session.get_or_create_cdp_session(target_id=target_id, focus=False)
		await session.cdp_client.send.Runtime.evaluate(
			params={'expression': script, 'awaitPromise': False},
			session_id=session.session_id,
		)
