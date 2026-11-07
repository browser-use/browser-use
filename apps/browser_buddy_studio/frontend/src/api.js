async function jsonFetch(url, options = {}) {
  const response = await fetch(url, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.detail || data.error || `Request failed (${response.status})`)
  }
  return data
}

export function getProviders() {
  return jsonFetch('/api/providers')
}

export function getState() {
  return jsonFetch('/api/state')
}

export function getHistory() {
  return jsonFetch('/api/history')
}

export function getChats() {
  return jsonFetch('/api/chats')
}

export function saveChat(thread) {
  return jsonFetch('/api/chats', {
    method: 'POST',
    body: JSON.stringify(thread),
  })
}

export function saveHistoryEntry(entry) {
  return jsonFetch('/api/history', {
    method: 'POST',
    body: JSON.stringify(entry),
  })
}

export function getPreferences() {
  return jsonFetch('/api/preferences')
}

export function savePreferences(preferences) {
  return jsonFetch('/api/preferences', {
    method: 'POST',
    body: JSON.stringify(preferences),
  })
}

export function runTask(payload) {
  return jsonFetch('/api/run', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function stopTask() {
  return jsonFetch('/api/stop', { method: 'POST' })
}

export function openLogs() {
  return jsonFetch('/api/open-logs', { method: 'POST' })
}

export function openDownloads() {
  return jsonFetch('/api/open-downloads', { method: 'POST' })
}

export function startLogin(site) {
  return jsonFetch('/api/login/start', {
    method: 'POST',
    body: JSON.stringify({ site }),
  })
}

export function finishLogin() {
  return jsonFetch('/api/login/finish', { method: 'POST' })
}

export function cancelLogin() {
  return jsonFetch('/api/login/cancel', { method: 'POST' })
}

export function continueHuman() {
  return jsonFetch('/api/human/continue', { method: 'POST' })
}

export function cancelHuman() {
  return jsonFetch('/api/human/cancel', { method: 'POST' })
}

export function connectEvents(onEvent) {
  const source = new EventSource('/api/events')
  source.onmessage = (event) => {
    try {
      onEvent(JSON.parse(event.data))
    } catch {
      // Ignore malformed events.
    }
  }
  return source
}
