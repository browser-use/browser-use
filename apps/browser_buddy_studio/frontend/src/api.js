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
