import { Component, StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './styles.css'

class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  render() {
    if (this.state.error) {
      return (
        <div
          style={{
            minHeight: '100vh',
            display: 'grid',
            placeItems: 'center',
            padding: '32px',
            background: '#0b0f17',
            color: '#e8edf5',
            fontFamily: '-apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif',
          }}
        >
          <div style={{ maxWidth: '560px', width: '100%' }}>
            <h1 style={{ margin: 0, fontSize: '22px' }}>界面出现错误</h1>
            <p style={{ color: '#8b98ad', lineHeight: 1.6 }}>
              请重新加载应用。如果问题持续存在，请打开日志目录并反馈错误信息。
            </p>
            <pre
              style={{
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
                padding: '12px',
                borderRadius: '10px',
                background: '#111827',
                border: '1px solid #1f2a3d',
                color: '#f87171',
                fontSize: '12px',
                maxHeight: '260px',
                overflow: 'auto',
              }}
            >
              {String(this.state.error?.stack || this.state.error)}
            </pre>
            <button
              onClick={() => window.location.reload()}
              style={{
                marginTop: '14px',
                padding: '9px 14px',
                borderRadius: '9px',
                border: 0,
                background: '#2563eb',
                color: '#fff',
                fontWeight: 650,
                cursor: 'pointer',
              }}
            >
              重新加载
            </button>
          </div>
        </div>
      )
    }
    return this.props.children
  }
}

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>,
)
