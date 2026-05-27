import { useState, useEffect } from 'react'
import { Input, Button, Typography, Divider } from 'antd'
import {
  PlusOutlined, SearchOutlined, DatabaseOutlined,
  MessageOutlined, LogoutOutlined, SettingOutlined,
} from '@ant-design/icons'
import { chatApi, Conversation } from '@/api/chat'
import { dataSpacesApi, DataSpace } from '@/api/dataSpaces'
import { useAuthStore } from '@/stores/authStore'
import { MainView } from '@/components/Layout/MainLayout'

const { Text } = Typography

function formatRelativeTime(dateStr: string): string {
  try {
    const now = Date.now()
    const d = new Date(dateStr).getTime()
    const diff = Math.floor((now - d) / 1000)
    if (diff < 60) return '刚刚'
    if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
    if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
    if (diff < 172800) return '昨天'
    return `${Math.floor(diff / 86400)}天前`
  } catch { return '' }
}

interface Props {
  currentConvId: string | undefined
  onNewChat: () => void
  onSelectConversation: (id: string) => void
  onOpenDataManager: () => void
  onOpenSettings: () => void
  currentView: MainView
}

interface GroupedConversations {
  spaceName: string
  spaceId: string
  conversations: Conversation[]
}

export default function Sidebar({
  currentConvId,
  onNewChat, onSelectConversation, onOpenDataManager, onOpenSettings, currentView,
}: Props) {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [spaces, setSpaces] = useState<DataSpace[]>([])
  const [searchText, setSearchText] = useState('')
  const { user, logout } = useAuthStore()

  useEffect(() => {
    loadConversations()
    loadSpaces()
  }, [currentConvId])

  const loadConversations = async () => {
    try {
      const res = await chatApi.listConversations()
      setConversations(res.data)
    } catch {}
  }

  const loadSpaces = async () => {
    try {
      const res = await dataSpacesApi.list()
      setSpaces(res.data)
    } catch {}
  }

  // Group conversations by data space
  const grouped: GroupedConversations[] = (() => {
    const filtered = (searchText
      ? conversations.filter(c => (c.title || '').toLowerCase().includes(searchText.toLowerCase()))
      : conversations
    ).filter(c => c.data_space_id)

    const map = new Map<string, Conversation[]>()
    for (const conv of filtered) {
      const key = conv.data_space_id!
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(conv)
    }

    const result: GroupedConversations[] = []
    for (const [spaceId, convs] of map) {
      const space = spaces.find(s => s.id === spaceId)
      result.push({
        spaceId,
        spaceName: space?.name || '未知空间',
        conversations: convs.slice(0, 10),
      })
    }
    return result
  })()

  return (
    <div style={{
      width: 280,
      height: '100vh',
      display: 'flex',
      flexDirection: 'column',
      background: '#ffffff',
      borderRight: '1px solid #e2e8f0',
      flexShrink: 0,
    }}>
      {/* Logo + New Chat */}
      <div style={{ padding: '16px 14px 8px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
          <div style={{
            width: 30, height: 30, borderRadius: 8,
            background: 'linear-gradient(135deg, #4f46e5, #7c3aed)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 14, color: '#fff', fontWeight: 700,
          }}>D</div>
          <Text style={{ fontSize: 14, fontWeight: 600, color: '#1e293b' }}>Data Agent</Text>
        </div>

        <Button
          type="primary"
          icon={<PlusOutlined />}
          block
          onClick={onNewChat}
          style={{ height: 36, fontSize: 13, marginBottom: 10 }}
        >
          新对话
        </Button>

        {/* Search */}
        <Input
          prefix={<SearchOutlined style={{ color: '#94a3b8' }} />}
          placeholder="搜索对话..."
          value={searchText}
          onChange={e => setSearchText(e.target.value)}
          allowClear
          size="small"
          style={{ marginBottom: 8 }}
        />
      </div>

      {/* Data Manager Entry */}
      <div style={{ padding: '0 14px 8px' }}>
        <Button
          type={currentView === 'data' ? 'default' : 'text'}
          icon={<DatabaseOutlined />}
          block
          onClick={onOpenDataManager}
          style={{
            height: 34, fontSize: 13, justifyContent: 'flex-start',
            background: currentView === 'data' ? '#f1f5f9' : 'transparent',
            fontWeight: currentView === 'data' ? 500 : 400,
          }}
        >
          数据管理
        </Button>
      </div>

      <Divider style={{ margin: '4px 0' }} />

      {/* Conversation History grouped by space */}
      <div style={{ flex: 1, overflow: 'auto', padding: '4px 0' }}>
        {grouped.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '30px 16px', color: '#94a3b8', fontSize: 13 }}>
            暂无对话记录
          </div>
        ) : (
          grouped.map(group => (
            <div key={group.spaceId} style={{ marginBottom: 8 }}>
              {/* Space header */}
              <div style={{
                padding: '6px 16px',
                fontSize: 11,
                fontWeight: 600,
                color: '#94a3b8',
                textTransform: 'uppercase',
                letterSpacing: 0.5,
              }}>
                <DatabaseOutlined style={{ marginRight: 4 }} />
                {group.spaceName}
              </div>

              {/* Conversations in this space */}
              {group.conversations.map(conv => (
                <div
                  key={conv.id}
                  onClick={() => onSelectConversation(conv.id)}
                  style={{
                    padding: '8px 16px 8px 28px',
                    cursor: 'pointer',
                    background: currentConvId === conv.id ? '#f1f5f9' : 'transparent',
                    borderRadius: 0,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    transition: 'background 0.1s',
                  }}
                  onMouseEnter={e => { if (currentConvId !== conv.id) e.currentTarget.style.background = '#f8fafc' }}
                  onMouseLeave={e => { if (currentConvId !== conv.id) e.currentTarget.style.background = 'transparent' }}
                >
                  <MessageOutlined style={{ fontSize: 11, color: '#94a3b8', flexShrink: 0 }} />
                  <Text
                    ellipsis
                    style={{
                      flex: 1, fontSize: 13,
                      color: currentConvId === conv.id ? '#1e293b' : '#475569',
                    }}
                  >
                    {conv.title || '新对话'}
                  </Text>
                  <Text style={{ fontSize: 10, color: '#cbd5e1', flexShrink: 0 }}>
                    {formatRelativeTime(conv.updated_at)}
                  </Text>
                </div>
              ))}
            </div>
          ))
        )}
      </div>

      {/* Footer - user info */}
      <div style={{
        padding: '10px 14px',
        borderTop: '1px solid #e2e8f0',
        display: 'flex',
        alignItems: 'center',
        gap: 8,
      }}>
        <div style={{
          width: 28, height: 28, borderRadius: '50%',
          background: '#4f46e5', display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 11, color: '#fff', fontWeight: 600,
        }}>
          {(user?.username || 'U')[0].toUpperCase()}
        </div>
        <Text style={{ flex: 1, fontSize: 12, color: '#475569' }} ellipsis>
          {user?.username || '用户'}
        </Text>
        <Button
          type="text"
          size="small"
          icon={<SettingOutlined />}
          onClick={onOpenSettings}
          style={{ color: currentView === 'settings' ? '#4f46e5' : '#94a3b8' }}
        />
        <Button
          type="text"
          size="small"
          icon={<LogoutOutlined />}
          onClick={logout}
          style={{ color: '#94a3b8' }}
        />
      </div>
    </div>
  )
}
