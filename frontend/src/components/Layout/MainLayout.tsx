import { useState, useEffect, useCallback } from 'react'
import { Modal, Drawer, Button } from 'antd'
import { MenuOutlined } from '@ant-design/icons'
import { useAuthStore } from '@/stores/authStore'
import { dataSpacesApi } from '@/api/dataSpaces'
import { chatApi } from '@/api/chat'
import { useIsMobile } from '@/hooks/useIsMobile'
import NavRail from '@/components/Sidebar/NavRail'
import ConversationPanel from '@/components/Sidebar/ConversationPanel'
import ChatView from '@/components/Chat/ChatView'
import DataManager from '@/components/DataManager/DataManager'
import SettingsPage from '@/pages/Settings'
import CreditsPage from '@/pages/Credits'
import AdminPage from '@/pages/Admin'
import Onboarding from '@/components/Onboarding/Onboarding'
import Logo from '@/components/Layout/Logo'
import { colors } from '@/styles/tokens'

export type MainView = 'chat' | 'data' | 'settings' | 'credits' | 'admin'

export default function MainLayout() {
  const [currentView, setCurrentView] = useState<MainView>('chat')
  const [selectedSpaceId, setSelectedSpaceId] = useState<string | undefined>()
  // 多项目：当前选中的全部项目 id（含主空间，主空间=第一个）。selectedSpaceId 与它的首元素保持一致。
  const [selectedSpaceIds, setSelectedSpaceIds] = useState<string[]>([])
  const [currentConvId, setCurrentConvId] = useState<string | undefined>()
  const [showOnboarding, setShowOnboarding] = useState(false)
  const [checkingSpaces, setCheckingSpaces] = useState(true)
  const [showGuide, setShowGuide] = useState(false)
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const isMobile = useIsMobile()
  const { user, fetchUser } = useAuthStore()

  useEffect(() => {
    if (!user) fetchUser()
  }, [user, fetchUser])

  // 切回桌面端时收起抽屉，避免再次回到移动端时残留打开态
  useEffect(() => {
    if (!isMobile) setMobileMenuOpen(false)
  }, [isMobile])

  // 检查是否需要显示引导
  useEffect(() => {
    const checkSpaces = async () => {
      try {
        const res = await dataSpacesApi.list()
        if (res.data.length === 0) {
          setShowOnboarding(true)
        } else {
          setSelectedSpaceId(res.data[0].id)
          setSelectedSpaceIds([res.data[0].id])
        }
      } catch {}
      setCheckingSpaces(false)
    }
    checkSpaces()
  }, [])

  const handleOnboardingComplete = useCallback((spaceId: string) => {
    setShowOnboarding(false)
    setSelectedSpaceId(spaceId)
    setSelectedSpaceIds([spaceId])
    setCurrentView('chat')
    if (!localStorage.getItem('guide_seen')) {
      setShowGuide(true)
      localStorage.setItem('guide_seen', '1')
    }
  }, [])

  const handleNewChat = useCallback(() => {
    setCurrentConvId(undefined)
    setCurrentView('chat')
  }, [])

  const handleSelectConversation = useCallback(async (id: string) => {
    setCurrentConvId(id)
    setCurrentView('chat')
    try {
      const res = await chatApi.getConversation(id)
      // 优先用对话存的多项目全集恢复；否则回退到单空间；都没有则普通对话
      const ids = (res.data.data_space_ids && res.data.data_space_ids.length)
        ? res.data.data_space_ids
        : (res.data.data_space_id ? [res.data.data_space_id] : [])
      setSelectedSpaceIds(ids)
      setSelectedSpaceId(ids[0])
    } catch {
      // 加载失败不阻断
    }
  }, [])

  // 项目切换的唯一入口（左侧项目栏）：支持多选。第一个为主空间。
  // 切换后回到聊天视图、开启新对话，并让中间栏按主空间过滤历史。
  const handleSelectSpaces = useCallback((ids: string[]) => {
    setSelectedSpaceIds(ids)
    setSelectedSpaceId(ids[0])
    setCurrentConvId(undefined)
    setCurrentView('chat')
  }, [])

  const handleOpenDataManager = useCallback(() => {
    setSelectedSpaceId(undefined)
    setSelectedSpaceIds([])
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
  }, [])

  const handleStartChat = useCallback(() => {
    setCurrentConvId(undefined)
    setCurrentView('chat')
  }, [])

  // 移动端：导航动作后自动收起抽屉（选对话 / 切视图 / 新对话等）
  const withDrawerClose = useCallback(
    <A extends any[]>(fn: (...a: A) => void) =>
      (...a: A) => {
        fn(...a)
        setMobileMenuOpen(false)
      },
    []
  )

  const navRail = (
    <NavRail
      currentView={currentView}
      onOpenChat={withDrawerClose(handleNewChat)}
      onOpenDataManager={withDrawerClose(handleOpenDataManager)}
      onOpenCredits={withDrawerClose(handleOpenCredits)}
      onOpenAdmin={withDrawerClose(handleOpenAdmin)}
      onOpenSettings={withDrawerClose(handleOpenSettings)}
      inDrawer={isMobile}
    />
  )

  // 对话历史面板：仅对话视图展示（其余视图为全宽内容页）
  const conversationPanel = (
    <ConversationPanel
      currentConvId={currentConvId}
      onNewChat={withDrawerClose(handleNewChat)}
      onSelectConversation={withDrawerClose(handleSelectConversation)}
      onOpenDataManager={withDrawerClose(handleOpenDataManager)}
      selectedSpaceId={selectedSpaceId}
      onSelectSpace={withDrawerClose((id: string | undefined) => handleSelectSpaces(id ? [id] : []))}
      selectedSpaceIds={selectedSpaceIds}
      onSelectSpaces={withDrawerClose(handleSelectSpaces)}
      inDrawer={isMobile}
    />
  )

  const mainContent =
    currentView === 'chat' ? (
      <ChatView
        selectedSpaceId={selectedSpaceId}
        selectedSpaceIds={selectedSpaceIds}
        conversationId={currentConvId}
        onConversationCreated={handleConversationCreated}
        onConversationDeleted={handleNewChat}
      />
    ) : currentView === 'data' ? (
      <DataManager
        selectedSpaceId={selectedSpaceId}
        onSpaceChange={(id?: string) => { setSelectedSpaceId(id); setSelectedSpaceIds(id ? [id] : []) }}
        onStartChat={handleStartChat}
      />
    ) : currentView === 'credits' ? (
      <div style={{ height: '100%', overflow: 'auto', background: '#f8fafc', padding: isMobile ? 16 : 32 }}>
        <div style={{ maxWidth: 900, margin: '0 auto' }}>
          <CreditsPage />
        </div>
      </div>
    ) : currentView === 'admin' ? (
      <div style={{ height: '100%', overflow: 'auto', background: '#f8fafc', padding: isMobile ? 16 : 32 }}>
        <div style={{ maxWidth: 1100, margin: '0 auto' }}>
          <AdminPage />
        </div>
      </div>
    ) : (
      <SettingsPage />
    )

  return (
    <>
      {checkingSpaces ? (
        <div style={{ height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ textAlign: 'center', color: '#94a3b8' }}>加载中...</div>
        </div>
      ) : showOnboarding ? (
        <Onboarding onComplete={handleOnboardingComplete} />
      ) : isMobile ? (
        <div style={{ display: 'flex', flexDirection: 'column', height: '100dvh', width: '100%', overflow: 'hidden' }}>
          {/* 移动端顶栏：汉堡按钮 + 品牌 */}
          <div
            style={{
              flexShrink: 0,
              height: 48,
              display: 'flex',
              alignItems: 'center',
              gap: 8,
              padding: '0 8px',
              borderBottom: `1px solid ${colors.border}`,
              background: colors.surface,
            }}
          >
            <Button
              type="text"
              icon={<MenuOutlined />}
              onClick={() => setMobileMenuOpen(true)}
              style={{ color: colors.textSecondary }}
              aria-label="打开菜单"
            />
            <Logo size={22} />
          </div>
          <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>{mainContent}</div>
          <Drawer
            placement="left"
            open={mobileMenuOpen}
            onClose={() => setMobileMenuOpen(false)}
            width={Math.min(300, typeof window !== 'undefined' ? window.innerWidth * 0.85 : 300)}
            styles={{ body: { padding: 0 } }}
            closable={false}
          >
            <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: colors.bgSubtle }}>
              {navRail}
              <div style={{ borderTop: `1px solid ${colors.border}`, flex: 1, minHeight: 0, overflow: 'hidden' }}>
                {conversationPanel}
              </div>
            </div>
          </Drawer>
        </div>
      ) : (
        <div style={{ display: 'flex', height: '100vh', width: '100vw', overflow: 'hidden' }}>
          {navRail}
          {currentView === 'chat' && conversationPanel}
          <div style={{ flex: 1, overflow: 'hidden' }}>{mainContent}</div>
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
            <div><strong>① 数据管理</strong> — 左侧进入数据管理，创建项目并上传文件</div>
            <div><strong>② 新建对话</strong> — 点击"新对话"，在顶部选择项目和模型</div>
            <div><strong>③ 开始提问</strong> — 用自然语言问关于你数据的任何问题</div>
          </div>
          <div style={{ marginTop: 16, fontSize: 12, color: '#94a3b8' }}>
            模型随时可切换，历史对话会按项目分组显示在左侧
          </div>
        </div>
      </Modal>
    </>
  )
}
