import { useState, useEffect } from 'react'
import { Outlet } from 'react-router-dom'
import { ConfigProvider, Button, Tooltip } from 'antd'
import { MenuFoldOutlined, MenuUnfoldOutlined, TableOutlined } from '@ant-design/icons'
import { useAuthStore } from '@/stores/authStore'
import { lightThemeConfig } from '@/theme/themeConfig'
import Sidebar from '@/components/Sidebar/Sidebar'
import DataPanel from '@/components/DataPanel/DataPanel'

export default function AppLayout() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const [dataPanelVisible, setDataPanelVisible] = useState(false)
  const [selectedSpaceId, setSelectedSpaceId] = useState<string | undefined>()
  const { user, fetchUser } = useAuthStore()

  useEffect(() => {
    if (!user) fetchUser()
  }, [user, fetchUser])

  return (
    <ConfigProvider theme={lightThemeConfig}>
      <div style={{
        display: 'flex',
        height: '100vh',
        width: '100vw',
        overflow: 'hidden',
        background: '#f8fafc',
      }}>
        <Sidebar
          collapsed={sidebarCollapsed}
          onSpaceChange={setSelectedSpaceId}
        />

        <div style={{
          position: 'fixed',
          top: 12,
          left: sidebarCollapsed ? 12 : 308,
          zIndex: 100,
          transition: 'left 0.2s',
          display: 'flex',
          gap: 4,
        }}>
          <Tooltip title={sidebarCollapsed ? '展开侧栏' : '收起侧栏'}>
            <Button
              type="text"
              size="small"
              icon={sidebarCollapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
              onClick={() => setSidebarCollapsed(!sidebarCollapsed)}
              style={{ color: '#94a3b8' }}
            />
          </Tooltip>
        </div>

        {/* Data panel toggle - fixed top right */}
        <div style={{ position: 'fixed', top: 12, right: dataPanelVisible ? 428 : 12, zIndex: 100, transition: 'right 0.2s' }}>
          <Tooltip title={dataPanelVisible ? '关闭数据面板' : '查看数据'}>
            <Button
              type={dataPanelVisible ? 'primary' : 'text'}
              size="small"
              icon={<TableOutlined />}
              onClick={() => setDataPanelVisible(!dataPanelVisible)}
              style={dataPanelVisible ? {} : { color: '#64748b' }}
            />
          </Tooltip>
        </div>

        <Outlet />

        <DataPanel
          spaceId={selectedSpaceId}
          visible={dataPanelVisible}
          onClose={() => setDataPanelVisible(false)}
        />
      </div>
    </ConfigProvider>
  )
}
