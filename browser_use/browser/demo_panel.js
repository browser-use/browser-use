(function () {
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
    button.textContent = '📝';
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

  function renderMarkdown(text) {
    if (!text) return '<p></p>';

    // Store code blocks before processing
    const codeBlocks = [];
    let html = text.replace(/```[\s\S]*?```/g, (match) => {
      const id = `__CODE_BLOCK_${codeBlocks.length}__`;
      codeBlocks.push(match);
      return id;
    });

    // Store inline code
    const inlineCodes = [];
    html = html.replace(/`[^`\n]+`/g, (match) => {
      const id = `__INLINE_CODE_${inlineCodes.length}__`;
      inlineCodes.push(match);
      return id;
    });

    // Escape HTML
    html = html
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');

    // Process by lines
    const lines = html.split('\n');
    const result = [];
    let inList = false;

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];

      // Headers (store content for later inline formatting)
      const h3Match = line.match(/^###\s+(.+)$/);
      if (h3Match) {
        if (inList) {
          result.push('</ul>');
          inList = false;
        }
        result.push({ type: 'h3', content: h3Match[1] });
        continue;
      }
      const h2Match = line.match(/^##\s+(.+)$/);
      if (h2Match) {
        if (inList) {
          result.push('</ul>');
          inList = false;
        }
        result.push({ type: 'h2', content: h2Match[1] });
        continue;
      }
      const h1Match = line.match(/^#\s+(.+)$/);
      if (h1Match) {
        if (inList) {
          result.push('</ul>');
          inList = false;
        }
        result.push({ type: 'h1', content: h1Match[1] });
        continue;
      }

      // Lists (store content for later inline formatting)
      const listMatch = line.match(/^[\*\-\+]\s+(.+)$/);
      if (listMatch) {
        if (!inList) {
          result.push('<ul>');
          inList = true;
        }
        result.push({ type: 'li', content: listMatch[1] });
        continue;
      }

      // Empty line
      if (!line.trim()) {
        if (inList) {
          result.push('</ul>');
          inList = false;
        }
        continue;
      }

      // Regular line
      if (inList) {
        result.push('</ul>');
        inList = false;
      }
      result.push(line);
    }

    if (inList) {
      result.push('</ul>');
    }

    // Helper to apply inline formatting
    function formatInline(text) {
      let formatted = text;

      // Links (before other formatting to avoid conflicts)
      formatted = formatted.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');

      // Bold (before italic)
      formatted = formatted.replace(/\*\*([^\*]+?)\*\*/g, '<strong>$1</strong>');
      formatted = formatted.replace(/__([^_]+?)__/g, '<strong>$1</strong>');

      // Italic (single asterisk/underscore, not part of bold or code)
      formatted = formatted.replace(/(^|[^*])\*([^*\n]+?)\*([^*]|$)/g, '$1<em>$2</em>$3');
      formatted = formatted.replace(/(^|[^_])_([^_\n]+?)_([^_]|$)/g, '$1<em>$2</em>$3');

      // Restore inline code (after all formatting to preserve code content)
      inlineCodes.forEach((code, i) => {
        const codeText = code.replace(/`/g, '').trim();
        const escaped = codeText
          .replace(/&/g, '&amp;')
          .replace(/</g, '&lt;')
          .replace(/>/g, '&gt;');
        formatted = formatted.replace(`__INLINE_CODE_${i}__`, `<code>${escaped}</code>`);
      });

      return formatted;
    }

    // Convert result array to HTML, applying inline formatting
    const htmlParts = [];
    let currentPara = [];

    for (const item of result) {
      if (typeof item === 'object') {
        // Close any open paragraph
        if (currentPara.length > 0) {
          htmlParts.push(`<p>${formatInline(currentPara.join(' '))}</p>`);
          currentPara = [];
        }
        // Format header/list item content
        const formatted = formatInline(item.content);
        if (item.type === 'h1') {
          htmlParts.push(`<h1>${formatted}</h1>`);
        } else if (item.type === 'h2') {
          htmlParts.push(`<h2>${formatted}</h2>`);
        } else if (item.type === 'h3') {
          htmlParts.push(`<h3>${formatted}</h3>`);
        } else if (item.type === 'li') {
          htmlParts.push(`<li>${formatted}</li>`);
        }
      } else if (item === '<ul>' || item === '</ul>') {
        // Close any open paragraph
        if (currentPara.length > 0) {
          htmlParts.push(`<p>${formatInline(currentPara.join(' '))}</p>`);
          currentPara = [];
        }
        htmlParts.push(item);
      } else {
        // Regular text line
        currentPara.push(item);
      }
    }

    // Close any remaining paragraph
    if (currentPara.length > 0) {
      htmlParts.push(`<p>${formatInline(currentPara.join('<br>'))}</p>`);
    }

    html = htmlParts.join('');

    // Restore code blocks (after all other processing)
    codeBlocks.forEach((block, i) => {
      const code = block.replace(/```\w*\n?/g, '').replace(/```/g, '').trim();
      const escaped = code
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
      html = html.replace(`__CODE_BLOCK_${i}__`, `<pre><code>${escaped}</code></pre>`);
    });

    return html || '<p></p>';
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
    const messageHtml = renderMarkdown(messageText);
    const message = document.createElement('div');
    message.className = 'browser-use-markdown-content';
    message.innerHTML = messageHtml;
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
