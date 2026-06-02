import { useState, useEffect, useMemo } from 'react'
import { Input, Button, Typography, Tooltip, Dropdown, Modal, message } from 'antd'
import {
  PlusOutlined,
  SearchOutlined,
  DatabaseOutlined,
  MessageOutlined,
  LogoutOutlined,
  SettingOutlined,
  MoreOutlined,
  EditOutlined,
  DeleteOutlined,
  WalletOutlined,
  CrownOutlined,
  FolderOutlined,
} from '@ant-design/icons'
import { chatApi, Conversation } from '@/api/chat'
import { dataSpacesApi, DataSpace } from '@/api/dataSpaces'
import { useAuthStore } from '@/stores/authStore'
import { MainView } from '@/components/Layout/MainLayout'
import Logo from '@/components/Layout/Logo'
import { colors } from '@/styles/tokens'

const { Text } = Typography

interface Props {
  currentConvId: string | undefined
  onNewChat: () => void
  onSelectConversation: (id: string) => void
  onOpenDataManager: () => void
  onOpenSettings: () => void
  onOpenCredits: () => void
  onOpenAdmin: () => void
  currentView: MainView
}

interface GroupedConversations {
  spaceName: string
  spaceId: string
  conversations: Conversation[]
  latestUpdate: number
}

export default function Sidebar({
  currentConvId,
  onNewChat,
  onSelectConversation,
  onOpenDataManager,
  onOpenSettings,
  onOpenCredits,
  onOpenAdmin,
  currentView,
}: Props) {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [spaces, setSpaces] = useState<DataSpace[]>([])
  const [searchText, setSearchText] = useState('')
  const [renameId, setRenameId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set())
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

  const handleDeleteConversation = async (id: string, e?: React.MouseEvent) => {
    e?.stopPropagation()
    Modal.confirm({
      title: '删除对话',
      content: '确定删除这个对话？删除后无法恢复。',
      okText: '删除',
      cancelText: '取消',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await chatApi.deleteConversation(id)
          message.success('已删除')
          loadConversations()
          if (currentConvId === id) onNewChat()
        } catch {
          message.error('删除失败')
        }
      },
    })
  }

  const handleRenameConversation = async (id: string) => {
    if (!renameValue.trim()) { setRenameId(null); return }
    try {
      await chatApi.renameConversation(id, renameValue.trim())
      message.success('已重命名')
      setRenameId(null)
      loadConversations()
    } catch {
      message.error('重命名失败')
    }
  }

  const grouped: GroupedConversations[] = useMemo(() => {
    const filtered = searchText
      ? conversations.filter((c) =>
          (c.title || '').toLowerCase().includes(searchText.toLowerCase())
        )
      : conversations

    const map = new Map<string, Conversation[]>()
    const general: Conversation[] = []
    for (const conv of filtered) {
      if (conv.data_space_id) {
        const key = conv.data_space_id
        if (!map.has(key)) map.set(key, [])
        map.get(key)!.push(conv)
      } else {
        general.push(conv)
      }
    }

    const result: GroupedConversations[] = []

    if (general.length > 0) {
      const sorted = [...general].sort(
        (a, b) =>
          new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
      )
      result.push({
        spaceId: '__general__',
        spaceName: '通用对话',
        conversations: sorted,
        latestUpdate: new Date(sorted[0].updated_at).getTime(),
      })
    }

    for (const [spaceId, convs] of map) {
      const space = spaces.find((s) => s.id === spaceId)
      const sorted = [...convs].sort(
        (a, b) =>
          new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
      )
      result.push({
        spaceId,
        spaceName: space?.name || '未知空间',
        conversations: sorted,
        latestUpdate: sorted.length
          ? new Date(sorted[0].updated_at).getTime()
          : 0,
      })
    }
    result.sort((a, b) => b.latestUpdate - a.latestUpdate)
    return result
  }, [conversations, spaces, searchText])

  return (
    <div
      style={{
        width: 272,
        height: '100vh',
        display: 'flex',
        flexDirection: 'column',
        background: colors.bgSubtle,
        borderRight: `1px solid ${colors.border}`,
        flexShrink: 0,
      }}
    >
      {/* Header */}
      <div style={{ padding: '16px 12px 12px' }}>
        <div style={{ marginBottom: 16 }}>
          <Logo size={24} />
        </div>

        <Button
          icon={<PlusOutlined />}
          block
          onClick={onNewChat}
          style={{
            height: 36,
            fontSize: 13.5,
            fontWeight: 500,
            borderRadius: 8,
            marginBottom: 10,
            background: colors.bgMuted,
            border: `1px solid ${colors.border}`,
            color: colors.textPrimary,
          }}
        >
          新对话
        </Button>

        <Input
          prefix={<SearchOutlined style={{ color: colors.textMuted }} />}
          placeholder="搜索对话"
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          allowClear
          style={{
            height: 32,
            background: '#ffffff',
            borderRadius: 8,
            fontSize: 13,
          }}
        />
      </div>

      {/* Navigation */}
      <div style={{ padding: '0 12px 8px' }}>
        <div
          className={`sidebar-item${currentView === 'data' ? ' active' : ''}`}
          onClick={onOpenDataManager}
        >
          <DatabaseOutlined style={{ fontSize: 14 }} />
          <span style={{ flex: 1 }}>数据管理</span>
        </div>
        <div
          className={`sidebar-item${currentView === 'credits' ? ' active' : ''}`}
          onClick={onOpenCredits}
        >
          <WalletOutlined style={{ fontSize: 14 }} />
          <span style={{ flex: 1 }}>额度与 API</span>
        </div>
        {user?.role === 'admin' && (
          <div
            className={`sidebar-item${currentView === 'admin' ? ' active' : ''}`}
            onClick={onOpenAdmin}
          >
            <CrownOutlined style={{ fontSize: 14 }} />
            <span style={{ flex: 1 }}>管理后台</span>
          </div>
        )}
      </div>

      <div style={{ margin: '0 12px 8px', borderTop: `1px solid ${colors.border}` }} />

      {/* Conversation history */}
      <div style={{ flex: 1, overflow: 'auto', padding: '0 12px 8px' }}>
        {grouped.length === 0 ? (
          <div
            style={{
              textAlign: 'center',
              padding: '40px 16px',
              color: colors.textMuted,
              fontSize: 13,
            }}
          >
            {searchText ? '没有匹配的对话' : '暂无对话记录'}
          </div>
        ) : (
          grouped.map((group) => {
            const COLLAPSED_LIMIT = 8
            const isExpanded = expandedGroups.has(group.spaceId)
            const displayConvs = isExpanded ? group.conversations : group.conversations.slice(0, COLLAPSED_LIMIT)
            const hasMore = group.conversations.length > COLLAPSED_LIMIT
            return (
            <div key={group.spaceId} style={{ marginBottom: 16 }}>
              <div
                style={{
                  padding: '6px 10px',
                  fontSize: 11.5,
                  fontWeight: 600,
                  color: group.spaceId === '__general__' ? colors.textMuted : colors.textSecondary,
                  letterSpacing: 0.2,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 7,
                  borderLeft: group.spaceId === '__general__'
                    ? `2px solid ${colors.borderStrong}`
                    : `2px solid ${colors.borderStrong}`,
                  marginBottom: 2,
                  borderRadius: '0 4px 4px 0',
                }}
              >
                {group.spaceId === '__general__' ? (
                  <MessageOutlined style={{ fontSize: 14 }} />
                ) : (
                  <FolderOutlined style={{ fontSize: 14 }} />
                )}
                <span
                  style={{
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {group.spaceName}
                </span>
              </div>

              {displayConvs.map((conv) => {
                const active = currentConvId === conv.id
                const isRenaming = renameId === conv.id
                return (
                  <div
                    key={conv.id}
                    onClick={() => !isRenaming && onSelectConversation(conv.id)}
                    className="conv-row"
                    style={{
                      padding: '7px 10px',
                      cursor: isRenaming ? 'default' : 'pointer',
                      background: active ? '#ececf1' : 'transparent',
                      borderRadius: 8,
                      display: 'flex',
                      alignItems: 'center',
                      gap: 8,
                      transition: 'background 0.12s',
                      marginBottom: 2,
                    }}
                    onMouseEnter={(e) => {
                      if (!active) e.currentTarget.style.background = '#ececf1'
                    }}
                    onMouseLeave={(e) => {
                      if (!active)
                        e.currentTarget.style.background = 'transparent'
                    }}
                  >
                    <MessageOutlined
                      style={{
                        fontSize: 12,
                        color: colors.textMuted,
                        flexShrink: 0,
                      }}
                    />
                    {isRenaming ? (
                      <Input
                        size="small"
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        onPressEnter={() => handleRenameConversation(conv.id)}
                        onBlur={() => handleRenameConversation(conv.id)}
                        autoFocus
                        onClick={(e) => e.stopPropagation()}
                        style={{ flex: 1, fontSize: 12 }}
                      />
                    ) : (
                      <Text
                        ellipsis
                        style={{
                          flex: 1,
                          fontSize: 13,
                          color: active
                            ? colors.textPrimary
                            : colors.textSecondary,
                          fontWeight: active ? 500 : 400,
                        }}
                      >
                        {conv.title || '新对话'}
                      </Text>
                    )}
                    {!isRenaming && (
                      <Dropdown
                        trigger={['click']}
                        menu={{
                          items: [
                            {
                              key: 'rename',
                              label: '重命名',
                              icon: <EditOutlined />,
                              onClick: ({ domEvent }) => {
                                domEvent.stopPropagation()
                                setRenameId(conv.id)
                                setRenameValue(conv.title || '')
                              },
                            },
                            {
                              key: 'delete',
                              label: '删除',
                              icon: <DeleteOutlined />,
                              danger: true,
                              onClick: ({ domEvent }) => {
                                domEvent.stopPropagation()
                                handleDeleteConversation(conv.id)
                              },
                            },
                          ],
                        }}
                      >
                        <MoreOutlined
                          onClick={(e) => e.stopPropagation()}
                          className="conv-more-btn"
                          style={{
                            fontSize: 12,
                            color: colors.textMuted,
                            flexShrink: 0,
                            padding: '2px 4px',
                            borderRadius: 4,
                            opacity: 0,
                            transition: 'opacity 0.15s',
                          }}
                        />
                      </Dropdown>
                    )}
                  </div>
                )
              })}
              {hasMore && (
                <div
                  onClick={() => {
                    const next = new Set(expandedGroups)
                    if (isExpanded) next.delete(group.spaceId)
                    else next.add(group.spaceId)
                    setExpandedGroups(next)
                  }}
                  style={{
                    padding: '5px 10px',
                    fontSize: 11.5,
                    color: colors.textMuted,
                    cursor: 'pointer',
                    textAlign: 'center',
                    borderRadius: 6,
                    transition: 'color 0.15s',
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.color = colors.textSecondary }}
                  onMouseLeave={(e) => { e.currentTarget.style.color = colors.textMuted }}
                >
                  {isExpanded ? '收起' : `展开全部 ${group.conversations.length} 条对话`}
                </div>
              )}
            </div>
          )})
        )}
      </div>

      {/* Footer */}
      <div
        style={{
          padding: '12px',
          borderTop: `1px solid ${colors.border}`,
          display: 'flex',
          alignItems: 'center',
          gap: 10,
        }}
      >
        <div
          style={{
            width: 30,
            height: 30,
            borderRadius: '50%',
            background: colors.userAvatar,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 12,
            color: '#fff',
            fontWeight: 600,
            flexShrink: 0,
          }}
        >
          {(user?.username || 'U')[0].toUpperCase()}
        </div>
        <Text
          style={{ flex: 1, fontSize: 13, color: colors.textSecondary }}
          ellipsis
        >
          {user?.username || '用户'}
        </Text>
        <Tooltip title="设置" placement="top">
          <Button
            type="text"
            size="small"
            icon={<SettingOutlined />}
            onClick={onOpenSettings}
            style={{
              color:
                currentView === 'settings'
                  ? colors.primary
                  : colors.textMuted,
            }}
          />
        </Tooltip>
        <Tooltip title="退出登录" placement="top">
          <Button
            type="text"
            size="small"
            icon={<LogoutOutlined />}
            onClick={logout}
            style={{ color: colors.textMuted }}
          />
        </Tooltip>
      </div>
    </div>
  )
}
