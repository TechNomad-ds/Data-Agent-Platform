import { useState, useEffect, useMemo } from 'react'
import { Input, Button, Typography, Dropdown, Modal, message } from 'antd'
import {
  PlusOutlined,
  SearchOutlined,
  MessageOutlined,
  MoreOutlined,
  EditOutlined,
  DeleteOutlined,
  FolderOutlined,
  DownOutlined,
  AppstoreOutlined,
} from '@ant-design/icons'
import { chatApi, Conversation } from '@/api/chat'
import { dataSpacesApi, DataSpace } from '@/api/dataSpaces'
import { colors } from '@/styles/tokens'

const { Text } = Typography

interface Props {
  currentConvId: string | undefined
  onNewChat: () => void
  onSelectConversation: (id: string) => void
  /** 打开数据管理（用于"管理项目"入口） */
  onOpenDataManager: () => void
  /** 当前活跃的项目。undefined = 通用，不绑定项目 */
  selectedSpaceId: string | undefined
  /** 切换活跃项目 */
  onSelectSpace: (id: string | undefined) => void
  /** 在移动端抽屉内渲染：填满容器宽高，操作按钮常显（适配触屏） */
  inDrawer?: boolean
}

interface GroupedConversations {
  spaceName: string
  spaceId: string
  conversations: Conversation[]
  latestUpdate: number
}

export default function ConversationPanel({
  currentConvId,
  onNewChat,
  onSelectConversation,
  onOpenDataManager,
  selectedSpaceId,
  onSelectSpace,
  inDrawer = false,
}: Props) {
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [spaces, setSpaces] = useState<DataSpace[]>([])
  const [searchText, setSearchText] = useState('')
  const [renameId, setRenameId] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set())

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
        spaceName: '普通对话',
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
        spaceName: space?.name || '未知项目',
        conversations: sorted,
        latestUpdate: sorted.length
          ? new Date(sorted[0].updated_at).getTime()
          : 0,
      })
    }
    result.sort((a, b) => b.latestUpdate - a.latestUpdate)
    return result
  }, [conversations, spaces, searchText])

  // 项目切换：选定空间后只展示该空间的会话（context 已由切换器表明，
  // 故隐藏组头）；未选定时展示全部并按空间分组（保留总览能力）。
  const visibleGroups = useMemo(() => {
    if (!selectedSpaceId) return grouped
    return grouped.filter((g) => g.spaceId === selectedSpaceId)
  }, [grouped, selectedSpaceId])
  const flatMode = !!selectedSpaceId

  const activeSpace = spaces.find((s) => s.id === selectedSpaceId)

  // 项目切换器菜单：通用 + 各项目（带文件数）+ 管理入口。
  // 这是全局唯一切换项目的入口（对话页顶栏只读展示，不再切换）。
  const workspaceMenuItems = [
    {
      key: '__general__',
      label: (
        <span style={{ display: 'inline-flex', flexDirection: 'column', lineHeight: 1.3, padding: '1px 0' }}>
          <span>普通对话</span>
          <span style={{ fontSize: 11, color: colors.textMuted }}>不分析你的文件，直接和 AI 聊</span>
        </span>
      ),
      icon: <MessageOutlined />,
      onClick: () => onSelectSpace(undefined),
    },
    ...(spaces.length ? [{ type: 'divider' as const }] : []),
    ...spaces.map((s) => ({
      key: s.id,
      label: (
        <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'space-between', width: '100%', gap: 12 }}>
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.name}</span>
          <span style={{ fontSize: 11, color: colors.textMuted, flexShrink: 0 }}>{s.file_count} 个文件</span>
        </span>
      ),
      icon: <FolderOutlined />,
      onClick: () => onSelectSpace(s.id),
    })),
    { type: 'divider' as const },
    {
      key: '__manage__',
      label: '管理项目',
      icon: <AppstoreOutlined />,
      onClick: onOpenDataManager,
    },
  ]

  return (
    <div
      style={{
        width: inDrawer ? '100%' : 264,
        height: inDrawer ? '100%' : '100vh',
        display: 'flex',
        flexDirection: 'column',
        background: colors.bgSubtle,
        borderRight: inDrawer ? 'none' : `1px solid ${colors.border}`,
        flexShrink: 0,
      }}
    >
      {/* Header：项目切换器 + 新对话 + 搜索 */}
      <div style={{ padding: inDrawer ? '8px 12px 12px' : '16px 12px 12px' }}>
        {/* 项目切换器 — 对话页一级上下文，切换后下方历史随之过滤 */}
        <Dropdown
          menu={{ items: workspaceMenuItems }}
          trigger={['click']}
          placement="bottomLeft"
        >
          <div className="workspace-switcher">
            <span
              className="workspace-switcher-icon"
              style={{ color: activeSpace ? colors.primary : colors.textMuted }}
            >
              {activeSpace ? <FolderOutlined /> : <MessageOutlined />}
            </span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="workspace-switcher-label">
                {activeSpace ? `项目 · ${activeSpace.file_count} 个文件` : '项目'}
              </div>
              <div className="workspace-switcher-name">
                {activeSpace ? activeSpace.name : '普通对话'}
              </div>
            </div>
            <DownOutlined style={{ fontSize: 10, color: colors.textMuted }} />
          </div>
        </Dropdown>

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

      <div style={{ margin: '0 12px 8px', borderTop: `1px solid ${colors.border}` }} />

      {/* Conversation history */}
      <div style={{ flex: 1, overflow: 'auto', padding: '0 12px 8px' }}>
        {visibleGroups.length === 0 ? (
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
          visibleGroups.map((group) => {
            const COLLAPSED_LIMIT = 8
            const isExpanded = expandedGroups.has(group.spaceId)
            const displayConvs = isExpanded ? group.conversations : group.conversations.slice(0, COLLAPSED_LIMIT)
            const hasMore = group.conversations.length > COLLAPSED_LIMIT
            return (
            <div key={group.spaceId} style={{ marginBottom: 16 }}>
              {!flatMode && (
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
                  borderLeft: `2px solid ${colors.borderStrong}`,
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
              )}

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
                      if (!active) e.currentTarget.style.background = 'transparent'
                    }}
                  >
                    <MessageOutlined
                      style={{ fontSize: 12, color: colors.textMuted, flexShrink: 0 }}
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
                          color: active ? colors.textPrimary : colors.textSecondary,
                          fontWeight: active ? 500 : 400,
                        }}
                      >
                        {conv.channel && conv.channel !== 'web' && (
                          <span
                            style={{ marginRight: 4 }}
                            title={`来自${conv.channel === 'weixin' ? '微信' : conv.channel === 'feishu' ? '飞书' : conv.channel}`}
                          >
                            {conv.channel === 'weixin' ? '💬' : conv.channel === 'feishu' ? '🪶' : '🔗'}
                          </span>
                        )}
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
                            opacity: inDrawer ? 1 : 0,
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

    </div>
  )
}
