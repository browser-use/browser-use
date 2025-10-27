'use client'

import { useState, useEffect, useRef } from 'react'
import { Send, Mic, MicOff, Monitor, Pause, Play, Square } from 'lucide-react'
import MessageBubble from './MessageBubble'
import ActionTimeline from './ActionTimeline'
import { useWebSocket } from '@/hooks/useWebSocket'
import { useSpeechRecognition } from '@/hooks/useSpeechRecognition'

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

interface ChatInterfaceProps {
  sessionId: string | null
  onSessionCreated: (sessionId: string) => void
  onToggleBrowserPreview: () => void
}

export default function ChatInterface({ 
  sessionId, 
  onSessionCreated,
  onToggleBrowserPreview 
}: ChatInterfaceProps) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isLoading, setIsLoading] = useState(false)
  const [isPaused, setIsPaused] = useState(false)
  const [currentStep, setCurrentStep] = useState(0)
  const [maxSteps, setMaxSteps] = useState(10)
  
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const { isListening, transcript, startListening, stopListening, isSupported } = useSpeechRecognition()
  const { sendMessage, agentStatus } = useWebSocket(sessionId, (event) => {
    handleWebSocketEvent(event)
  })

  // Auto-scroll para última mensagem
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Atualizar input com transcrição de voz
  useEffect(() => {
    if (transcript) {
      setInput(transcript)
    }
  }, [transcript])

  const handleWebSocketEvent = (event: any) => {
    switch (event.type) {
      case 'agent_started':
        setIsLoading(true)
        setMaxSteps(event.max_steps)
        addSystemMessage(`Agente iniciado: ${event.task}`)
        break

      case 'step':
        setCurrentStep(event.step_number)
        addAssistantMessage({
          content: event.thought || `Executando: ${event.action}`,
          screenshot: event.screenshot,
          action: event.action,
          thought: event.thought,
          stepNumber: event.step_number,
        })
        break

      case 'done':
        setIsLoading(false)
        addSystemMessage(`Tarefa concluída! ${event.total_steps} steps executados.`)
        if (event.final_result) {
          addAssistantMessage({ content: event.final_result })
        }
        break

      case 'error':
        setIsLoading(false)
        addSystemMessage(`Erro: ${event.error}`, 'error')
        break

      case 'control':
        if (event.action === 'paused') {
          setIsPaused(true)
          addSystemMessage('Agente pausado')
        } else if (event.action === 'resumed') {
          setIsPaused(false)
          addSystemMessage('Agente resumido')
        } else if (event.action === 'stopped') {
          setIsLoading(false)
          addSystemMessage('Agente parado')
        }
        break
    }
  }

  const addUserMessage = (content: string) => {
    const message: Message = {
      id: Date.now().toString(),
      type: 'user',
      content,
      timestamp: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, message])
  }

  const addAssistantMessage = (data: {
    content: string
    screenshot?: string
    action?: string
    thought?: string
    stepNumber?: number
  }) => {
    const message: Message = {
      id: Date.now().toString(),
      type: 'assistant',
      ...data,
      timestamp: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, message])
  }

  const addSystemMessage = (content: string, variant: 'info' | 'error' = 'info') => {
    const message: Message = {
      id: Date.now().toString(),
      type: 'system',
      content,
      timestamp: new Date().toISOString(),
    }
    setMessages((prev) => [...prev, message])
  }

  const handleSendMessage = async () => {
    if (!input.trim()) return

    const messageText = input.trim()
    setInput('')
    addUserMessage(messageText)
    setIsLoading(true)

    try {
      const response = await fetch('http://localhost:8000/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          message: messageText,
          session_id: sessionId,
          llm_provider: 'openai',
          llm_model: 'gpt-4o-mini',
          max_steps: 10,
        }),
      })

      const data = await response.json()
      
      if (!sessionId) {
        onSessionCreated(data.session_id)
      }
    } catch (error) {
      console.error('Erro ao enviar mensagem:', error)
      addSystemMessage('Erro ao enviar mensagem', 'error')
      setIsLoading(false)
    }
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSendMessage()
    }
  }

  const handleToggleMic = () => {
    if (isListening) {
      stopListening()
    } else {
      startListening()
    }
  }

  const handleControlAgent = async (action: 'pause' | 'resume' | 'stop') => {
    if (!sessionId) return

    try {
      await fetch(`http://localhost:8000/api/session/${sessionId}/control`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action }),
      })
    } catch (error) {
      console.error(`Erro ao ${action} agente:`, error)
    }
  }

  return (
    <div className="flex-1 flex flex-col h-full">
      {/* Header */}
      <div className="bg-white dark:bg-chatgpt-gray-800 border-b border-chatgpt-gray-200 dark:border-chatgpt-gray-700 px-6 py-4">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold">Browser-Use Agent</h1>
            {isLoading && (
              <p className="text-sm text-chatgpt-gray-200">
                Executando step {currentStep} de {maxSteps}...
              </p>
            )}
          </div>
          
          <div className="flex items-center gap-2">
            {/* Controles do agente */}
            {isLoading && (
              <>
                {isPaused ? (
                  <button
                    onClick={() => handleControlAgent('resume')}
                    className="p-2 rounded-lg hover:bg-chatgpt-gray-100 dark:hover:bg-chatgpt-gray-700"
                    title="Resumir"
                  >
                    <Play size={20} />
                  </button>
                ) : (
                  <button
                    onClick={() => handleControlAgent('pause')}
                    className="p-2 rounded-lg hover:bg-chatgpt-gray-100 dark:hover:bg-chatgpt-gray-700"
                    title="Pausar"
                  >
                    <Pause size={20} />
                  </button>
                )}
                <button
                  onClick={() => handleControlAgent('stop')}
                  className="p-2 rounded-lg hover:bg-chatgpt-gray-100 dark:hover:bg-chatgpt-gray-700 text-red-500"
                  title="Parar"
                >
                  <Square size={20} />
                </button>
              </>
            )}
            
            <button
              onClick={onToggleBrowserPreview}
              className="p-2 rounded-lg hover:bg-chatgpt-gray-100 dark:hover:bg-chatgpt-gray-700"
              title="Toggle Browser Preview"
            >
              <Monitor size={20} />
            </button>
          </div>
        </div>
      </div>

      {/* Messages Area */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        {messages.length === 0 ? (
          <div className="h-full flex items-center justify-center">
            <div className="text-center max-w-md">
              <h2 className="text-2xl font-semibold mb-4">
                Como posso ajudar você hoje?
              </h2>
              <p className="text-chatgpt-gray-200 mb-6">
                Digite uma tarefa de automação web ou use o microfone para falar
              </p>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div className="p-4 rounded-lg bg-chatgpt-gray-100 dark:bg-chatgpt-gray-800 cursor-pointer hover:bg-chatgpt-gray-200 dark:hover:bg-chatgpt-gray-700">
                  Buscar informações no Google
                </div>
                <div className="p-4 rounded-lg bg-chatgpt-gray-100 dark:bg-chatgpt-gray-800 cursor-pointer hover:bg-chatgpt-gray-200 dark:hover:bg-chatgpt-gray-700">
                  Preencher formulário
                </div>
                <div className="p-4 rounded-lg bg-chatgpt-gray-100 dark:bg-chatgpt-gray-800 cursor-pointer hover:bg-chatgpt-gray-200 dark:hover:bg-chatgpt-gray-700">
                  Extrair dados de site
                </div>
                <div className="p-4 rounded-lg bg-chatgpt-gray-100 dark:bg-chatgpt-gray-800 cursor-pointer hover:bg-chatgpt-gray-200 dark:hover:bg-chatgpt-gray-700">
                  Adicionar item ao carrinho
                </div>
              </div>
            </div>
          </div>
        ) : (
          <div className="max-w-4xl mx-auto">
            {messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}
            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Input Area */}
      <div className="bg-white dark:bg-chatgpt-gray-800 border-t border-chatgpt-gray-200 dark:border-chatgpt-gray-700 px-6 py-4">
        <div className="max-w-4xl mx-auto">
          <div className="relative flex items-end gap-2">
            <div className="flex-1 relative">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyPress={handleKeyPress}
                placeholder="Digite sua mensagem..."
                rows={1}
                className="w-full px-4 py-3 pr-12 rounded-xl border border-chatgpt-gray-200 dark:border-chatgpt-gray-700 bg-white dark:bg-chatgpt-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none"
                style={{ minHeight: '52px', maxHeight: '200px' }}
              />
              
              {/* Mic Button */}
              {isSupported && (
                <button
                  onClick={handleToggleMic}
                  className={`absolute right-3 top-1/2 -translate-y-1/2 p-2 rounded-lg transition-colors ${
                    isListening 
                      ? 'text-red-500 bg-red-50 dark:bg-red-900/20' 
                      : 'text-chatgpt-gray-200 hover:bg-chatgpt-gray-100 dark:hover:bg-chatgpt-gray-700'
                  }`}
                  title={isListening ? 'Parar gravação' : 'Gravar áudio'}
                >
                  {isListening ? <MicOff size={20} /> : <Mic size={20} />}
                </button>
              )}
            </div>

            <button
              onClick={handleSendMessage}
              disabled={!input.trim() || isLoading}
              className="p-3 rounded-xl bg-blue-500 text-white hover:bg-blue-600 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <Send size={20} />
            </button>
          </div>
          
          {isListening && (
            <div className="mt-2 text-sm text-red-500 flex items-center gap-2">
              <span className="animate-pulse-subtle">🔴</span>
              Gravando...
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
