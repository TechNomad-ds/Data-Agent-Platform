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
  DownOutlined,
  AppstoreOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
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
  /** 当前活跃的数据空间（工作区）。undefined = 通用，不绑定空间 */
  selectedSpaceId: string | undefined
  /** 切换活跃工作区 */
  onSelectSpace: (id: string | undefined) => void
  /** 桌面端折叠为窄栏 */
  collapsed?: boolean
  /** 折叠 / 展开切换 */
  onToggleCollapse?: () => void
  /** 在移动端抽屉内渲染：填满容器宽高，操作按钮常显（适配触屏） */
  inDrawer?: boolean
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
  selectedSpaceId,
  onSelectSpace,
  collapsed = false,
  onToggleCollapse,
  inDrawer = false,
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

  // 工作区切换：选定空间后只展示该空间的会话（context 已由切换器表明，
  // 故隐藏组头）；未选定时展示全部并按空间分组（保留总览能力）。
  const visibleGroups = useMemo(() => {
    if (!selectedSpaceId) return grouped
    return grouped.filter((g) => g.spaceId === selectedSpaceId)
  }, [grouped, selectedSpaceId])
  const flatMode = !!selectedSpaceId

  const activeSpace = spaces.find((s) => s.id === selectedSpaceId)

  // 工作区切换器菜单：通用 + 各数据空间 + 管理入口
  const workspaceMenuItems = [
    {
      key: '__general__',
      label: '通用对话',
      icon: <MessageOutlined />,
      onClick: () => onSelectSpace(undefined),
    },
    ...(spaces.length
      ? [{ type: 'divider' as const }]
      : []),
    ...spaces.map((s) => ({
      key: s.id,
      label: s.name,
      icon: <FolderOutlined />,
      onClick: () => onSelectSpace(s.id),
    })),
    { type: 'divider' as const },
    {
      key: '__manage__',
      label: '管理数据空间',
      icon: <AppstoreOutlined />,
      onClick: onOpenDataManager,
    },
  ]

  // 账户菜单：仅保留设置与退出（数据管理/额度/后台为侧栏常驻导航，不收纳）
  const accountMenuItems = [
    {
      key: 'settings',
      label: '设置',
      icon: <SettingOutlined />,
      onClick: onOpenSettings,
    },
    { type: 'divider' as const },
    {
      key: 'logout',
      label: '退出登录',
      icon: <LogoutOutlined />,
      danger: true,
      onClick: logout,
    },
  ]

  const userInitial = (user?.username || 'U')[0].toUpperCase()

  // 折叠态：仅桌面端窄栏。展示展开/新建/工作区/头像四个核心动作。
  if (collapsed && !inDrawer) {
    return (
      <div
        style={{
          width: 56,
          height: '100vh',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 6,
          padding: '12px 0',
          background: colors.bgSubtle,
          borderRight: `1px solid ${colors.border}`,
          flexShrink: 0,
        }}
      >
        <Tooltip title="展开侧栏" placement="right">
          <Button type="text" icon={<MenuUnfoldOutlined />} onClick={onToggleCollapse} />
        </Tooltip>
        <Tooltip title="新对话" placement="right">
          <Button type="text" icon={<PlusOutlined />} onClick={onNewChat} />
        </Tooltip>
        <Dropdown menu={{ items: workspaceMenuItems }} trigger={['click']} placement="bottomLeft">
          <Tooltip title={activeSpace ? activeSpace.name : '通用对话'} placement="right">
            <Button
              type="text"
              icon={activeSpace
                ? <FolderOutlined style={{ color: colors.primary }} />
                : <MessageOutlined />}
            />
          </Tooltip>
        </Dropdown>
        <div style={{ margin: '6px 0', width: 24, borderTop: `1px solid ${colors.border}` }} />
        <Tooltip title="数据管理" placement="right">
          <Button
            type="text"
            icon={<DatabaseOutlined />}
            onClick={onOpenDataManager}
            style={{ color: currentView === 'data' ? colors.primary : undefined }}
          />
        </Tooltip>
        <Tooltip title="额度与 API" placement="right">
          <Button
            type="text"
            icon={<WalletOutlined />}
            onClick={onOpenCredits}
            style={{ color: currentView === 'credits' ? colors.primary : undefined }}
          />
        </Tooltip>
        {user?.role === 'admin' && (
          <Tooltip title="管理后台" placement="right">
            <Button
              type="text"
              icon={<CrownOutlined />}
              onClick={onOpenAdmin}
              style={{ color: currentView === 'admin' ? colors.primary : undefined }}
            />
          </Tooltip>
        )}
        <div style={{ flex: 1 }} />
        <Dropdown menu={{ items: accountMenuItems }} trigger={['click']} placement="topLeft">
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
              cursor: 'pointer',
            }}
          >
            {userInitial}
          </div>
        </Dropdown>
      </div>
    )
  }

  return (
    <div
      style={{
        width: inDrawer ? '100%' : 272,
        height: inDrawer ? '100%' : '100vh',
        display: 'flex',
        flexDirection: 'column',
        background: colors.bgSubtle,
        borderRight: inDrawer ? 'none' : `1px solid ${colors.border}`,
        flexShrink: 0,
      }}
    >
      {/* Header */}
      <div style={{ padding: '16px 12px 12px' }}>
        <div
          style={{
            marginBottom: 14,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <Logo size={24} />
          {!inDrawer && (
            <Tooltip title="收起侧栏" placement="right">
              <Button
                type="text"
                size="small"
                icon={<MenuFoldOutlined />}
                onClick={onToggleCollapse}
                style={{ color: colors.textMuted }}
              />
            </Tooltip>
          )}
        </div>

        {/* 工作区（数据空间）切换器 — 信息架构第一层级，对齐 Codex 的 project 概念 */}
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
              <div className="workspace-switcher-label">工作区</div>
              <div className="workspace-switcher-name">
                {activeSpace ? activeSpace.name : '通用对话'}
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

      <div style={{ margin: '4px 12px 8px', borderTop: `1px solid ${colors.border}` }} />

      {/* Navigation — 数据管理 / 额度 / 后台 常驻导航 */}
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

      {/* Footer — 账户菜单收纳次要导航（设置/额度/后台/退出） */}
      <Dropdown
        menu={{
          items: accountMenuItems,
          selectable: true,
          selectedKeys: [currentView],
        }}
        trigger={['click']}
        placement="topLeft"
      >
        <div
          className="sidebar-account"
          style={{
            padding: '10px 12px',
            margin: 8,
            borderRadius: 10,
            borderTop: 'none',
            display: 'flex',
            alignItems: 'center',
            gap: 10,
            cursor: 'pointer',
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
            {userInitial}
          </div>
          <Text
            style={{ flex: 1, fontSize: 13, color: colors.textSecondary }}
            ellipsis
          >
            {user?.username || '用户'}
          </Text>
          <MoreOutlined style={{ fontSize: 16, color: colors.textMuted }} />
        </div>
      </Dropdown>
    </div>
  )
}
