'use client'

import { useState, useEffect } from 'react'
import { X, ExternalLink, Maximize2 } from 'lucide-react'

interface BrowserPreviewProps {
  sessionId: string | null
  onClose: () => void
}

export default function BrowserPreview({ sessionId, onClose }: BrowserPreviewProps) {
  const [currentUrl, setCurrentUrl] = useState<string>('')
  const [currentTitle, setCurrentTitle] = useState<string>('')
  const [screenshot, setScreenshot] = useState<string | null>(null)
  const [stepNumber, setStepNumber] = useState<number>(0)

  useEffect(() => {
    if (!sessionId) return

    // Conectar ao WebSocket para receber atualizações
    const ws = new WebSocket(`ws://localhost:8000/ws/${sessionId}`)

    ws.onmessage = (event) => {
      const data = JSON.parse(event.data)
      
      if (data.type === 'step') {
        setCurrentUrl(data.url || '')
        setCurrentTitle(data.title || '')
        setScreenshot(data.screenshot || null)
        setStepNumber(data.step_number || 0)
      }
    }

    return () => {
      ws.close()
    }
  }, [sessionId])

  const openInNewTab = () => {
    if (currentUrl) {
      window.open(currentUrl, '_blank')
    }
  }

  return (
    <div className="w-96 bg-white dark:bg-chatgpt-gray-800 border-l border-chatgpt-gray-200 dark:border-chatgpt-gray-700 flex flex-col h-full">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-chatgpt-gray-200 dark:border-chatgpt-gray-700">
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-sm">Browser Preview</h3>
          {stepNumber > 0 && (
            <p className="text-xs text-chatgpt-gray-200">Step {stepNumber}</p>
          )}
        </div>
        <button
          onClick={onClose}
          className="p-1.5 rounded hover:bg-chatgpt-gray-100 dark:hover:bg-chatgpt-gray-700"
        >
          <X size={18} />
        </button>
      </div>

      {/* URL Bar */}
      {currentUrl && (
        <div className="px-4 py-2 border-b border-chatgpt-gray-200 dark:border-chatgpt-gray-700">
          <div className="flex items-center gap-2">
            <div className="flex-1 min-w-0 px-3 py-1.5 rounded bg-chatgpt-gray-100 dark:bg-chatgpt-gray-900 text-sm truncate">
              {currentUrl}
            </div>
            <button
              onClick={openInNewTab}
              className="p-1.5 rounded hover:bg-chatgpt-gray-100 dark:hover:bg-chatgpt-gray-700"
              title="Abrir em nova aba"
            >
              <ExternalLink size={16} />
            </button>
          </div>
          {currentTitle && (
            <div className="mt-1 text-xs text-chatgpt-gray-200 truncate">
              {currentTitle}
            </div>
          )}
        </div>
      )}

      {/* Screenshot */}
      <div className="flex-1 overflow-y-auto p-4">
        {screenshot ? (
          <div className="relative group">
            <img
              src={`data:image/png;base64,${screenshot}`}
              alt="Browser Screenshot"
              className="w-full h-auto rounded-lg border border-chatgpt-gray-200 dark:border-chatgpt-gray-700"
            />
            <button
              onClick={() => {
                const win = window.open()
                if (win) {
                  win.document.write(`
                    <html>
                      <head><title>Screenshot - Step ${stepNumber}</title></head>
                      <body style="margin:0;background:#000;display:flex;align-items:center;justify-content:center;">
                        <img src="data:image/png;base64,${screenshot}" style="max-width:100%;max-height:100vh;" />
                      </body>
                    </html>
                  `)
                }
              }}
              className="absolute top-2 right-2 p-2 rounded bg-black/50 text-white opacity-0 group-hover:opacity-100 transition-opacity"
              title="Ampliar"
            >
              <Maximize2 size={16} />
            </button>
          </div>
        ) : (
          <div className="h-full flex items-center justify-center text-chatgpt-gray-200">
            <div className="text-center">
              <Monitor size={48} className="mx-auto mb-4 opacity-50" />
              <p className="text-sm">Aguardando navegação...</p>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function Monitor({ size, className }: { size: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
    >
      <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
      <line x1="8" y1="21" x2="16" y2="21" />
      <line x1="12" y1="17" x2="12" y2="21" />
    </svg>
  )
}
