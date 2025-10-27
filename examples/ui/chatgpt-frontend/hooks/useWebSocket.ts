import { useEffect, useRef, useState } from 'react'

interface UseWebSocketReturn {
  sendMessage: (message: any) => void
  agentStatus: 'idle' | 'running' | 'paused' | 'stopped'
}

export function useWebSocket(
  sessionId: string | null,
  onMessage: (data: any) => void
): UseWebSocketReturn {
  const wsRef = useRef<WebSocket | null>(null)
  const [agentStatus, setAgentStatus] = useState<'idle' | 'running' | 'paused' | 'stopped'>('idle')

  useEffect(() => {
    if (!sessionId || sessionId.startsWith('new-')) {
      return
    }

    // Conectar ao WebSocket
    const ws = new WebSocket(`ws://localhost:8000/ws/${sessionId}`)

    ws.onopen = () => {
      console.log('WebSocket conectado')
      setAgentStatus('idle')
    }

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        console.log('WebSocket message:', data)

        // Atualizar status baseado no tipo de evento
        if (data.type === 'agent_started') {
          setAgentStatus('running')
        } else if (data.type === 'control') {
          if (data.action === 'paused') setAgentStatus('paused')
          if (data.action === 'resumed') setAgentStatus('running')
          if (data.action === 'stopped') setAgentStatus('stopped')
        } else if (data.type === 'done') {
          setAgentStatus('idle')
        }

        onMessage(data)
      } catch (error) {
        console.error('Erro ao processar mensagem WebSocket:', error)
      }
    }

    ws.onerror = (error) => {
      console.error('Erro no WebSocket:', error)
    }

    ws.onclose = () => {
      console.log('WebSocket desconectado')
      setAgentStatus('idle')
    }

    wsRef.current = ws

    return () => {
      ws.close()
    }
  }, [sessionId, onMessage])

  const sendMessage = (message: any) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(message))
    }
  }

  return {
    sendMessage,
    agentStatus,
  }
}
