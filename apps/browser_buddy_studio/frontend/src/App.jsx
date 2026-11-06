import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import {
  connectEvents,
  getHistory,
  getPreferences,
  getProviders,
  getState,
  openLogs,
  runTask,
  saveHistoryEntry,
  savePreferences,
  stopTask,
} from './api'
import { EXAMPLES } from './examples'
import { Icon } from './icons'

const DEFAULT_SETTINGS = {
  provider: 'DeepSeek',
  model: 'deepseek-v4-flash',
  headless: false,
  useVision: true,
  maxSteps: 50,
}

function formatTime(value) {
  return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function dayLabel(value) {
  const date = new Date(value)
  const now = new Date()
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const target = new Date(date.getFullYear(), date.getMonth(), date.getDate())
  const diff = Math.round((today - target) / 86400000)
  if (diff <= 0) return '今天'
  if (diff === 1) return '昨天'
  return '更早'
}

function groupHistory(history) {
  const groups = new Map()
  for (const item of history) {
    const label = dayLabel(item.ts)
    if (!groups.has(label)) groups.set(label, [])
    groups.get(label).push(item)
  }
  return [...groups.entries()]
}

function StatusPill({ running, result, error }) {
  if (running) {
    return (
      <span className="status-pill running">
        <span className="status-dot" />
        执行中
      </span>
    )
  }
  if (error) {
    return (
      <span className="status-pill error">
        <Icon name="alert" size={14} />
        失败
      </span>
    )
  }
  if (result) {
    return (
      <span className="status-pill success">
        <Icon name="check" size={14} />
        已完成
      </span>
    )
  }
  return null
}

function Sidebar({ history, onNew, onSelect, onSettings, theme, setTheme, providers, settings }) {
  const groups = groupHistory(history)
  const providerInfo = providers.find((item) => item.name === settings.provider)
  const apiReady = Boolean(providerInfo?.has_key)

  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">
          <Icon name="sparkles" size={20} />
        </div>
        <div>
          <div className="brand-name">BrowserBuddy</div>
          <div className="brand-sub">Browser agent for Mac</div>
        </div>
      </div>

      <button className="new-task" onClick={onNew}>
        <Icon name="plus" size={17} />
        新建任务
        <span className="kbd">⌘N</span>
      </button>

      <div className="sidebar-section">
        <div className="section-label">最近任务</div>
        {groups.length === 0 ? (
          <div className="empty-history">还没有任务记录</div>
        ) : (
          groups.map(([label, items]) => (
            <div key={label} className="history-group">
              <div className="history-label">{label}</div>
              {items.map((item) => (
                <button key={item.id} className="history-item" onClick={() => onSelect(item)}>
                  <span className={`history-icon ${item.result?.success === false ? 'failed' : ''}`}>
                    {item.result?.success === false ? <Icon name="x" size={12} /> : <Icon name="check" size={12} />}
                  </span>
                  <span className="history-body">
                    <span className="history-task">{item.task}</span>
                    <span className="history-meta">
                      {item.provider} · {formatTime(item.ts)}
                    </span>
                  </span>
                </button>
              ))}
            </div>
          ))
        )}
      </div>

      <div className="sidebar-footer">
        <div className={`api-status ${apiReady ? 'ready' : ''}`}>
          <span className="api-dot" />
          {apiReady ? 'API 已连接' : '需要 API Key'}
        </div>
        <div className="footer-actions">
          <button className="icon-button" onClick={onSettings} title="设置">
            <Icon name="settings" size={18} />
          </button>
          <button
            className="icon-button"
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            title="切换主题"
          >
            <Icon name={theme === 'dark' ? 'sun' : 'moon'} size={18} />
          </button>
        </div>
      </div>
    </aside>
  )
}

function Home({ task, setTask, onRun, running, settings, onSettings, error }) {
  const run = () => {
    if (!running) onRun()
  }

  return (
    <div className="home-view">
      <div className="topbar topbar-home">
        <div className="topbar-title">新任务</div>
        <button className="model-chip" onClick={onSettings}>
          <span className="model-dot" />
          {settings.provider} · {settings.model}
          <Icon name="chevronDown" size={14} />
        </button>
      </div>

      <div className="hero">
        <div className="hero-badge">
          <Icon name="sparkles" size={14} />
          Browser agent
        </div>
        <h1>今天想让浏览器做什么？</h1>
        <p>描述一个目标，BrowserBuddy 会规划步骤、操作浏览器，并把结果和来源整理给你。</p>

        <div className="composer-card">
          <textarea
            value={task}
            onChange={(event) => setTask(event.target.value)}
            onKeyDown={(event) => {
              if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
                event.preventDefault()
                run()
              }
            }}
            placeholder="例如：打开 Google 搜索 browser automation，总结前 3 个结果并附上链接"
            rows={5}
            autoFocus
          />
          <div className="composer-footer">
            <div className="composer-options">
              <button className="soft-chip" onClick={onSettings}>
                <Icon name="settings" size={14} />
                {settings.headless ? '后台运行' : '显示浏览器'}
              </button>
              <span className="soft-chip">
                <Icon name={settings.useVision ? 'image' : 'terminal'} size={14} />
                {settings.useVision ? '视觉模式' : 'DOM 模式'}
              </span>
            </div>
            <button className="run-button" onClick={run} disabled={running || !task.trim()}>
              <Icon name={running ? 'loader' : 'play'} size={16} className={running ? 'spin' : ''} />
              {running ? '执行中' : '开始执行'}
              <span className="kbd">⌘↵</span>
            </button>
          </div>
        </div>

        {error && (
          <div className="inline-error">
            <Icon name="alert" size={16} />
            {error}
          </div>
        )}

        <div className="examples-head">
          <span>试试这些</span>
          <span className="examples-sub">中英文示例都可以直接运行</span>
        </div>
        <div className="examples-grid">
          {EXAMPLES.map((example) => (
            <button
              key={example.id}
              className="example-card"
              onClick={() => setTask(example.task)}
            >
              <span className="example-icon">
                <Icon name={example.icon} size={18} />
              </span>
              <span className="example-body">
                <span className="example-title">{example.title}</span>
                <span className="example-subtitle">{example.subtitle}</span>
              </span>
              <span className={`example-tag ${example.tag === 'EN' ? 'en' : ''}`}>{example.tag}</span>
            </button>
          ))}
        </div>

        <div className="home-footnote">
          <Icon name="key" size={14} />
          API Key 保存在 macOS Keychain，不会写进代码或日志。
        </div>
      </div>
    </div>
  )
}

function Timeline({ steps, running, result, error }) {
  return (
    <section className="activity-panel">
      <div className="panel-head">
        <div>
          <div className="panel-title">执行轨迹</div>
          <div className="panel-sub">{steps.length} 个步骤</div>
        </div>
        {running && <span className="live-pill">LIVE</span>}
      </div>

      {steps.length === 0 && running && (
        <div className="activity-empty">
          <Icon name="loader" size={18} className="spin" />
          正在启动浏览器...
        </div>
      )}

      {steps.length === 0 && !running && !result && !error && (
        <div className="activity-empty">还没有执行步骤</div>
      )}

      <div className="timeline">
        {steps.map((step, index) => {
          const isLast = index === steps.length - 1
          return (
            <div key={`${step.step}-${index}`} className="timeline-item">
              <div className={`timeline-marker ${running && isLast ? 'active' : 'done'}`}>
                {running && isLast ? <Icon name="loader" size={12} className="spin" /> : <Icon name="check" size={12} />}
              </div>
              <div className="timeline-content">
                <div className="timeline-head">
                  <span className="timeline-step">Step {step.step}</span>
                  <span className="timeline-actions">
                    {(step.actions || []).map((action) => (
                      <span key={action} className="action-chip">
                        {action}
                      </span>
                    ))}
                  </span>
                </div>
                <div className="timeline-goal">{step.goal || '执行中'}</div>
              </div>
            </div>
          )
        })}
      </div>

      {error && (
        <div className="error-card">
          <Icon name="alert" size={16} />
          <div>
            <div className="error-title">任务失败</div>
            <div className="error-message">{error}</div>
          </div>
        </div>
      )}
    </section>
  )
}

function Markdown({ text }) {
  const html = useMemo(() => {
    const rendered = marked.parse(text || '')
    return DOMPurify.sanitize(rendered)
  }, [text])
  return <div className="markdown" dangerouslySetInnerHTML={{ __html: html }} />
}

function SourceCard({ source }) {
  const initial = (source.domain || '?').slice(0, 1).toUpperCase()
  return (
    <a className="source-card" href={source.url} target="_blank" rel="noreferrer">
      <div className="source-image">
        <span className="source-placeholder">{initial}</span>
        {source.image && (
          <img
            src={source.image}
            alt=""
            loading="lazy"
            referrerPolicy="no-referrer"
            onError={(event) => {
              event.currentTarget.style.display = 'none'
            }}
          />
        )}
      </div>
      <div className="source-body">
        <div className="source-title">{source.title}</div>
        <div className="source-description">{source.description || source.url}</div>
        <div className="source-domain">{source.domain}</div>
      </div>
      <Icon name="external" size={14} className="source-arrow" />
    </a>
  )
}

function Attachments({ files, images }) {
  if (!files.length && !images.length) return null
  return (
    <div className="attachments-block">
      <div className="result-section-head">附件与图片</div>
      {images.length > 0 && (
        <div className="image-grid">
          {images.map((image) => (
            <a key={image.url} href={image.url} target="_blank" rel="noreferrer" className="image-tile">
              <img src={image.url} alt={image.name} loading="lazy" />
              <span>{image.name}</span>
            </a>
          ))}
        </div>
      )}
      {files.length > 0 && (
        <div className="file-list">
          {files.map((file) => (
            <a key={file.url} href={file.url} target="_blank" rel="noreferrer" className="file-chip">
              <Icon name={file.kind === 'pdf' ? 'file' : file.kind === 'csv' ? 'table' : 'file'} size={15} />
              <span>{file.name}</span>
              <Icon name="download" size={14} />
            </a>
          ))}
        </div>
      )}
    </div>
  )
}

function ResultPanel({ result, error, running, onCopy, onDownload, onNew }) {
  if (error && !result) {
    return (
      <section className="result-panel">
        <div className="result-empty">
          <div className="empty-icon error">
            <Icon name="alert" size={24} />
          </div>
          <h2>任务没有完成</h2>
          <p>{error}</p>
          <button className="secondary-button" onClick={onNew}>
            新建任务
          </button>
        </div>
      </section>
    )
  }

  if (!result) {
    return (
      <section className="result-panel">
        <div className="result-empty">
          <div className="empty-icon">
            <Icon name={running ? 'loader' : 'sparkles'} size={26} className={running ? 'spin' : ''} />
          </div>
          <h2>{running ? '正在执行任务' : '等待任务'}</h2>
          <p>{running ? '左侧会实时显示浏览器执行步骤，完成后结果显示在这里。' : '从左侧新建一个任务，或者使用示例开始。'}</p>
        </div>
      </section>
    )
  }

  return (
    <section className="result-panel">
      <div className="result-head">
        <div>
          <div className="result-eyebrow">
            <Icon name="check" size={14} />
            执行结果
          </div>
          <h2>{result.success === false ? '任务部分完成' : '任务完成'}</h2>
          <div className="result-meta">
            <span>
              <Icon name="clock" size={13} />
              {result.duration ? `${result.duration}s` : '刚刚'}
            </span>
            <span>{result.steps || 0} steps</span>
          </div>
        </div>
        <div className="result-actions">
          <button className="icon-button" onClick={onCopy} title="复制结果">
            <Icon name="copy" size={16} />
          </button>
          <button className="icon-button" onClick={onDownload} title="导出 Markdown">
            <Icon name="download" size={16} />
          </button>
          <button className="secondary-button" onClick={onNew}>
            新建任务
          </button>
        </div>
      </div>

      <Markdown text={result.text} />

      {result.sources?.length > 0 && (
        <div className="sources-block">
          <div className="result-section-head">来源</div>
          <div className="sources-grid">
            {result.sources.map((source) => (
              <SourceCard key={source.url} source={source} />
            ))}
          </div>
        </div>
      )}

      <Attachments files={result.files || []} images={result.images || []} />
    </section>
  )
}

function RunView({
  task,
  steps,
  running,
  result,
  error,
  onBack,
  onStop,
  onNew,
  onCopy,
  onDownload,
  onSettings,
  onLogs,
}) {
  return (
    <div className="run-view">
      <div className="topbar">
        <button className="back-button" onClick={onBack}>
          <Icon name="arrowLeft" size={16} />
          返回
        </button>
        <div className="run-title" title={task}>
          {task || '任务'}
        </div>
        <div className="topbar-actions">
          <StatusPill running={running} result={result} error={error} />
          {running ? (
            <button className="stop-button" onClick={onStop}>
              <Icon name="stop" size={14} />
              停止
            </button>
          ) : (
            <button className="icon-button" onClick={onLogs} title="打开日志">
              <Icon name="terminal" size={17} />
            </button>
          )}
          <button className="icon-button" onClick={onSettings} title="设置">
            <Icon name="settings" size={17} />
          </button>
        </div>
      </div>

      <div className="run-layout">
        <Timeline steps={steps} running={running} result={result} error={error} />
        <ResultPanel
          result={result}
          error={error}
          running={running}
          onCopy={onCopy}
          onDownload={onDownload}
          onNew={onNew}
        />
      </div>
    </div>
  )
}

function SettingsDrawer({
  open,
  onClose,
  providers,
  settings,
  setSettings,
  apiKey,
  setApiKey,
  theme,
  setTheme,
  onLogs,
}) {
  if (!open) return null
  const providerInfo = providers.find((item) => item.name === settings.provider)

  return (
    <div className="drawer-overlay" onMouseDown={onClose}>
      <div className="drawer" onMouseDown={(event) => event.stopPropagation()}>
        <div className="drawer-head">
          <div>
            <div className="drawer-title">设置</div>
            <div className="drawer-sub">模型、浏览器和输出</div>
          </div>
          <button className="icon-button" onClick={onClose}>
            <Icon name="x" size={18} />
          </button>
        </div>

        <div className="drawer-section">
          <div className="drawer-section-title">模型</div>
          <label className="field">
            <span>模型提供商</span>
            <select
              value={settings.provider}
              onChange={(event) => {
                const provider = event.target.value
                const info = providers.find((item) => item.name === provider)
                setSettings((prev) => ({
                  ...prev,
                  provider,
                  model: info?.default_model || prev.model,
                }))
                setApiKey('')
              }}
            >
              {providers.map((provider) => (
                <option key={provider.name} value={provider.name}>
                  {provider.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            <span>模型名称</span>
            <input
              value={settings.model}
              onChange={(event) => setSettings((prev) => ({ ...prev, model: event.target.value }))}
              placeholder={providerInfo?.default_model || 'model-name'}
            />
          </label>
          <label className="field">
            <span>API Key</span>
            <input
              type="password"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              placeholder={providerInfo?.has_key ? '已保存，留空即可' : providerInfo?.placeholder || 'sk-...'}
            />
          </label>
          <div className={`key-status ${providerInfo?.has_key ? 'ready' : ''}`}>
            <span className="api-dot" />
            {providerInfo?.has_key ? 'Key 已保存到 macOS Keychain' : '还没有保存这个提供商的 Key'}
          </div>
        </div>

        <div className="drawer-section">
          <div className="drawer-section-title">浏览器</div>
          <label className="toggle-row">
            <span>
              <strong>后台运行浏览器</strong>
              <small>不显示 Chrome 窗口</small>
            </span>
            <input
              type="checkbox"
              checked={settings.headless}
              onChange={(event) => setSettings((prev) => ({ ...prev, headless: event.target.checked }))}
            />
          </label>
          <label className="toggle-row">
            <span>
              <strong>使用网页截图</strong>
              <small>需要模型支持视觉</small>
            </span>
            <input
              type="checkbox"
              checked={settings.useVision}
              onChange={(event) => setSettings((prev) => ({ ...prev, useVision: event.target.checked }))}
            />
          </label>
          <label className="field">
            <span>最大步数：{settings.maxSteps}</span>
            <input
              type="range"
              min="10"
              max="100"
              step="5"
              value={settings.maxSteps}
              onChange={(event) => setSettings((prev) => ({ ...prev, maxSteps: Number(event.target.value) }))}
            />
          </label>
        </div>

        <div className="drawer-section">
          <div className="drawer-section-title">外观</div>
          <div className="theme-switch">
            <button className={theme === 'light' ? 'active' : ''} onClick={() => setTheme('light')}>
              <Icon name="sun" size={15} />
              浅色
            </button>
            <button className={theme === 'dark' ? 'active' : ''} onClick={() => setTheme('dark')}>
              <Icon name="moon" size={15} />
              深色
            </button>
          </div>
        </div>

        <button className="secondary-button wide" onClick={onLogs}>
          <Icon name="terminal" size={15} />
          打开日志目录
        </button>
      </div>
    </div>
  )
}

export default function App() {
  const [providers, setProviders] = useState([])
  const [settings, setSettings] = useState({ ...DEFAULT_SETTINGS })
  const [apiKey, setApiKey] = useState('')
  const [task, setTask] = useState('')
  const [view, setView] = useState('home')
  const [running, setRunning] = useState(false)
  const [steps, setSteps] = useState([])
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')
  const [history, setHistory] = useState([])
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [theme, setTheme] = useState('dark')
  const runMetaRef = useRef(null)
  const stepsRef = useRef([])
  const prefsLoadedRef = useRef(false)

  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  useEffect(() => {
    if (!prefsLoadedRef.current) return
    const timer = setTimeout(() => {
      savePreferences({ settings, theme }).catch(() => {})
    }, 300)
    return () => clearTimeout(timer)
  }, [settings, theme])

  useEffect(() => {
    stepsRef.current = steps
  }, [steps])

  const addHistory = useCallback((entry) => {
    setHistory((prev) => {
      const next = [entry, ...prev.filter((item) => item.id !== entry.id)]
      return next.slice(0, 20)
    })
    saveHistoryEntry(entry).catch(() => {})
  }, [])

  const handleEvent = useCallback(
    (event) => {
      if (event.type === 'run_started') {
        runMetaRef.current = {
          task: event.task,
          provider: event.provider,
          model: event.model,
        }
        setView('run')
        setRunning(true)
        stepsRef.current = []
        setSteps([])
        setResult(null)
        setError('')
        setTask(event.task)
        return
      }
      if (event.type === 'step') {
        const next = stepsRef.current.some((item) => item.step === event.step)
          ? stepsRef.current.map((item) => (item.step === event.step ? event : item))
          : [...stepsRef.current, event]
        stepsRef.current = next
        setSteps(next)
        return
      }
      if (event.type === 'result') {
        setResult(event)
        setRunning(false)
        const meta = runMetaRef.current
        if (meta) {
          addHistory({
            id: `${Date.now()}`,
            task: meta.task,
            provider: meta.provider,
            model: meta.model,
            ts: Date.now(),
            result: event,
            steps: stepsRef.current,
          })
        }
        return
      }
      if (event.type === 'error') {
        setError(event.message)
        setRunning(false)
        return
      }
      if (event.type === 'run_finished') {
        setRunning(false)
      }
    },
    [addHistory],
  )

  useEffect(() => {
    const source = connectEvents(handleEvent)
    return () => source.close()
  }, [handleEvent])

  useEffect(() => {
    let cancelled = false
    async function bootstrap() {
      try {
        const [providerData, state, historyData, prefs] = await Promise.all([
          getProviders(),
          getState(),
          getHistory(),
          getPreferences(),
        ])
        if (cancelled) return
        setProviders(providerData)
        setHistory(Array.isArray(historyData) ? historyData : [])
        if (prefs?.settings) setSettings((prev) => ({ ...prev, ...prefs.settings }))
        if (prefs?.theme) setTheme(prefs.theme)
        prefsLoadedRef.current = true
        if (state.running || state.result || state.error) {
          setView('run')
          setRunning(Boolean(state.running))
          stepsRef.current = state.steps || []
          setSteps(state.steps || [])
          setResult(state.result)
          setError(state.error || '')
          setTask(state.task || '')
          runMetaRef.current = {
            task: state.task,
            provider: state.provider,
            model: state.model,
          }
        }
      } catch (e) {
        setError(e.message)
      } finally {
        prefsLoadedRef.current = true
      }
    }
    bootstrap()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    function onKeyDown(event) {
      const meta = event.metaKey || event.ctrlKey
      if (meta && event.key.toLowerCase() === 'n') {
        event.preventDefault()
        newTask()
      }
      if (meta && event.key === 'Enter' && view === 'home' && !running) {
        event.preventDefault()
        handleRun()
      }
      if (event.key === 'Escape' && running) {
        handleStop()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  })

  function newTask() {
    setView('home')
    setTask('')
    stepsRef.current = []
    setSteps([])
    setResult(null)
    setError('')
    setRunning(false)
  }

  async function handleRun() {
    if (!task.trim() || running) {
      if (!task.trim()) setError('请先输入任务。')
      return
    }
    setError('')
    setView('run')
    setRunning(true)
    stepsRef.current = []
    setSteps([])
    setResult(null)
    runMetaRef.current = {
      task,
      provider: settings.provider,
      model: settings.model,
    }
    try {
      await runTask({
        task,
        provider: settings.provider,
        model: settings.model,
        api_key: apiKey || null,
        headless: settings.headless,
        max_steps: settings.maxSteps,
        use_vision: settings.useVision,
      })
    } catch (e) {
      setError(e.message)
      setRunning(false)
    }
  }

  async function handleStop() {
    try {
      await stopTask()
    } catch (e) {
      setError(e.message)
    }
  }

  function handleSelectHistory(entry) {
    setView('run')
    setTask(entry.task)
    setSteps(entry.steps || [])
    setResult(entry.result)
    setError('')
    setRunning(false)
    runMetaRef.current = {
      task: entry.task,
      provider: entry.provider,
      model: entry.model,
    }
  }

  function handleCopy() {
    if (result?.text) navigator.clipboard?.writeText(result.text)
  }

  function handleDownload() {
    if (!result?.text) return
    const blob = new Blob([result.text], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = 'browserbuddy-result.md'
    link.click()
    URL.revokeObjectURL(url)
  }

  return (
    <div className="app-shell">
      <Sidebar
        history={history}
        onNew={newTask}
        onSelect={handleSelectHistory}
        onSettings={() => setSettingsOpen(true)}
        theme={theme}
        setTheme={setTheme}
        providers={providers}
        settings={settings}
      />
      <main className="main">
        {view === 'home' ? (
          <Home
            task={task}
            setTask={setTask}
            onRun={handleRun}
            running={running}
            settings={settings}
            onSettings={() => setSettingsOpen(true)}
            error={error}
          />
        ) : (
          <RunView
            task={task}
            steps={steps}
            running={running}
            result={result}
            error={error}
            onBack={() => setView('home')}
            onStop={handleStop}
            onNew={newTask}
            onCopy={handleCopy}
            onDownload={handleDownload}
            onSettings={() => setSettingsOpen(true)}
            onLogs={openLogs}
          />
        )}
      </main>
      <SettingsDrawer
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        providers={providers}
        settings={settings}
        setSettings={setSettings}
        apiKey={apiKey}
        setApiKey={setApiKey}
        theme={theme}
        setTheme={setTheme}
        onLogs={openLogs}
      />
    </div>
  )
}
