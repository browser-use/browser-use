import { useState, useEffect, useCallback } from 'react'

interface UseSpeechRecognitionReturn {
  isListening: boolean
  transcript: string
  startListening: () => void
  stopListening: () => void
  isSupported: boolean
}

export function useSpeechRecognition(): UseSpeechRecognitionReturn {
  const [isListening, setIsListening] = useState(false)
  const [transcript, setTranscript] = useState('')
  const [recognition, setRecognition] = useState<any>(null)

  // Verificar se Speech Recognition API está disponível
  const isSupported = typeof window !== 'undefined' && 
    ('SpeechRecognition' in window || 'webkitSpeechRecognition' in window)

  useEffect(() => {
    if (!isSupported) return

    // Criar instância do Speech Recognition
    const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition
    const recognitionInstance = new SpeechRecognition()

    recognitionInstance.continuous = true
    recognitionInstance.interimResults = true
    recognitionInstance.lang = 'pt-BR'

    recognitionInstance.onresult = (event: any) => {
      let finalTranscript = ''
      
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript
        if (event.results[i].isFinal) {
          finalTranscript += transcript + ' '
        }
      }

      if (finalTranscript) {
        setTranscript(finalTranscript.trim())
      }
    }

    recognitionInstance.onerror = (event: any) => {
      console.error('Erro no reconhecimento de voz:', event.error)
      setIsListening(false)
    }

    recognitionInstance.onend = () => {
      setIsListening(false)
    }

    setRecognition(recognitionInstance)

    return () => {
      if (recognitionInstance) {
        recognitionInstance.stop()
      }
    }
  }, [isSupported])

  const startListening = useCallback(() => {
    if (!recognition) return

    try {
      setTranscript('')
      recognition.start()
      setIsListening(true)
    } catch (error) {
      console.error('Erro ao iniciar reconhecimento de voz:', error)
    }
  }, [recognition])

  const stopListening = useCallback(() => {
    if (!recognition) return

    try {
      recognition.stop()
      setIsListening(false)
    } catch (error) {
      console.error('Erro ao parar reconhecimento de voz:', error)
    }
  }, [recognition])

  return {
    isListening,
    transcript,
    startListening,
    stopListening,
    isSupported,
  }
}
