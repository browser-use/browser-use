import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import {
  cancelHuman,
  cancelLogin,
  connectEvents,
  continueHuman,
  deleteLocalData,
  finishLogin,
  getChats,
  getHistory,
  getLogins,
  getPreferences,
  getProviders,
  getState,
  openDataFolder,
  openDownloads,
  openLogs,
  openUrl,
  runTask,
  saveChat,
  saveHistoryEntry,
  savePreferences,
  startLogin,
  stopTask,
} from './api'
import { EXAMPLES } from './examples'
import { Icon } from './icons'

// Bump this when the palette changes so existing installs pick up the new
// default once, while still respecting later manual theme switches.
const THEME_REVISION = 'chatgpt-2026-11'

const DEFAULT_SETTINGS = {
  provider: 'DeepSeek',
  model: 'deepseek-v4-flash',
  headless: false,
  useVision: true,
  maxSteps: 50,
  searchEngine: 'auto',
}

const SEARCH_ENGINES = [
  { value: 'auto', label: '自动（优先 Bing）' },
  { value: 'bing_cn', label: 'Bing 中国' },
  { value: 'baidu', label: '百度' },
  { value: 'sogou', label: '搜狗' },
  { value: 'so', label: '360 搜索' },
  { value: 'bing', label: 'Bing 国际' },
  { value: 'google', label: 'Google' },
  { value: 'duckduckgo', label: 'DuckDuckGo' },
]

function searchEngineLabel(value) {
  return SEARCH_ENGINES.find((engine) => engine.value === value)?.label || '自动'
}

function platformLabel(site) {
  return { taobao: '淘宝', jd: '京东', xiaohongshu: '小红书', douyin: '抖音' }[site] || ''
}

function buildPreviousContext(followUp) {
  const links = [...new Set((followUp.sources || []).map((source) => source.url).filter(Boolean))]
  const files = (followUp.files || []).map((file) => file.display_name || file.name).filter(Boolean)
  return [
    `上一次任务：${followUp.task}`,
    `上一次结果：\n${(followUp.text || '').slice(0, 8000)}`,
    links.length ? `相关链接：\n${links.join('\n')}` : '',
    files.length ? `相关文件：${files.join(', ')}` : '',
  ]
    .filter(Boolean)
    .join('\n\n')
}

function formatTime(value) {
  return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function formatLoginDate(value) {
  if (!value) return ''
  return new Date(value * 1000).toLocaleDateString([], { month: '2-digit', day: '2-digit' })
}

async function copyToClipboard(text) {
  if (!text) return false
  const native = globalThis.pywebview?.api
  if (native?.copy) {
    try {
      if (await native.copy(text)) return true
    } catch {
      // Fall through to the browser clipboard.
    }
  }
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // Ignore and report failure below.
  }
  return false
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

function Sidebar({ history, activeId, onNew, onSelect, onSettings, onDownloads, onLogin, loginActive, loginSite, platforms, theme, setTheme, providers, settings }) {
  const groups = groupHistory(history)
  const providerInfo = providers.find((item) => item.name === settings.provider)
  const apiReady = Boolean(providerInfo?.has_key)
  const loggedInCount = (platforms || []).filter((item) => item.logged_in).length

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
        新建对话
        <span className="kbd">⌘N</span>
      </button>
      <button className="sidebar-action" onClick={onDownloads}>
        <Icon name="folder" size={16} />
        下载文件夹
        <span className="sidebar-action-hint">应用内</span>
      </button>
      <button className={`sidebar-action ${loginActive ? 'accent' : ''}`} onClick={onLogin}>
        <Icon name="login" size={16} />
        {loginActive ? `登录中：${platformLabel(loginSite)}` : '登录平台'}
        {loggedInCount > 0 && <span className="login-count">{loggedInCount} 已登录</span>}
      </button>

      <div className="sidebar-section">
        <div className="section-label">对话</div>
        {groups.length === 0 ? (
          <div className="empty-history">还没有对话</div>
        ) : (
          groups.map(([label, items]) => (
            <div key={label} className="history-group">
              <div className="history-label">{label}</div>
              {items.map((item) => (
                <button key={item.id} className={`history-item ${item.id === activeId ? 'active' : ''}`} onClick={() => onSelect(item)}>
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

function Home({ task, setTask, onRun, running, settings, onSettings, error, followUp, onClearFollowUp }) {
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

        {followUp && (
          <div className="followup-banner">
            <Icon name="sparkles" size={16} />
            <div>
              <strong>基于上一次结果继续</strong>
              <span>{followUp.task}</span>
            </div>
            <button className="icon-button" onClick={onClearFollowUp} title="清除上下文">
              <Icon name="x" size={15} />
            </button>
          </div>
        )}

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
            placeholder="例如：搜索 browser automation，总结前 3 个结果并附上链接"
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
              <span className="soft-chip">
                <Icon name="search" size={14} />
                {searchEngineLabel(settings.searchEngine)}
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
          <span className="examples-sub">点击示例快速填入任务</span>
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
              <span className="example-tag">{example.tag}</span>
            </button>
          ))}
        </div>

        <div className="home-footnote">
          <Icon name="key" size={14} />
          API Key 保存在本机私有配置（仅当前用户可读），不会写进代码或日志。
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
  const [openError, setOpenError] = useState('')
  const html = useMemo(() => {
    const rendered = marked.parse(text || '')
    return DOMPurify.sanitize(rendered)
  }, [text])

  async function handleClick(event) {
    const anchor = event.target.closest?.('a')
    if (!anchor) return
    const href = anchor.getAttribute('href') || ''
    if (!isLoggedInSource(href)) return
    event.preventDefault()
    setOpenError('')
    if (lacksXiaohongshuToken(href)) {
      setOpenError('该小红书链接缺少访问令牌 xsec_token，桌面端会显示 404。请重新运行任务，让来源返回带 xsec_token 的完整链接。')
      return
    }
    try {
      await openUrl(href)
    } catch (error) {
      setOpenError(error.message || '打开链接失败')
    }
  }

  return (
    <>
      <div className="markdown" onClick={handleClick} dangerouslySetInnerHTML={{ __html: html }} />
      {openError && <div className="markdown-open-error">{openError}</div>}
    </>
  )
}

const LOGGED_IN_SOURCE_HOSTS = ['xiaohongshu.com', 'xhslink.com', 'douyin.com', 'iesdouyin.com']

function isLoggedInSource(url) {
  try {
    const host = new URL(url).hostname.toLowerCase()
    return LOGGED_IN_SOURCE_HOSTS.some((domain) => host === domain || host.endsWith(`.${domain}`))
  } catch {
    return false
  }
}

function lacksXiaohongshuToken(url) {
  try {
    const parsed = new URL(url)
    const host = parsed.hostname.toLowerCase()
    const isXiaohongshu = host === 'xiaohongshu.com' || host.endsWith('.xiaohongshu.com')
    const isNote = parsed.pathname.startsWith('/explore/') || parsed.pathname.startsWith('/search_result/')
    return isXiaohongshu && isNote && !parsed.searchParams.get('xsec_token')
  } catch {
    return false
  }
}

function SourceCard({ source }) {
  const initial = (source.domain || '?').slice(0, 1).toUpperCase()
  const usesLoggedInBrowser = isLoggedInSource(source.url)
  const missingToken = usesLoggedInBrowser && lacksXiaohongshuToken(source.url)
  const [opening, setOpening] = useState(false)
  const [openError, setOpenError] = useState('')

  async function handleClick(event) {
    if (!usesLoggedInBrowser) return
    event.preventDefault()
    if (opening) return
    setOpenError('')
    if (missingToken) {
      setOpenError('该链接缺少 xsec_token，桌面端会显示 404。请重新运行任务，让来源返回完整链接。')
      return
    }
    setOpening(true)
    try {
      await openUrl(source.url)
    } catch (error) {
      setOpenError(error.message || '打开失败')
    } finally {
      setOpening(false)
    }
  }

  return (
    <a
      className="source-card"
      href={source.url}
      target="_blank"
      rel="noreferrer"
      onClick={handleClick}
      title={usesLoggedInBrowser ? '用 BrowserBuddy 已登录的浏览器打开' : source.url}
    >
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
        {usesLoggedInBrowser && (
          <div className="source-browser-hint">
            <Icon name="globe" size={11} />
            {opening ? '正在打开…' : '用已登录浏览器打开'}
          </div>
        )}
        {missingToken && (
          <div className="source-warning">此链接缺少访问令牌，可能无法直接播放</div>
        )}
        {openError && <div className="source-warning">{openError}</div>}
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
              <span>{image.display_name || image.name}</span>
            </a>
          ))}
        </div>
      )}
      {files.length > 0 && (
        <div className="file-list">
          {files.map((file) => (
            <a key={file.url} href={file.url} target="_blank" rel="noreferrer" className="file-chip">
              <Icon name={file.kind === 'pdf' ? 'file' : file.kind === 'csv' ? 'table' : 'file'} size={15} />
              <span>{file.display_name || file.name}</span>
              <Icon name="download" size={14} />
            </a>
          ))}
        </div>
      )}
    </div>
  )
}

function ResultPanel({ result, error, running, onCopy, onDownload, onNew, onDownloads, onContinue }) {
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
          <button className="icon-button" onClick={onDownloads} title="打开下载文件夹">
            <Icon name="folder" size={16} />
          </button>
          <button className="secondary-button" onClick={onContinue}>
            <Icon name="sparkles" size={15} />
            继续这个任务
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
  onDownloads,
  onContinue,
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
          onDownloads={onDownloads}
          onContinue={onContinue}
        />
      </div>
    </div>
  )
}

function loginOptionHint(status, fallback) {
  if (!status?.logged_in) return fallback
  return status.account ? `已登录：${status.account}` : '已登录，无需重复登录'
}

function LoginDialog({ open, active, busy, site, error, platforms, onClose, onStart, onFinish, onCancel }) {
  if (!open) return null
  const label = platformLabel(site)
  const statusFor = (key) => (platforms || []).find((item) => item.site === key)

  return (
    <div className="modal-overlay" onMouseDown={onClose}>
      <div className="modal-card login-modal" onMouseDown={(event) => event.stopPropagation()}>
        <div className="modal-head">
          <div>
            <div className="modal-title">登录平台</div>
            <div className="modal-sub">登录一次后，cookies 会保存在 BrowserBuddy 的独立浏览器 profile 中</div>
          </div>
          <button className="icon-button" onClick={onClose}>
            <Icon name="x" size={18} />
          </button>
        </div>

        {active ? (
          <div className="login-active">
            <div className="login-site-badge">
              <Icon name="login" size={18} />
              {label} 登录页已打开
            </div>
            <p>请在弹出的浏览器窗口中完成扫码或账号密码登录。检测到登录成功后会自动关闭登录窗口；扫码失败时直接关闭浏览器窗口即可。</p>
            <div className="login-note">不要在这里输入密码。只在你自己的浏览器窗口中登录。登录状态会保存在本机，下次不需要重复扫码。</div>
            <div className="modal-actions">
              <button className="run-button" onClick={onFinish}>
                <Icon name="check" size={15} />
                已完成登录
              </button>
              <button className="secondary-button" onClick={onCancel}>
                取消登录
              </button>
            </div>
          </div>
        ) : (
          <div>
            <p>选择一个平台。BrowserBuddy 会打开一个可见浏览器，用户自己完成登录，App 不保存账号密码。</p>
            {busy && (
              <div className="login-opening">
                <Icon name="loader" size={14} className="spin" />
                正在打开浏览器…
              </div>
            )}
            <div className="login-options">
              <button className="login-option" disabled={busy} onClick={() => onStart('taobao')}>
                <span className="login-option-icon">
                  <Icon name="tag" size={20} />
                </span>
                <strong>淘宝</strong>
                <small className={statusFor('taobao')?.logged_in ? 'ready' : ''}>
                  {loginOptionHint(statusFor('taobao'), '扫码或账号密码登录')}
                </small>
              </button>
              <button className="login-option" disabled={busy} onClick={() => onStart('jd')}>
                <span className="login-option-icon">
                  <Icon name="tag" size={20} />
                </span>
                <strong>京东</strong>
                <small className={statusFor('jd')?.logged_in ? 'ready' : ''}>
                  {loginOptionHint(statusFor('jd'), '扫码或账号密码登录')}
                </small>
              </button>
              <button className="login-option" disabled={busy} onClick={() => onStart('xiaohongshu')}>
                <span className="login-option-icon">
                  <Icon name="search" size={20} />
                </span>
                <strong>小红书</strong>
                <small className={statusFor('xiaohongshu')?.logged_in ? 'ready' : ''}>
                  {loginOptionHint(statusFor('xiaohongshu'), '扫码登录')}
                </small>
              </button>
              <button className="login-option" disabled={busy} onClick={() => onStart('douyin')}>
                <span className="login-option-icon">
                  <Icon name="play" size={20} />
                </span>
                <strong>抖音</strong>
                <small className={statusFor('douyin')?.logged_in ? 'ready' : ''}>
                  {loginOptionHint(statusFor('douyin'), '扫码登录')}
                </small>
              </button>
            </div>
            <p className="login-persist-note">登录一次后，App 会保存登录状态，重启后不需要重复扫码。</p>
          </div>
        )}

        {error && (
          <div className="inline-error">
            <Icon name="alert" size={15} />
            {error}
          </div>
        )}
      </div>
    </div>
  )
}

function HumanDialog({ request, onContinue, onCancel }) {
  if (!request) return null

  return (
    <div className="modal-overlay">
      <div className="modal-card human-modal">
        <div className="modal-head">
          <div>
            <div className="modal-title">需要你操作一下</div>
            <div className="modal-sub">任务已暂停，等你完成浏览器里的操作</div>
          </div>
          <span className="live-pill">PAUSED</span>
        </div>
        <div className="human-reason">
          <Icon name="alert" size={18} />
          <div>{request.reason || '网站要求登录或人工验证'}</div>
        </div>
        <p>
          请在弹出的浏览器窗口中完成扫码、登录或验证码。完成后点击“继续任务”。
          如果看不到浏览器窗口，请取消任务，并在设置中关闭“后台运行浏览器”后重试。
        </p>
        <div className="modal-actions">
          <button className="run-button" onClick={onContinue}>
            <Icon name="play" size={15} />
            继续任务
          </button>
          <button className="secondary-button" onClick={onCancel}>
            取消任务
          </button>
        </div>
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
  onDownloads,
  onOpenData,
  onDeleteData,
  platforms,
  onLoginSite,
}) {
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleteBusy, setDeleteBusy] = useState(false)
  const [deleteError, setDeleteError] = useState('')

  if (!open) return null
  const providerInfo = providers.find((item) => item.name === settings.provider)

  async function handleDeleteData() {
    setDeleteBusy(true)
    setDeleteError('')
    try {
      await onDeleteData()
      if (globalThis.pywebview?.api?.quit) {
        await globalThis.pywebview.api.quit()
      }
    } catch (event) {
      setDeleteError(event.message)
      setDeleteBusy(false)
    }
  }

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
          <label className="field">
            <span>搜索引擎</span>
            <select
              value={settings.searchEngine || 'auto'}
              onChange={(event) => setSettings((prev) => ({ ...prev, searchEngine: event.target.value }))}
            >
              {SEARCH_ENGINES.map((engine) => (
                <option key={engine.value} value={engine.value}>
                  {engine.label}
                </option>
              ))}
            </select>
          </label>
          <div className={`key-status ${providerInfo?.has_key ? 'ready' : ''}`}>
            <span className="api-dot" />
            {providerInfo?.has_key ? 'Key 已保存在本机' : '还没有保存这个提供商的 Key'}
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
          <div className="drawer-section-title">平台登录</div>
          {(platforms || []).map((item) => (
            <div className="platform-row" key={item.site}>
              <span className="platform-name">{item.label}</span>
              {item.logged_in ? (
                <>
                  <span className="platform-note">{formatLoginDate(item.last_login_at)}</span>
                  <span className="platform-status ready">已登录</span>
                </>
              ) : (
                <button className="soft-chip" onClick={() => onLoginSite(item.site)}>
                  登录
                </button>
              )}
            </div>
          ))}
          <p className="drawer-hint" style={{ marginTop: 10 }}>
            登录状态保存在本机，重启 App 后不需要重复扫码。
          </p>
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

        <div className="drawer-section">
          <div className="drawer-section-title">数据与卸载</div>
          <p className="drawer-hint">
            浏览器、任务记录、登录状态和下载文件都保存在一个文件夹内。把 BrowserBuddy 拖到废纸篓即可删除应用本身；下面的按钮会清除全部本地数据。
          </p>
          <button className="secondary-button wide" onClick={onOpenData}>
            <Icon name="folder" size={15} />
            打开数据文件夹
          </button>
          {confirmDelete ? (
            <div className="delete-confirm">
              <div>
                <Icon name="alert" size={15} />
                将删除任务记录、登录状态、下载文件、浏览器配置和设置，且无法恢复。
              </div>
              <div className="delete-actions">
                <button className="soft-chip" onClick={() => setConfirmDelete(false)} disabled={deleteBusy}>
                  取消
                </button>
                <button className="danger-button" onClick={handleDeleteData} disabled={deleteBusy}>
                  <Icon name="trash" size={14} />
                  {deleteBusy ? '正在删除…' : '确认彻底删除'}
                </button>
              </div>
            </div>
          ) : (
            <button
              className="secondary-button wide danger"
              onClick={() => setConfirmDelete(true)}
              style={{ marginTop: 8 }}
            >
              <Icon name="trash" size={15} />
              彻底删除本地数据
            </button>
          )}
          {deleteError ? <div className="inline-error">{deleteError}</div> : null}
        </div>

        <button className="secondary-button wide" onClick={onLogs}>
          <Icon name="terminal" size={15} />
          打开日志目录
        </button>
        <button className="secondary-button wide" onClick={onDownloads} style={{ marginTop: 8 }}>
          <Icon name="download" size={15} />
          打开下载文件夹
        </button>
      </div>
    </div>
  )
}


function newId() {
  return globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function buildThreadContext(messages) {
  const parts = []
  for (const message of messages || []) {
    if (message.role === 'user') {
      parts.push(`用户：${message.text}`)
    } else if (message.role === 'assistant' && message.result) {
      const links = [...new Set((message.result.sources || []).map((source) => source.url).filter(Boolean))]
      const files = (message.result.files || []).map((file) => file.display_name || file.name).filter(Boolean)
      parts.push(
        [
          `助手：${(message.result.text || '').slice(0, 6000)}`,
          links.length ? `链接：${links.join(', ')}` : '',
          files.length ? `文件：${files.join(', ')}` : '',
        ]
          .filter(Boolean)
          .join('\n'),
      )
    }
  }
  return parts.join('\n\n').slice(-16000)
}

function TraceList({ steps, running }) {
  if (!steps.length) {
    return running ? (
      <div className="activity-empty">
        <Icon name="loader" size={16} className="spin" />
        正在启动浏览器...
      </div>
    ) : null
  }

  return (
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
  )
}

function UserMessage({ message, onCopy }) {
  return (
    <div className="chat-message user">
      <div className="user-message-stack">
        <div className="user-bubble">{message.text}</div>
        <button className="user-copy-button" onClick={() => onCopy(message.text)} title="复制这条输入">
          <Icon name="copy" size={12} />
          复制
        </button>
      </div>
    </div>
  )
}

function AssistantMessage({ message, onCopy, onDownload, onDownloads }) {
  const result = message.result || {}
  return (
    <div className="chat-message assistant">
      <div className="assistant-avatar">
        <Icon name="sparkles" size={17} />
      </div>
      <div className="message-body">
        <div className="message-meta">
          <span>BrowserBuddy</span>
          {result.duration ? <span>{result.duration}s</span> : null}
          {result.steps ? <span>{result.steps} steps</span> : null}
          {result.success === false ? <span className="message-warning">部分完成</span> : null}
        </div>

        <Markdown text={result.text || ''} />

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

        {message.steps?.length > 0 && (
          <details className="message-trace">
            <summary>执行轨迹 · {message.steps.length} steps</summary>
            <TraceList steps={message.steps} running={false} />
          </details>
        )}

        <div className="message-actions">
          <button className="icon-button" onClick={() => onCopy(result.text || '')} title="复制结果">
            <Icon name="copy" size={15} />
          </button>
          <button className="icon-button" onClick={() => onDownload(result.text || '', message.ts)} title="导出 Markdown">
            <Icon name="download" size={15} />
          </button>
          <button className="icon-button" onClick={onDownloads} title="打开下载文件夹">
            <Icon name="folder" size={15} />
          </button>
        </div>
      </div>
    </div>
  )
}

function LiveMessage({ steps }) {
  return (
    <div className="chat-message assistant live">
      <div className="assistant-avatar">
        <Icon name="loader" size={17} className="spin" />
      </div>
      <div className="message-body">
        <div className="message-meta">
          <span>BrowserBuddy</span>
          <span className="live-label">正在执行</span>
        </div>
        <TraceList steps={steps} running />
      </div>
    </div>
  )
}

function ChatComposer({ value, onChange, onSend, onStop, running, disabled, settings, onSettings, placeholder }) {
  const canSend = value.trim() && !running && !disabled

  function send() {
    if (canSend) onSend(value)
  }

  return (
    <div className="chat-composer">
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
            event.preventDefault()
            send()
          }
        }}
        placeholder={placeholder}
        rows={3}
      />
      <div className="chat-composer-footer">
        <div className="composer-options">
          <button className="soft-chip" onClick={onSettings}>
            <Icon name="settings" size={14} />
            {settings.provider}
          </button>
          <span className="soft-chip">
            <Icon name={settings.useVision ? 'image' : 'terminal'} size={14} />
            {settings.useVision ? '视觉模式' : 'DOM 模式'}
          </span>
          <span className="soft-chip">
            <Icon name="search" size={14} />
            {searchEngineLabel(settings.searchEngine)}
          </span>
          {running && (
            <span className="soft-chip running-chip">
              <Icon name="loader" size={14} className="spin" />
              正在执行
            </span>
          )}
        </div>
        {running ? (
          <button className="stop-button composer-stop" onClick={onStop}>
            <Icon name="stop" size={14} />
            停止任务
          </button>
        ) : (
          <button className="run-button" onClick={send} disabled={!canSend}>
            <Icon name="play" size={15} />
            发送
            <span className="kbd">↵</span>
          </button>
        )}
      </div>
    </div>
  )
}

function WelcomeView({ draft, setDraft, onSend, running, disabled, settings, onSettings, error, loginActive, onExample }) {
  return (
    <div className="welcome-view">
      <div className="topbar topbar-home">
        <div className="topbar-title">新对话</div>
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

        {loginActive && (
          <div className="inline-error">
            <Icon name="login" size={15} />
            请先完成购物网站登录，或取消登录后再开始任务。
          </div>
        )}

        <ChatComposer
          value={draft}
          onChange={setDraft}
          onSend={onSend}
          running={running}
          disabled={disabled}
          settings={settings}
          onSettings={onSettings}
          placeholder="例如：搜索 browser automation，总结前 3 个结果并附上链接"
        />

        {error && (
          <div className="inline-error">
            <Icon name="alert" size={16} />
            {error}
          </div>
        )}

        <div className="examples-head">
          <span>试试这些</span>
          <span className="examples-sub">点击示例快速填入任务</span>
        </div>
        <div className="examples-grid">
          {EXAMPLES.map((example) => (
            <button key={example.id} className="example-card" onClick={() => onExample(example.task)}>
              <span className="example-icon">
                <Icon name={example.icon} size={18} />
              </span>
              <span className="example-body">
                <span className="example-title">{example.title}</span>
                <span className="example-subtitle">{example.subtitle}</span>
              </span>
              <span className="example-tag">{example.tag}</span>
            </button>
          ))}
        </div>

        <div className="home-footnote">
          <Icon name="key" size={14} />
          API Key 保存在本机私有配置（仅当前用户可读），不会写进代码或日志。
        </div>
      </div>
    </div>
  )
}

function ChatView({
  thread,
  running,
  liveSteps,
  error,
  draft,
  setDraft,
  onSend,
  onStop,
  onSettings,
  onLogs,
  onDownloads,
  onCopy,
  onDownload,
  disabled,
  settings,
}) {
  const bottomRef = useRef(null)
  const lastAssistant = [...(thread.messages || [])].reverse().find((message) => message.role === 'assistant')
  const lastResult = lastAssistant?.result

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [thread.messages?.length, liveSteps.length, running])

  return (
    <div className="chat-view">
      <div className="topbar">
        <div className="run-title" title={thread.title}>
          {thread.title || '对话'}
        </div>
        <div className="topbar-actions">
          <StatusPill running={running} result={lastResult} error={error} />
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

      <div className="chat-scroll">
        <div className="chat-thread">
          {(thread.messages || []).map((message, index) =>
            message.role === 'user' ? (
              <UserMessage key={`${message.ts}-${index}`} message={message} onCopy={onCopy} />
            ) : (
              <AssistantMessage
                key={`${message.ts}-${index}`}
                message={message}
                onCopy={onCopy}
                onDownload={onDownload}
                onDownloads={onDownloads}
              />
            ),
          )}
          {running && <LiveMessage steps={liveSteps} />}
          {error && (
            <div className="chat-error">
              <Icon name="alert" size={16} />
              <div>{error}</div>
            </div>
          )}
          <div ref={bottomRef} />
        </div>
      </div>

      <div className="chat-composer-wrap">
        <ChatComposer
          value={draft}
          onChange={setDraft}
          onSend={onSend}
          onStop={onStop}
          running={running}
          disabled={disabled}
          settings={settings}
          onSettings={onSettings}
          placeholder="继续提问，或输入新的任务…"
        />
      </div>
    </div>
  )
}

export default function App() {
  const [providers, setProviders] = useState([])
  const [settings, setSettings] = useState({ ...DEFAULT_SETTINGS })
  const [apiKey, setApiKey] = useState('')
  const [threads, setThreads] = useState([])
  const [activeThreadId, setActiveThreadId] = useState(null)
  const [draft, setDraft] = useState('')
  const [running, setRunning] = useState(false)
  const [liveSteps, setLiveSteps] = useState([])
  const [error, setError] = useState('')
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [theme, setTheme] = useState('light')
  const [loginOpen, setLoginOpen] = useState(false)
  const [loginActive, setLoginActive] = useState(false)
  const [loginBusy, setLoginBusy] = useState(false)
  const [loginSite, setLoginSite] = useState(null)
  const [loginError, setLoginError] = useState('')
  const [platforms, setPlatforms] = useState([])
  const [humanRequest, setHumanRequest] = useState(null)
  const [toast, setToast] = useState('')
  const liveStepsRef = useRef([])
  const pendingThreadRef = useRef(null)
  const runMetaRef = useRef(null)
  const prefsLoadedRef = useRef(false)
  const toastTimerRef = useRef(null)

  const showToast = useCallback((message) => {
    setToast(message)
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current)
    toastTimerRef.current = setTimeout(() => setToast(''), 2600)
  }, [])

  const refreshLogins = useCallback(async () => {
    try {
      const data = await getLogins()
      if (Array.isArray(data.platforms)) setPlatforms(data.platforms)
    } catch {
      // Login status is cosmetic; keep the last known values.
    }
  }, [])

  const activeThread = useMemo(
    () => threads.find((thread) => thread.id === activeThreadId) || null,
    [threads, activeThreadId],
  )

  const sidebarEntries = useMemo(
    () =>
      threads.map((thread) => {
        const lastAssistant = [...(thread.messages || [])].reverse().find((message) => message.role === 'assistant')
        return {
          id: thread.id,
          task: thread.title,
          ts: thread.updatedAt || thread.createdAt,
          provider: thread.provider || '',
          result: lastAssistant?.result,
        }
      }),
    [threads],
  )

  useEffect(() => {
    document.documentElement.dataset.theme = theme
  }, [theme])

  useEffect(() => {
    if (!prefsLoadedRef.current) return
    const timer = setTimeout(() => {
      savePreferences({ settings, theme, themeRevision: THEME_REVISION }).catch(() => {})
    }, 300)
    return () => clearTimeout(timer)
  }, [settings, theme])

  useEffect(() => {
    liveStepsRef.current = liveSteps
  }, [liveSteps])

  const appendAssistant = useCallback((result) => {
    const threadId = pendingThreadRef.current
    if (!threadId) return

    const meta = runMetaRef.current
    const assistant = {
      role: 'assistant',
      result,
      steps: liveStepsRef.current,
      ts: Date.now(),
      provider: meta?.provider,
      model: meta?.model,
    }

    setThreads((prev) => {
      const next = prev.map((thread) =>
        thread.id === threadId
          ? {
              ...thread,
              messages: [...(thread.messages || []), assistant],
              updatedAt: Date.now(),
            }
          : thread,
      )
      const updated = next.find((thread) => thread.id === threadId)
      if (updated) saveChat(updated).catch(() => {})
      return next
    })

    setRunning(false)
    setLiveSteps([])
    liveStepsRef.current = []
    pendingThreadRef.current = null
  }, [])

  const handleEvent = useCallback(
    (event) => {
      if (event.type === 'login_started') {
        setLoginActive(true)
        setLoginSite(event.site)
        setLoginOpen(true)
        setLoginError('')
        return
      }
      if (event.type === 'logins_updated') {
        if (Array.isArray(event.logins)) setPlatforms(event.logins)
        return
      }
      if (event.type === 'login_finished') {
        if (Array.isArray(event.logins)) setPlatforms(event.logins)
        setLoginActive(false)
        setLoginBusy(false)
        setLoginSite(null)
        if (event.success) {
          setLoginOpen(false)
          setLoginError('')
          showToast(`${event.label || platformLabel(event.site)}登录成功`)
        } else if (event.cancelled) {
          setLoginOpen(false)
          setLoginError('')
          showToast('已关闭登录窗口')
        } else {
          setLoginError(`还没有检测到${event.label || '该平台'}登录成功，请先在浏览器里完成扫码。`)
        }
        return
      }
      if (event.type === 'needs_human') {
        setHumanRequest({ reason: event.reason || '网站要求人工操作' })
        return
      }
      if (event.type === 'human_resolved') {
        setHumanRequest(null)
        return
      }
      if (event.type === 'step') {
        const next = liveStepsRef.current.some((item) => item.step === event.step)
          ? liveStepsRef.current.map((item) => (item.step === event.step ? event : item))
          : [...liveStepsRef.current, event]
        liveStepsRef.current = next
        setLiveSteps(next)
        return
      }
      if (event.type === 'result') {
        appendAssistant(event)
        return
      }
      if (event.type === 'stopped') {
        appendAssistant({
          text: '任务已被手动停止。',
          sources: [],
          files: [],
          images: [],
          success: false,
          duration: 0,
          steps: liveStepsRef.current.length,
        })
        return
      }
      if (event.type === 'error') {
        appendAssistant({
          text: `运行失败：${event.message}`,
          sources: [],
          files: [],
          images: [],
          success: false,
          duration: 0,
          steps: liveStepsRef.current.length,
        })
        return
      }
      if (event.type === 'run_finished') {
        setRunning(false)
      }
    },
    [appendAssistant, showToast],
  )

  useEffect(() => {
    const source = connectEvents(handleEvent)
    return () => source.close()
  }, [handleEvent])

  useEffect(() => {
    let cancelled = false

    async function bootstrap() {
      try {
        const [providerData, state, chatData, prefs, historyData] = await Promise.all([
          getProviders(),
          getState(),
          getChats(),
          getPreferences(),
          getHistory(),
        ])
        if (cancelled) return

        setProviders(providerData)
        if (prefs?.settings) setSettings((prev) => ({ ...prev, ...prefs.settings }))
        if (prefs?.themeRevision === THEME_REVISION && prefs?.theme) {
          setTheme(prefs.theme)
        } else {
          setTheme('light')
        }
        prefsLoadedRef.current = true

        let nextThreads = Array.isArray(chatData) ? chatData : []
        if (!nextThreads.length && Array.isArray(historyData) && historyData.length) {
          nextThreads = historyData.map((entry) => ({
            id: entry.id || newId(),
            title: entry.task || '历史任务',
            createdAt: entry.ts || Date.now(),
            updatedAt: entry.ts || Date.now(),
            provider: entry.provider || '',
            model: entry.model || '',
            messages: [
              { role: 'user', text: entry.task || '', ts: entry.ts || Date.now() },
              {
                role: 'assistant',
                result: entry.result || { text: '', sources: [], files: [], images: [], success: false, duration: 0, steps: 0 },
                steps: entry.steps || [],
                ts: entry.ts || Date.now(),
              },
            ],
          }))
          await Promise.all(nextThreads.map((thread) => saveChat(thread).catch(() => {})))
        }

        setThreads(nextThreads)

        if (state.running) {
          let thread = nextThreads.find((item) =>
            (item.messages || []).some((message) => message.role === 'user' && message.text === state.task),
          )
          if (!thread) {
            thread = {
              id: newId(),
              title: state.task || '正在执行的任务',
              createdAt: Date.now(),
              updatedAt: Date.now(),
              provider: state.provider,
              model: state.model,
              messages: [{ role: 'user', text: state.task || '', ts: Date.now() }],
            }
            nextThreads = [thread, ...nextThreads]
            setThreads(nextThreads)
            saveChat(thread).catch(() => {})
          }
          setActiveThreadId(thread.id)
          pendingThreadRef.current = thread.id
          runMetaRef.current = { task: state.task, provider: state.provider, model: state.model }
          setRunning(true)
          setLiveSteps(state.steps || [])
          liveStepsRef.current = state.steps || []
        }

        if (Array.isArray(state.logins)) setPlatforms(state.logins)
        if (state.login_active) {
          setLoginActive(true)
          setLoginSite(state.login_site)
          setLoginOpen(true)
        }
        if (state.human_active) {
          setHumanRequest({ reason: state.human_reason || '网站要求人工操作' })
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
      if (meta && event.key.toLowerCase() === 'n' && !running) {
        event.preventDefault()
        newChat()
      }
      if (event.key === 'Escape' && running) {
        handleStop()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  })

  function newChat() {
    if (running) return
    setActiveThreadId(null)
    setDraft('')
    setLiveSteps([])
    liveStepsRef.current = []
    setError('')
    pendingThreadRef.current = null
  }

  function selectThread(threadId) {
    if (running) return
    setActiveThreadId(threadId)
    setDraft('')
    setLiveSteps([])
    liveStepsRef.current = []
    setError('')
    pendingThreadRef.current = null
  }

  async function sendMessage(text) {
    const clean = (text || '').trim()
    if (!clean || running) return
    if (loginActive) {
      setError('请先完成购物网站登录，或取消登录后再发送。')
      return
    }

    const now = Date.now()
    const current = activeThread
    const previousContext = buildThreadContext(current?.messages || [])
    const threadId = current?.id || newId()
    const userMessage = { role: 'user', text: clean, ts: now }
    const updatedThread = current
      ? {
          ...current,
          title: current.messages?.length ? current.title : clean.slice(0, 40),
          messages: [...(current.messages || []), userMessage],
          updatedAt: now,
          provider: settings.provider,
          model: settings.model,
        }
      : {
          id: threadId,
          title: clean.slice(0, 40),
          createdAt: now,
          updatedAt: now,
          provider: settings.provider,
          model: settings.model,
          messages: [userMessage],
        }

    setThreads((prev) =>
      current ? prev.map((thread) => (thread.id === threadId ? updatedThread : thread)) : [updatedThread, ...prev],
    )
    setActiveThreadId(threadId)
    setDraft('')
    setError('')
    setRunning(true)
    setLiveSteps([])
    liveStepsRef.current = []
    pendingThreadRef.current = threadId
    runMetaRef.current = { task: clean, provider: settings.provider, model: settings.model }
    saveChat(updatedThread).catch(() => {})

    try {
      await runTask({
        task: clean,
        provider: settings.provider,
        model: settings.model,
        api_key: apiKey || null,
        headless: settings.headless,
        max_steps: settings.maxSteps,
        use_vision: settings.useVision,
        search_engine: settings.searchEngine || 'auto',
        previous_context: previousContext || null,
      })
      if (apiKey) {
        setProviders((prev) =>
          prev.map((provider) =>
            provider.name === settings.provider ? { ...provider, has_key: true } : provider,
          ),
        )
        setApiKey('')
      }
    } catch (e) {
      setError(e.message)
      setRunning(false)
      pendingThreadRef.current = null
    }
  }

  async function handleStop() {
    try {
      await stopTask()
    } catch (e) {
      setError(e.message)
    }
  }

  async function handleCopy(text) {
    const copied = await copyToClipboard(text)
    setToast(copied ? '已复制' : '复制失败')
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current)
    toastTimerRef.current = setTimeout(() => setToast(''), 1500)
  }

  function handleDownload(text, ts) {
    if (!text) return
    const blob = new Blob([text], { type: 'text/markdown;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = `browserbuddy-${new Date(ts || Date.now()).toISOString().slice(0, 19).replace(/[:T]/g, '-')}.md`
    link.click()
    URL.revokeObjectURL(url)
  }

  async function handleLoginStart(site) {
    setLoginError('')
    setLoginBusy(true)
    try {
      const result = await startLogin(site)
      if (Array.isArray(result.logins)) setPlatforms(result.logins)
      setLoginActive(true)
      setLoginSite(result.site || site)
      setLoginOpen(true)
    } catch (e) {
      setLoginError(e.message)
    } finally {
      setLoginBusy(false)
    }
  }

  async function handleLoginFinish() {
    try {
      // The backend validates the cookies and publishes login_finished; the
      // SSE handler decides whether to close the dialog or show an error.
      await finishLogin()
    } catch (e) {
      setLoginError(e.message)
    }
  }

  async function handleLoginCancel() {
    try {
      // Closing the login window is always allowed; the SSE handler reports it.
      await cancelLogin()
    } catch (e) {
      setLoginError(e.message)
    }
  }

  async function handleHumanContinue() {
    try {
      await continueHuman()
      setHumanRequest(null)
    } catch (e) {
      setError(e.message)
    }
  }

  async function handleHumanCancel() {
    try {
      await cancelHuman()
      setHumanRequest(null)
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <div className="app-shell">
      <Sidebar
        history={sidebarEntries}
        activeId={activeThreadId}
        onNew={newChat}
        onSelect={(entry) => selectThread(entry.id)}
        onSettings={() => setSettingsOpen(true)}
        onDownloads={openDownloads}
        onLogin={() => {
          setLoginError('')
          refreshLogins()
          setLoginOpen(true)
        }}
        loginActive={loginActive}
        loginSite={loginSite}
        platforms={platforms}
        theme={theme}
        setTheme={setTheme}
        providers={providers}
        settings={settings}
      />
      <main className="main">
        {activeThread ? (
          <ChatView
            thread={activeThread}
            running={running}
            liveSteps={liveSteps}
            error={error}
            draft={draft}
            setDraft={setDraft}
            onSend={sendMessage}
            onStop={handleStop}
            onSettings={() => setSettingsOpen(true)}
            onLogs={openLogs}
            onDownloads={openDownloads}
            onCopy={handleCopy}
            onDownload={handleDownload}
            disabled={loginActive}
            settings={settings}
          />
        ) : (
          <WelcomeView
            draft={draft}
            setDraft={setDraft}
            onSend={sendMessage}
            running={running}
            disabled={loginActive}
            settings={settings}
            onSettings={() => setSettingsOpen(true)}
            error={error}
            loginActive={loginActive}
            onExample={(task) => setDraft(task)}
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
        onDownloads={openDownloads}
        onOpenData={openDataFolder}
        onDeleteData={deleteLocalData}
        platforms={platforms}
        onLoginSite={(site) => {
          setSettingsOpen(false)
          setLoginError('')
          setLoginOpen(true)
          handleLoginStart(site)
        }}
      />
      <LoginDialog
        open={loginOpen}
        active={loginActive}
        busy={loginBusy}
        site={loginSite}
        error={loginError}
        platforms={platforms}
        onClose={() => setLoginOpen(false)}
        onStart={handleLoginStart}
        onFinish={handleLoginFinish}
        onCancel={handleLoginCancel}
      />
      <HumanDialog
        request={humanRequest}
        onContinue={handleHumanContinue}
        onCancel={handleHumanCancel}
      />
      {toast && <div className="app-toast">{toast}</div>}
    </div>
  )
}
