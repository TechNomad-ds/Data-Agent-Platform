import { Tooltip, Dropdown } from 'antd'
import {
  MessageOutlined,
  DatabaseOutlined,
  WalletOutlined,
  CrownOutlined,
  SettingOutlined,
  LogoutOutlined,
} from '@ant-design/icons'
import { useAuthStore } from '@/stores/authStore'
import { MainView } from '@/components/Layout/MainLayout'
import Logo from '@/components/Layout/Logo'
import { colors } from '@/styles/tokens'

interface Props {
  currentView: MainView
  onOpenChat: () => void
  onOpenDataManager: () => void
  onOpenCredits: () => void
  onOpenAdmin: () => void
  onOpenSettings: () => void
  /** 在移动端抽屉内：横向铺满成宽行，文字常显 */
  inDrawer?: boolean
}

interface NavEntry {
  key: MainView
  label: string
  icon: React.ReactNode
  onClick: () => void
  show: boolean
}

export default function NavRail({
  currentView,
  onOpenChat,
  onOpenDataManager,
  onOpenCredits,
  onOpenAdmin,
  onOpenSettings,
  inDrawer = false,
}: Props) {
  const { user, logout } = useAuthStore()
  const userInitial = (user?.username || 'U')[0].toUpperCase()

  // 信息架构：对话在最上，其后是数据管理、额度、管理后台（后台仅管理员可见）
  const entries: NavEntry[] = [
    { key: 'chat', label: '对话', icon: <MessageOutlined />, onClick: onOpenChat, show: true },
    { key: 'data', label: '数据管理', icon: <DatabaseOutlined />, onClick: onOpenDataManager, show: true },
    { key: 'credits', label: '额度与 API', icon: <WalletOutlined />, onClick: onOpenCredits, show: true },
    { key: 'admin', label: '管理后台', icon: <CrownOutlined />, onClick: onOpenAdmin, show: user?.role === 'admin' },
  ]

  const accountMenuItems = [
    { key: 'settings', label: '设置', icon: <SettingOutlined />, onClick: onOpenSettings },
    { type: 'divider' as const },
    { key: 'logout', label: '退出登录', icon: <LogoutOutlined />, danger: true, onClick: logout },
  ]

  const avatar = (
    <Dropdown
      menu={{ items: accountMenuItems, selectable: true, selectedKeys: [currentView] }}
      trigger={['click']}
      placement={inDrawer ? 'bottomLeft' : 'topLeft'}
    >
      <div
        style={{
          width: 32,
          height: 32,
          borderRadius: '50%',
          background: colors.userAvatar,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 13,
          color: '#fff',
          fontWeight: 600,
          cursor: 'pointer',
          flexShrink: 0,
        }}
      >
        {userInitial}
      </div>
    </Dropdown>
  )

  // 移动端抽屉：横向宽行（图标 + 文案），便于触屏点击
  if (inDrawer) {
    return (
      <div style={{ padding: '12px 12px 8px', display: 'flex', flexDirection: 'column', gap: 4 }}>
        {entries
          .filter((e) => e.show)
          .map((e) => (
            <div
              key={e.key}
              className={`sidebar-item${currentView === e.key ? ' active' : ''}`}
              onClick={e.onClick}
            >
              <span style={{ fontSize: 16, display: 'flex' }}>{e.icon}</span>
              <span style={{ flex: 1 }}>{e.label}</span>
            </div>
          ))}
        <div style={{ margin: '6px 0', borderTop: `1px solid ${colors.border}` }} />
        <div
          className="sidebar-item"
          onClick={onOpenSettings}
          style={{ display: 'flex', alignItems: 'center', gap: 10 }}
        >
          {avatar}
          <span style={{ flex: 1 }}>{user?.username || '用户'}</span>
        </div>
      </div>
    )
  }

  // 桌面端：窄导航栏（图标 + 小字号标签）
  return (
    <div
      style={{
        width: 72,
        height: '100vh',
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        padding: '14px 0 12px',
        background: colors.bgSubtle,
        borderRight: `1px solid ${colors.border}`,
        flexShrink: 0,
      }}
    >
      <div style={{ marginBottom: 16 }}>
        <Logo size={28} withText={false} />
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6, alignItems: 'center', width: '100%' }}>
        {entries
          .filter((e) => e.show)
          .map((e) => {
            const active = currentView === e.key
            return (
              <Tooltip key={e.key} title={e.label} placement="right">
                <div
                  className="nav-rail-item"
                  onClick={e.onClick}
                  style={{
                    width: 56,
                    padding: '8px 0 6px',
                    borderRadius: 10,
                    display: 'flex',
                    flexDirection: 'column',
                    alignItems: 'center',
                    gap: 3,
                    cursor: 'pointer',
                    color: active ? colors.primary : colors.textSecondary,
                    background: active ? '#ececf1' : 'transparent',
                    transition: 'background 0.12s, color 0.12s',
                  }}
                >
                  <span style={{ fontSize: 19, display: 'flex' }}>{e.icon}</span>
                  <span style={{ fontSize: 10.5, lineHeight: 1.1, fontWeight: active ? 600 : 500, textAlign: 'center' }}>
                    {e.label}
                  </span>
                </div>
              </Tooltip>
            )
          })}
      </div>
      <div style={{ flex: 1 }} />
      {avatar}
    </div>
  )
}
