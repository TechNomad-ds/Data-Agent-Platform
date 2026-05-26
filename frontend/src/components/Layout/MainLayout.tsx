import { useState, useEffect, useCallback } from 'react'
import { useAuthStore } from '@/stores/authStore'
import { dataSpacesApi } from '@/api/dataSpaces'
import Sidebar from '@/components/Sidebar/Sidebar'
import ChatView from '@/components/Chat/ChatView'
import DataManager from '@/components/DataManager/DataManager'
import SettingsPage from '@/pages/Settings'
import Onboarding from '@/components/Onboarding/Onboarding'

export type MainView = 'chat' | 'data' | 'settings'

export default function MainLayout() {
  const [currentView, setCurrentView] = useState<MainView>('chat')
  const [selectedSpaceId, setSelectedSpaceId] = useState<string | undefined>()
  const [currentConvId, setCurrentConvId] = useState<string | undefined>()
  const [showOnboarding, setShowOnboarding] = useState(false)
  const [checkingSpaces, setCheckingSpaces] = useState(true)
  const { user, fetchUser } = useAuthStore()

  useEffect(() => {
    if (!user) fetchUser()
  }, [user, fetchUser])

  // 检查是否需要显示引导
  useEffect(() => {
    const checkSpaces = async () => {
      try {
        const res = await dataSpacesApi.list()
        if (res.data.length === 0) {
          setShowOnboarding(true)
        } else {
          setSelectedSpaceId(res.data[0].id)
        }
      } catch {}
      setCheckingSpaces(false)
    }
    checkSpaces()
  }, [])

  const handleOnboardingComplete = useCallback((spaceId: string) => {
    setShowOnboarding(false)
    setSelectedSpaceId(spaceId)
    setCurrentView('chat')
  }, [])

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

  const handleOpenSettings = useCallback(() => {
    setCurrentView('settings')
  }, [])

  const handleStartChat = useCallback(() => {
    setCurrentConvId(undefined)
    setCurrentView('chat')
  }, [])

  return (
    <>
      {checkingSpaces ? (
        <div style={{ height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ textAlign: 'center', color: '#94a3b8' }}>加载中...</div>
        </div>
      ) : showOnboarding ? (
        <Onboarding onComplete={handleOnboardingComplete} />
      ) : (
        <div style={{ display: 'flex', height: '100vh', width: '100vw', overflow: 'hidden' }}>
          <Sidebar
            selectedSpaceId={selectedSpaceId}
            onSpaceChange={setSelectedSpaceId}
            currentConvId={currentConvId}
            onNewChat={handleNewChat}
            onSelectConversation={handleSelectConversation}
            onOpenDataManager={handleOpenDataManager}
            onOpenSettings={handleOpenSettings}
            currentView={currentView}
          />

          <div style={{ flex: 1, overflow: 'hidden' }}>
            {currentView === 'chat' ? (
              <ChatView
                selectedSpaceId={selectedSpaceId}
                conversationId={currentConvId}
                onConversationCreated={setCurrentConvId}
              />
            ) : currentView === 'data' ? (
              <DataManager
                selectedSpaceId={selectedSpaceId}
                onSpaceChange={setSelectedSpaceId}
                onStartChat={handleStartChat}
              />
            ) : (
              <SettingsPage />
            )}
          </div>
        </div>
      )}
    </>
  )
}
