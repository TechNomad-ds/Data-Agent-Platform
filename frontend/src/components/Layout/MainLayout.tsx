import { useState, useEffect, useCallback } from 'react'
import { useAuthStore } from '@/stores/authStore'
import Sidebar from '@/components/Sidebar/Sidebar'
import ChatView from '@/components/Chat/ChatView'
import DataManager from '@/components/DataManager/DataManager'

export type MainView = 'chat' | 'data'

export default function MainLayout() {
  const [currentView, setCurrentView] = useState<MainView>('chat')
  const [selectedSpaceId, setSelectedSpaceId] = useState<string | undefined>()
  const [currentConvId, setCurrentConvId] = useState<string | undefined>()
  const { user, fetchUser } = useAuthStore()

  useEffect(() => {
    if (!user) fetchUser()
  }, [user, fetchUser])

  const handleNewChat = useCallback(() => {
    setCurrentConvId(undefined)
    setCurrentView('chat')
  }, [])

  const handleSelectConversation = useCallback((id: string) => {
    setCurrentConvId(id)
    setCurrentView('chat')
  }, [])

  const handleOpenDataManager = useCallback(() => {
    setCurrentView('data')
  }, [])

  return (
    <div style={{ display: 'flex', height: '100vh', width: '100vw', overflow: 'hidden' }}>
      {/* Left sidebar */}
      <Sidebar
        selectedSpaceId={selectedSpaceId}
        onSpaceChange={setSelectedSpaceId}
        currentConvId={currentConvId}
        onNewChat={handleNewChat}
        onSelectConversation={handleSelectConversation}
        onOpenDataManager={handleOpenDataManager}
        currentView={currentView}
      />

      {/* Right main area */}
      <div style={{ flex: 1, overflow: 'hidden' }}>
        {currentView === 'chat' ? (
          <ChatView
            selectedSpaceId={selectedSpaceId}
            conversationId={currentConvId}
            onConversationCreated={setCurrentConvId}
          />
        ) : (
          <DataManager
            selectedSpaceId={selectedSpaceId}
            onSpaceChange={setSelectedSpaceId}
          />
        )}
      </div>
    </div>
  )
}
