'use client'

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { User, Bot, Info } from 'lucide-react'

interface Message {
  id: string
  type: 'user' | 'assistant' | 'system'
  content: string
  timestamp: string
  screenshot?: string
  action?: string
  thought?: string
  stepNumber?: number
}

interface MessageBubbleProps {
  message: Message
}

export default function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.type === 'user'
  const isSystem = message.type === 'system'

  if (isSystem) {
    return (
      <div className="flex justify-center my-4">
        <div className="flex items-center gap-2 px-4 py-2 rounded-full bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400 text-sm">
          <Info size={16} />
          <span>{message.content}</span>
        </div>
      </div>
    )
  }

  return (
    <div className={`flex gap-4 mb-6 ${isUser ? 'flex-row-reverse' : ''}`}>
      {/* Avatar */}
      <div className={`flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center ${
        isUser 
          ? 'bg-blue-500 text-white' 
          : 'bg-green-500 text-white'
      }`}>
        {isUser ? <User size={18} /> : <Bot size={18} />}
      </div>

      {/* Content */}
      <div className={`flex-1 ${isUser ? 'flex justify-end' : ''}`}>
        <div className={`max-w-3xl ${isUser ? 'text-right' : ''}`}>
          {/* Message Content */}
          <div className={`rounded-2xl px-4 py-3 ${
            isUser 
              ? 'bg-blue-500 text-white' 
              : 'bg-chatgpt-gray-100 dark:bg-chatgpt-gray-800'
          }`}>
            <ReactMarkdown 
              remarkPlugins={[remarkGfm]}
              className="markdown-content"
            >
              {message.content}
            </ReactMarkdown>
          </div>

          {/* Step Info (apenas para assistant) */}
          {!isUser && message.stepNumber && (
            <div className="mt-2 text-xs text-chatgpt-gray-200 space-y-1">
              <div>Step {message.stepNumber}</div>
              {message.action && (
                <div className="flex items-center gap-2">
                  <span className="font-medium">Ação:</span>
                  <span className="px-2 py-0.5 rounded bg-chatgpt-gray-200 dark:bg-chatgpt-gray-700">
                    {message.action}
                  </span>
                </div>
              )}
            </div>
          )}

          {/* Screenshot (apenas para assistant) */}
          {!isUser && message.screenshot && (
            <div className="mt-3">
              <img 
                src={`data:image/png;base64,${message.screenshot}`}
                alt={`Screenshot - Step ${message.stepNumber}`}
                className="rounded-lg border border-chatgpt-gray-200 dark:border-chatgpt-gray-700 max-w-full h-auto cursor-pointer hover:opacity-90 transition-opacity"
                onClick={() => {
                  // Abrir screenshot em nova aba
                  const win = window.open()
                  if (win) {
                    win.document.write(`<img src="data:image/png;base64,${message.screenshot}" />`)
                  }
                }}
              />
            </div>
          )}

          {/* Timestamp */}
          <div className="mt-1 text-xs text-chatgpt-gray-200 opacity-70">
            {new Date(message.timestamp).toLocaleTimeString('pt-BR', {
              hour: '2-digit',
              minute: '2-digit'
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
