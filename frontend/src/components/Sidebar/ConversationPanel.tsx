import { useState, useEffect, useMemo } from 'react'
import { Input, Button, Typography, Dropdown, Modal, message, Checkbox } from 'antd'
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
  CheckOutlined,
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
  /** 切换活跃项目（单选，保留兼容） */
  onSelectSpace: (id: string | undefined) => void
  /** 多项目：当前选中的全部项目 id（含主空间）。空数组 = 普通对话 */
  selectedSpaceIds?: string[]
  /** 多项目：更新选中的项目集合 */
  onSelectSpaces?: (ids: string[]) => void
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
  selectedSpaceIds,
  onSelectSpaces,
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

  // 多项目：归一化当前选中集合。优先用 selectedSpaceIds，回退到单选 selectedSpaceId。
  const selectedIds: string[] = (selectedSpaceIds && selectedSpaceIds.length)
    ? selectedSpaceIds
    : (selectedSpaceId ? [selectedSpaceId] : [])
  const selectedSet = new Set(selectedIds)
  const selectedSpaceObjs = selectedIds
    .map((id) => spaces.find((s) => s.id === id))
    .filter(Boolean) as DataSpace[]

  // 勾选/取消某项目：维护选中集合（保持顺序，先选的在前=主空间）。
  // 选中任意项目即退出「普通对话」；取消到空集合即回到普通对话。
  const toggleSpace = (id: string) => {
    const next = selectedSet.has(id)
      ? selectedIds.filter((x) => x !== id)
      : [...selectedIds, id]
    if (onSelectSpaces) onSelectSpaces(next)
    else onSelectSpace(next[0])
  }
  const selectGeneral = () => {
    if (onSelectSpaces) onSelectSpaces([])
    else onSelectSpace(undefined)
  }

  // 切换器顶部展示文案
  const switcherLabel = selectedSpaceObjs.length === 0
    ? '普通对话'
    : selectedSpaceObjs.length === 1
      ? selectedSpaceObjs[0].name
      : `${selectedSpaceObjs.length} 个项目`
  const switcherSub = selectedSpaceObjs.length === 0
    ? '不分析文件，直接聊'
    : selectedSpaceObjs.length === 1
      ? `项目 · ${selectedSpaceObjs[0].file_count} 个文件`
      : `共 ${selectedSpaceObjs.reduce((n, s) => n + (s.file_count || 0), 0)} 个文件`

  // 多选下拉面板（用受控 open，避免点 checkbox 即关闭）
  const switcherPanel = (
    <div style={{
      width: 260, maxHeight: 360, overflowY: 'auto', padding: 6,
      background: '#fff', borderRadius: 10, border: `1px solid ${colors.border}`,
      boxShadow: '0 6px 24px rgba(15,23,42,0.12)',
    }}>
      <div
        onClick={selectGeneral}
        style={{
          display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px',
          borderRadius: 8, cursor: 'pointer',
          background: selectedSpaceObjs.length === 0 ? colors.bgMuted : 'transparent',
        }}
      >
        <MessageOutlined style={{ color: colors.textMuted }} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 13 }}>普通对话</div>
          <div style={{ fontSize: 11, color: colors.textMuted }}>不分析你的文件，直接和 AI 聊</div>
        </div>
        {selectedSpaceObjs.length === 0 && <CheckOutlined style={{ color: colors.primary, fontSize: 12 }} />}
      </div>
      {spaces.length > 0 && <div style={{ height: 1, background: colors.border, margin: '6px 4px' }} />}
      {spaces.length > 0 && (
        <div style={{ fontSize: 11, color: colors.textMuted, padding: '2px 10px 6px' }}>
          可多选项目，一起对话
        </div>
      )}
      {spaces.map((s) => {
        const checked = selectedSet.has(s.id)
        return (
          <label
            key={s.id}
            style={{
              display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px',
              borderRadius: 8, cursor: 'pointer',
              background: checked ? colors.bgMuted : 'transparent',
            }}
          >
            <Checkbox checked={checked} onChange={() => toggleSpace(s.id)} />
            <FolderOutlined style={{ color: checked ? colors.primary : colors.textMuted }} />
            <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 13 }}>
              {s.name}
            </span>
            <span style={{ fontSize: 11, color: colors.textMuted, flexShrink: 0 }}>{s.file_count} 个文件</span>
          </label>
        )
      })}
      <div style={{ height: 1, background: colors.border, margin: '6px 4px' }} />
      <div
        onClick={onOpenDataManager}
        style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px', borderRadius: 8, cursor: 'pointer' }}
      >
        <AppstoreOutlined style={{ color: colors.textMuted }} />
        <span style={{ fontSize: 13 }}>管理项目</span>
      </div>
    </div>
  )

  return (
    <div
      style={{
        width: inDrawer ? '100%' : 'clamp(264px, 18vw, 340px)',
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
        {/* 项目切换器 — 对话页一级上下文，支持多选项目一起对话 */}
        <Dropdown
          popupRender={() => switcherPanel}
          trigger={['click']}
          placement="bottomLeft"
        >
          <div className="workspace-switcher">
            <span
              className="workspace-switcher-icon"
              style={{ color: selectedSpaceObjs.length ? colors.primary : colors.textMuted }}
            >
              {selectedSpaceObjs.length ? <FolderOutlined /> : <MessageOutlined />}
            </span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="workspace-switcher-label">
                {switcherSub}
              </div>
              <div className="workspace-switcher-name">
                {switcherLabel}
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
