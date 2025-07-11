import React, { useState, useEffect, useRef } from 'react'
import { Send, Mic, MicOff, Sparkles, Search, Brain, Zap, User, Bot } from 'lucide-react'

interface Message {
  type: 'user' | 'agent' | 'system' | 'error'
  content: string
  timestamp: string
  id?: string
}

function App() {
  const [messages, setMessages] = useState<Message[]>([])
  const [inputMessage, setInputMessage] = useState('')
  const [isConnected, setIsConnected] = useState(false)
  const [isListening, setIsListening] = useState(false)
  const [isThinking, setIsThinking] = useState(false)
  const [ws, setWs] = useState<WebSocket | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const recognitionRef = useRef<any>(null)

  // Connexion WebSocket
  useEffect(() => {
    const connectWebSocket = () => {
      const websocket = new WebSocket('ws://localhost:8000/ws/chat')
      
      websocket.onopen = () => {
        setIsConnected(true)
        console.log('🟢 WebSocket connecté')
      }
      
      websocket.onmessage = (event) => {
        const data = JSON.parse(event.data)
        setMessages(prev => [...prev, { ...data, id: Date.now().toString() }])
        setIsThinking(false)
      }
      
      websocket.onclose = () => {
        setIsConnected(false)
        setTimeout(connectWebSocket, 3000)
      }
      
      setWs(websocket)
    }

    connectWebSocket()
  }, [])

  // Scroll automatique
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  // Reconnaissance vocale
  useEffect(() => {
    const windowAny = window as any
    if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
      const SpeechRecognition = windowAny.webkitSpeechRecognition || windowAny.SpeechRecognition
      recognitionRef.current = new SpeechRecognition()
      recognitionRef.current.lang = 'fr-FR'
      recognitionRef.current.continuous = false

      recognitionRef.current.onresult = (event: any) => {
        const transcript = event.results[0][0].transcript
        setInputMessage(transcript)
        setIsListening(false)
      }

      recognitionRef.current.onerror = () => setIsListening(false)
      recognitionRef.current.onend = () => setIsListening(false)
    }
  }, [])

  const sendMessage = () => {
    if (!inputMessage.trim() || !ws || !isConnected) return

    const userMessage: Message = {
      type: 'user',
      content: inputMessage,
      timestamp: new Date().toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }),
      id: `user-${Date.now()}`
    }

    setMessages(prev => [...prev, userMessage])
    setIsThinking(true)
    
    ws.send(JSON.stringify({
      type: 'user_message',
      content: inputMessage
    }))

    setInputMessage('')
  }

  const toggleListening = () => {
    if (!recognitionRef.current) return

    if (isListening) {
      recognitionRef.current.stop()
      setIsListening(false)
    } else {
      recognitionRef.current.start()
      setIsListening(true)
    }
  }

  const handleKeyPress = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendMessage()
    }
  }

  return (
    <div style={{
      position: 'fixed',
      inset: 0,
      backgroundColor: '#ffffff',
      display: 'flex',
      flexDirection: 'column',
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif'
    }}>
      {/* Header */}
      <div style={{
        backgroundColor: '#ffffff',
        borderBottom: '1px solid #e5e7eb',
        padding: '20px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <div style={{
            width: '40px',
            height: '40px',
            background: 'linear-gradient(135deg, #3b82f6, #8b5cf6)',
            borderRadius: '12px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center'
          }}>
            <Sparkles style={{ color: 'white', width: '20px', height: '20px' }} />
          </div>
          <div>
            <h1 style={{ margin: 0, fontSize: '18px', fontWeight: '600', color: '#111827' }}>
              Browser-Use AI
            </h1>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '14px' }}>
              <div style={{
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                backgroundColor: isConnected ? '#10b981' : '#ef4444'
              }} />
              <span style={{ color: '#6b7280' }}>
                {isConnected ? 'Connecté' : 'Déconnecté'}
              </span>
              {isThinking && <span style={{ color: '#f59e0b' }}>• Réflexion...</span>}
            </div>
          </div>
        </div>
      </div>

      {/* Messages Area */}
      <div style={{
        flex: 1,
        overflowY: 'auto',
        padding: '24px',
        backgroundColor: '#f9fafb'
      }}>
        {messages.length === 0 ? (
          <div style={{
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            height: '100%',
            textAlign: 'center',
            gap: '32px'
          }}>
            <div style={{
              width: '96px',
              height: '96px',
              background: 'linear-gradient(135deg, #3b82f6, #8b5cf6)',
              borderRadius: '24px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              boxShadow: '0 10px 25px rgba(59, 130, 246, 0.3)'
            }}>
              <Sparkles style={{ color: 'white', width: '48px', height: '48px' }} />
            </div>
            
            <div style={{ maxWidth: '400px' }}>
              <h2 style={{ fontSize: '24px', fontWeight: 'bold', color: '#111827', margin: '0 0 16px 0' }}>
                Bonjour ! 👋
              </h2>
              <p style={{ color: '#6b7280', lineHeight: '1.6', margin: 0 }}>
                Je suis votre assistant Browser-Use AI. Je peux naviguer sur le web, 
                effectuer des recherches et accomplir des tâches automatisées pour vous.
              </p>
            </div>
            
            {/* Suggestions */}
            <div style={{ display: 'grid', gap: '12px', width: '100%', maxWidth: '400px' }}>
              {[
                { 
                  icon: Search, 
                  text: "Rechercher des informations", 
                  action: "Recherche les dernières nouvelles sur l'IA",
                  color: 'linear-gradient(135deg, #3b82f6, #1d4ed8)'
                },
                { 
                  icon: Zap, 
                  text: "Automatiser une tâche", 
                  action: "Aide-moi à automatiser une tâche répétitive",
                  color: 'linear-gradient(135deg, #8b5cf6, #7c3aed)'
                },
                { 
                  icon: Brain, 
                  text: "Analyser un site web", 
                  action: "Analyse le contenu de cette page web",
                  color: 'linear-gradient(135deg, #10b981, #059669)'
                }
              ].map(({ icon: Icon, text, action, color }, index) => (
                <button
                  key={index}
                  onClick={() => setInputMessage(action)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '12px',
                    padding: '16px',
                    backgroundColor: '#ffffff',
                    borderRadius: '12px',
                    border: '1px solid #e5e7eb',
                    cursor: 'pointer',
                    textAlign: 'left',
                    transition: 'all 0.2s',
                    boxShadow: '0 1px 3px rgba(0, 0, 0, 0.1)'
                  }}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.borderColor = '#d1d5db'
                    e.currentTarget.style.boxShadow = '0 4px 12px rgba(0, 0, 0, 0.15)'
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.borderColor = '#e5e7eb'
                    e.currentTarget.style.boxShadow = '0 1px 3px rgba(0, 0, 0, 0.1)'
                  }}
                >
                  <div style={{
                    width: '40px',
                    height: '40px',
                    background: color,
                    borderRadius: '8px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center'
                  }}>
                    <Icon style={{ color: 'white', width: '20px', height: '20px' }} />
                  </div>
                  <div>
                    <div style={{ fontSize: '14px', fontWeight: '500', color: '#111827', marginBottom: '4px' }}>
                      {text}
                    </div>
                    <div style={{ fontSize: '12px', color: '#6b7280' }}>
                      {action}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {messages.map((message, index) => {
              const isUser = message.type === 'user'
              return (
                <div key={message.id || index} style={{
                  display: 'flex',
                  justifyContent: isUser ? 'flex-end' : 'flex-start',
                  marginBottom: '16px'
                }}>
                  <div style={{
                    display: 'flex',
                    flexDirection: isUser ? 'row-reverse' : 'row',
                    gap: '12px',
                    maxWidth: '80%'
                  }}>
                    {/* Avatar */}
                    <div style={{
                      width: '32px',
                      height: '32px',
                      borderRadius: '50%',
                      backgroundColor: isUser ? '#3b82f6' : '#10b981',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      flexShrink: 0
                    }}>
                      {isUser ? <User style={{ color: 'white', width: '16px', height: '16px' }} /> : <Bot style={{ color: 'white', width: '16px', height: '16px' }} />}
                    </div>

                    {/* Message */}
                    <div style={{
                      padding: '12px 16px',
                      borderRadius: '16px',
                      backgroundColor: isUser ? '#3b82f6' : '#f3f4f6',
                      color: isUser ? 'white' : '#111827',
                      borderBottomRightRadius: isUser ? '4px' : '16px',
                      borderBottomLeftRadius: isUser ? '16px' : '4px'
                    }}>
                      <div style={{ fontSize: '14px', lineHeight: '1.5', whiteSpace: 'pre-wrap' }}>
                        {message.content}
                      </div>
                      <div style={{
                        fontSize: '11px',
                        marginTop: '8px',
                        opacity: 0.7,
                        color: isUser ? 'rgba(255,255,255,0.8)' : '#6b7280'
                      }}>
                        {message.timestamp}
                      </div>
                    </div>
                  </div>
                </div>
              )
            })}

            {isThinking && (
              <div style={{ display: 'flex', justifyContent: 'flex-start', marginBottom: '16px' }}>
                <div style={{ display: 'flex', gap: '12px', maxWidth: '80%' }}>
                  <div style={{
                    width: '32px',
                    height: '32px',
                    borderRadius: '50%',
                    backgroundColor: '#10b981',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center'
                  }}>
                    <Bot style={{ color: 'white', width: '16px', height: '16px' }} />
                  </div>
                  <div style={{
                    padding: '12px 16px',
                    borderRadius: '16px',
                    borderBottomLeftRadius: '4px',
                    backgroundColor: '#f3f4f6',
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px'
                  }}>
                    <div style={{ display: 'flex', gap: '4px' }}>
                      {[0, 1, 2].map(i => (
                        <div key={i} style={{
                          width: '6px',
                          height: '6px',
                          borderRadius: '50%',
                          backgroundColor: '#9ca3af',
                          animation: `bounce 1.4s ease-in-out ${i * 0.16}s infinite`
                        }} />
                      ))}
                    </div>
                    <span style={{ fontSize: '14px', color: '#6b7280' }}>En train de réfléchir...</span>
                  </div>
                </div>
              </div>
            )}
          </>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Input Area */}
      <div style={{
        backgroundColor: '#ffffff',
        borderTop: '1px solid #e5e7eb',
        padding: '16px'
      }}>
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: '12px' }}>
          <div style={{ flex: 1, position: 'relative' }}>
            <textarea
              value={inputMessage}
              onChange={(e) => setInputMessage(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder="Tapez votre message..."
              style={{
                width: '100%',
                backgroundColor: '#f9fafb',
                color: '#111827',
                borderRadius: '16px',
                padding: '12px 16px',
                border: '1px solid #d1d5db',
                resize: 'none',
                minHeight: '48px',
                maxHeight: '120px',
                fontSize: '14px',
                fontFamily: 'inherit',
                outline: 'none'
              }}
              onFocus={(e) => e.target.style.borderColor = '#3b82f6'}
              onBlur={(e) => e.target.style.borderColor = '#d1d5db'}
              rows={1}
              disabled={!isConnected}
            />
            
            <div style={{
              position: 'absolute',
              bottom: '8px',
              right: '48px',
              fontSize: '12px',
              color: '#9ca3af'
            }}>
              {inputMessage.length}/1000
            </div>
          </div>
          
          {/* Voice Button */}
          <button
            onClick={toggleListening}
            disabled={!isConnected}
            style={{
              padding: '12px',
              borderRadius: '16px',
              border: 'none',
              backgroundColor: isListening ? '#ef4444' : '#f3f4f6',
              color: isListening ? 'white' : '#6b7280',
              cursor: isConnected ? 'pointer' : 'not-allowed',
              opacity: isConnected ? 1 : 0.5,
              transition: 'all 0.2s'
            }}
          >
            {isListening ? <MicOff style={{ width: '20px', height: '20px' }} /> : <Mic style={{ width: '20px', height: '20px' }} />}
          </button>
          
          {/* Send Button */}
          <button
            onClick={sendMessage}
            disabled={!inputMessage.trim() || !isConnected || isThinking}
            style={{
              padding: '12px',
              backgroundColor: '#3b82f6',
              color: 'white',
              borderRadius: '16px',
              border: 'none',
              cursor: (!inputMessage.trim() || !isConnected || isThinking) ? 'not-allowed' : 'pointer',
              opacity: (!inputMessage.trim() || !isConnected || isThinking) ? 0.5 : 1,
              transition: 'all 0.2s'
            }}
          >
            <Send style={{ width: '20px', height: '20px' }} />
          </button>
        </div>
        
        {isListening && (
          <div style={{ marginTop: '12px', textAlign: 'center' }}>
            <div style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '8px',
              color: '#f59e0b',
              fontSize: '14px'
            }}>
              <div style={{
                width: '8px',
                height: '8px',
                backgroundColor: '#f59e0b',
                borderRadius: '50%',
                animation: 'pulse 1s infinite'
              }} />
              <span>Écoute en cours... Parlez maintenant</span>
            </div>
          </div>
        )}
      </div>

      <style>{`
        @keyframes bounce {
          0%, 20%, 50%, 80%, 100% { transform: translateY(0); }
          40% { transform: translateY(-6px); }
          60% { transform: translateY(-3px); }
        }
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
      `}</style>
    </div>
  )
}

export default App 