import { useState, useEffect, useMemo } from 'react'
import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { Layout, Menu, Avatar, Dropdown, Space, Typography } from 'antd'
import {
  DashboardOutlined,
  DatabaseOutlined,
  MessageOutlined,
  WalletOutlined,
  SettingOutlined,
  LogoutOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { useAuthStore } from '@/stores/authStore'

const { Sider, Content, Header } = Layout
const { Text } = Typography

export default function AppLayout() {
  const [collapsed, setCollapsed] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  const { user, logout, fetchUser } = useAuthStore()

  useEffect(() => {
    if (!user) fetchUser()
  }, [user, fetchUser])

  const selectedKey = useMemo(() => {
    const path = location.pathname
    if (path.startsWith('/chat')) return '/chat'
    if (path.startsWith('/data-spaces')) return '/data-spaces'
    if (path.startsWith('/credits')) return '/credits'
    if (path.startsWith('/admin')) return '/admin'
    return '/'
  }, [location.pathname])

  const menuItems = [
    { key: '/', icon: <DashboardOutlined />, label: '工作台' },
    { key: '/data-spaces', icon: <DatabaseOutlined />, label: '数据空间' },
    { key: '/chat', icon: <MessageOutlined />, label: '智能对话' },
    { key: '/credits', icon: <WalletOutlined />, label: '额度中心' },
    ...(user?.role === 'admin'
      ? [{ key: '/admin', icon: <SettingOutlined />, label: '管理后台' }]
      : []),
  ]

  const userMenuItems = [
    { key: 'profile', icon: <UserOutlined />, label: '个人信息' },
    { type: 'divider' as const },
    { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', danger: true },
  ]

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        collapsible
        collapsed={collapsed}
        onCollapse={setCollapsed}
        theme="light"
        style={{
          borderRight: '1px solid #f0f0f0',
          position: 'fixed',
          left: 0,
          top: 0,
          bottom: 0,
          zIndex: 100,
        }}
      >
        <div style={{ padding: '16px', textAlign: 'center' }}>
          <img
            src="/logo.png"
            alt="Logo"
            style={{ width: collapsed ? 32 : 40, height: collapsed ? 32 : 40, borderRadius: 8 }}
          />
          {!collapsed && (
            <Text strong style={{ display: 'block', marginTop: 8, fontSize: 14 }}>
              Data Agent
            </Text>
          )}
        </div>
        <Menu
          mode="inline"
          selectedKeys={[selectedKey]}
          items={menuItems}
          onClick={({ key }) => navigate(key)}
          style={{ borderRight: 'none' }}
        />
      </Sider>
      <Layout style={{ marginLeft: collapsed ? 80 : 200, transition: 'margin-left 0.2s' }}>
        <Header
          style={{
            background: '#fff',
            padding: '0 24px',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'flex-end',
            borderBottom: '1px solid #f0f0f0',
            position: 'sticky',
            top: 0,
            zIndex: 99,
          }}
        >
          <Dropdown menu={{ items: userMenuItems, onClick: ({ key }) => key === 'logout' && logout() }}>
            <Space style={{ cursor: 'pointer' }}>
              <Avatar size="small" icon={<UserOutlined />} style={{ background: '#1677ff' }} />
              <Text>{user?.username || '用户'}</Text>
            </Space>
          </Dropdown>
        </Header>
        <Content style={{ padding: 24, background: '#f5f7fa', minHeight: 'calc(100vh - 64px)' }}>
          <Outlet />
        </Content>
      </Layout>
    </Layout>
  )
}
