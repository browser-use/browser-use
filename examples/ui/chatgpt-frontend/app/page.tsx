'use client'

import { useState } from 'react'
import Sidebar from '@/components/Sidebar'
import ChatInterface from '@/components/ChatInterface'
import BrowserPreview from '@/components/BrowserPreview'

export default function Home() {
  const [currentSessionId, setCurrentSessionId] = useState<string | null>(null)
  const [showBrowserPreview, setShowBrowserPreview] = useState(true)

  return (
    <main className="flex h-screen bg-chatgpt-gray-50 dark:bg-chatgpt-gray-900">
      {/* Sidebar */}
      <Sidebar 
        currentSessionId={currentSessionId}
        onSessionSelect={setCurrentSessionId}
      />

      {/* Chat Area */}
      <div className="flex-1 flex flex-col">
        <ChatInterface 
          sessionId={currentSessionId}
          onSessionCreated={setCurrentSessionId}
          onToggleBrowserPreview={() => setShowBrowserPreview(!showBrowserPreview)}
        />
      </div>

      {/* Browser Preview (collapsible) */}
      {showBrowserPreview && (
        <BrowserPreview 
          sessionId={currentSessionId}
          onClose={() => setShowBrowserPreview(false)}
        />
      )}
    </main>
  )
}
