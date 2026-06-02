import { useState, useEffect, useCallback } from 'react'
import { Modal } from 'antd'
import { useAuthStore } from '@/stores/authStore'
import { dataSpacesApi } from '@/api/dataSpaces'
import { chatApi } from '@/api/chat'
import Sidebar from '@/components/Sidebar/Sidebar'
import ChatView from '@/components/Chat/ChatView'
import DataManager from '@/components/DataManager/DataManager'
import SettingsPage from '@/pages/Settings'
import CreditsPage from '@/pages/Credits'
import AdminPage from '@/pages/Admin'
import Onboarding from '@/components/Onboarding/Onboarding'

export type MainView = 'chat' | 'data' | 'settings' | 'credits' | 'admin'

export default function MainLayout() {
  const [currentView, setCurrentView] = useState<MainView>('chat')
  const [selectedSpaceId, setSelectedSpaceId] = useState<string | undefined>()
  const [currentConvId, setCurrentConvId] = useState<string | undefined>()
  const [showOnboarding, setShowOnboarding] = useState(false)
  const [checkingSpaces, setCheckingSpaces] = useState(true)
  const [spaceLockedByConversation, setSpaceLockedByConversation] = useState(false)
  const [showGuide, setShowGuide] = useState(false)
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
    if (!localStorage.getItem('guide_seen')) {
      setShowGuide(true)
      localStorage.setItem('guide_seen', '1')
    }
  }, [])

  const handleNewChat = useCallback(() => {
    setCurrentConvId(undefined)
    setSpaceLockedByConversation(false)
    setCurrentView('chat')
  }, [])

  const handleSelectConversation = useCallback(async (id: string) => {
    setCurrentConvId(id)
    setCurrentView('chat')
    try {
      const res = await chatApi.getConversation(id)
      if (res.data.data_space_id) {
        setSelectedSpaceId(res.data.data_space_id)
        setSpaceLockedByConversation(true)
      } else {
        setSelectedSpaceId(undefined)
        setSpaceLockedByConversation(false)
      }
    } catch {
      setSpaceLockedByConversation(true)
    }
  }, [])

  const handleSpaceChange = useCallback((id: string | undefined) => {
    if (!spaceLockedByConversation) {
      setSelectedSpaceId(id)
      setCurrentConvId(undefined)
    }
  }, [spaceLockedByConversation])

  const handleOpenDataManager = useCallback(() => {
    setSelectedSpaceId(undefined)
    setCurrentView('data')
  }, [])

  const handleOpenSettings = useCallback(() => {
    setCurrentView('settings')
  }, [])

  const handleOpenCredits = useCallback(() => {
    setCurrentView('credits')
  }, [])

  const handleOpenAdmin = useCallback(() => {
    setCurrentView('admin')
  }, [])

  const handleConversationCreated = useCallback((id: string) => {
    setCurrentConvId(id)
    setSpaceLockedByConversation(true)
  }, [])

  const handleStartChat = useCallback(() => {
    setCurrentConvId(undefined)
    setSpaceLockedByConversation(false)
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
            currentConvId={currentConvId}
            onNewChat={handleNewChat}
            onSelectConversation={handleSelectConversation}
            onOpenDataManager={handleOpenDataManager}
            onOpenSettings={handleOpenSettings}
            onOpenCredits={handleOpenCredits}
            onOpenAdmin={handleOpenAdmin}
            currentView={currentView}
          />

          <div style={{ flex: 1, overflow: 'hidden' }}>
            {currentView === 'chat' ? (
              <ChatView
                selectedSpaceId={selectedSpaceId}
                conversationId={currentConvId}
                onConversationCreated={handleConversationCreated}
                onConversationDeleted={handleNewChat}
                onSpaceChange={handleSpaceChange}
                spaceLockedByConversation={spaceLockedByConversation}
              />
            ) : currentView === 'data' ? (
              <DataManager
                selectedSpaceId={selectedSpaceId}
                onSpaceChange={setSelectedSpaceId}
                onStartChat={handleStartChat}
              />
            ) : currentView === 'credits' ? (
              <div style={{ height: '100vh', overflow: 'auto', background: '#f8fafc', padding: 32 }}>
                <div style={{ maxWidth: 900, margin: '0 auto' }}>
                  <CreditsPage />
                </div>
              </div>
            ) : currentView === 'admin' ? (
              <div style={{ height: '100vh', overflow: 'auto', background: '#f8fafc', padding: 32 }}>
                <div style={{ maxWidth: 1100, margin: '0 auto' }}>
                  <AdminPage />
                </div>
              </div>
            ) : (
              <SettingsPage />
            )}
          </div>
        </div>
      )}

      <Modal
        open={showGuide}
        onCancel={() => setShowGuide(false)}
        onOk={() => setShowGuide(false)}
        okText="知道了"
        cancelButtonProps={{ style: { display: 'none' } }}
        centered
        width={420}
      >
        <div style={{ textAlign: 'center', padding: '12px 0' }}>
          <div style={{ fontSize: 36, marginBottom: 12 }}>👋</div>
          <div style={{ fontSize: 16, fontWeight: 600, color: '#1e293b', marginBottom: 16 }}>开始使用 DataMind</div>
          <div style={{ textAlign: 'left', fontSize: 14, color: '#475569', lineHeight: 2.2 }}>
            <div><strong>① 数据管理</strong> — 左侧进入数据管理，创建数据空间并上传文件</div>
            <div><strong>② 新建对话</strong> — 点击"新对话"，在顶部选择数据空间和模型</div>
            <div><strong>③ 开始提问</strong> — 用自然语言问关于你数据的任何问题</div>
          </div>
          <div style={{ marginTop: 16, fontSize: 12, color: '#94a3b8' }}>
            模型随时可切换，历史对话会按数据空间分组显示在左侧
          </div>
        </div>
      </Modal>
    </>
  )
}
