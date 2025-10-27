'use client'

import { useState, useEffect } from 'react'
import { MessageSquare, Plus, Trash2 } from 'lucide-react'

interface Session {
  id: string
  title: string
  createdAt: string
}

interface SidebarProps {
  currentSessionId: string | null
  onSessionSelect: (sessionId: string) => void
}

export default function Sidebar({ currentSessionId, onSessionSelect }: SidebarProps) {
  const [sessions, setSessions] = useState<Session[]>([])

  const createNewChat = () => {
    // Criar nova sessão (será criada de fato quando enviar primeira mensagem)
    const newSessionId = `new-${Date.now()}`
    onSessionSelect(newSessionId)
  }

  const deleteSession = (sessionId: string, e: React.MouseEvent) => {
    e.stopPropagation()
    setSessions(sessions.filter(s => s.id !== sessionId))
    if (currentSessionId === sessionId) {
      onSessionSelect('')
    }
  }

  return (
    <div className="w-64 bg-chatgpt-gray-900 text-white flex flex-col h-full">
      {/* Header */}
      <div className="p-3 border-b border-chatgpt-gray-700">
        <button
          onClick={createNewChat}
          className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg border border-chatgpt-gray-700 hover:bg-chatgpt-gray-800 transition-colors"
        >
          <Plus size={18} />
          <span className="text-sm font-medium">Novo Chat</span>
        </button>
      </div>

      {/* Sessions List */}
      <div className="flex-1 overflow-y-auto p-2">
        {sessions.length === 0 ? (
          <div className="text-center text-chatgpt-gray-200 text-sm mt-8">
            <MessageSquare size={32} className="mx-auto mb-2 opacity-50" />
            <p className="opacity-70">Nenhuma conversa ainda</p>
            <p className="opacity-50 text-xs mt-1">Inicie um novo chat</p>
          </div>
        ) : (
          sessions.map((session) => (
            <div
              key={session.id}
              onClick={() => onSessionSelect(session.id)}
              className={`
                group flex items-center justify-between gap-2 px-3 py-2.5 rounded-lg mb-1 cursor-pointer
                ${currentSessionId === session.id 
                  ? 'bg-chatgpt-gray-800' 
                  : 'hover:bg-chatgpt-gray-800'
                }
              `}
            >
              <div className="flex items-center gap-3 flex-1 min-w-0">
                <MessageSquare size={16} className="flex-shrink-0 opacity-70" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm truncate">{session.title}</p>
                  <p className="text-xs opacity-50 truncate">{session.createdAt}</p>
                </div>
              </div>
              <button
                onClick={(e) => deleteSession(session.id, e)}
                className="opacity-0 group-hover:opacity-100 p-1 hover:text-red-400 transition-opacity"
              >
                <Trash2 size={14} />
              </button>
            </div>
          ))
        )}
      </div>

      {/* Footer */}
      <div className="p-3 border-t border-chatgpt-gray-700">
        <div className="text-xs text-chatgpt-gray-200 opacity-70 text-center">
          Browser-Use Chat v1.0
        </div>
      </div>
    </div>
  )
}
