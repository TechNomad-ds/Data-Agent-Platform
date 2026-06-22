import { useState, useEffect, useRef, useCallback } from 'react'
import { Input, Button, Select, Typography, Spin, message, Tooltip } from 'antd'
import {
  SendOutlined,
  StopOutlined,
  LockOutlined,
  DatabaseOutlined,
  ArrowDownOutlined,
} from '@ant-design/icons'
import { chatApi, Message, SSEEvent } from '@/api/chat'
import { dataSpacesApi, DataSpace } from '@/api/dataSpaces'
import { settingsApi, ModelOption } from '@/api/settings'
import { useChatStore } from '@/stores/chatStore'
import { useAuthStore } from '@/stores/authStore'
import { useIsMobile } from '@/hooks/useIsMobile'
import MessageContent from '@/components/Chat/MessageContent'
import MarkdownRenderer from '@/components/Chat/MarkdownRenderer'
import ThinkingBlock from '@/components/Chat/ThinkingBlock'
import PlanCard from '@/components/Chat/PlanCard'
import ExportButton from '@/components/Chat/ExportButton'
import api from '@/api/client'
import { colors } from '@/styles/tokens'

const { Text } = Typography
const { TextArea } = Input

const FALLBACK_MODELS: ModelOption[] = [
  { id: 'deepseek-v4-flash', display_name: 'DeepSeek V4 Flash', model_name: 'deepseek-v4-flash', provider: 'deepseek', source: 'platform', credit_multiplier: 1.0 },
]

const DEFAULT_SUGGESTIONS = [
  '帮我看看数据空间里有什么文件',
  '帮我概述一下数据的整体情况',
  '帮我做一个关键指标的统计摘要',
  '数据中有哪些值得关注的趋势或规律？',
]

const READING_WIDTH = 760

interface Props {
  selectedSpaceId: string | undefined
  conversationId: string | undefined
  onConversationCreated: (id: string) => void
  onConversationDeleted?: () => void
  onSpaceChange: (id: string | undefined) => void
  spaceLockedByConversation?: boolean
}

// AI 大头像 — 用于空状态
function HeroMark() {
  return (
    <div
      style={{
        width: 56,
        height: 56,
        borderRadius: 16,
        background: colors.aiAvatar,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        margin: '0 auto 18px',
        boxShadow: '0 6px 20px rgba(79, 70, 229, 0.22)',
      }}
    >
      <svg width="28" height="28" viewBox="0 0 24 24" fill="none" aria-hidden>
        <path
          d="M12 2.5L13.5 9L20 10.5L13.5 12L12 18.5L10.5 12L4 10.5L10.5 9L12 2.5Z"
          fill="#ffffff"
        />
        <circle cx="12" cy="20.5" r="1.5" fill="#ffffff" opacity="0.7" />
      </svg>
    </div>
  )
}

export default function ChatView({
  selectedSpaceId,
  conversationId,
  onConversationCreated,
  onConversationDeleted,
  onSpaceChange,
  spaceLockedByConversation = false,
}: Props) {
  const {
    setCurrentConversation,
    messages,
    setMessages,
    segments,
    isStreaming,
    streamingConversationId,
    setIsStreaming,
    setStreamingConversationId,
    appendStreamDelta,
    appendThinkingDelta,
    addToolEvent,
    updatePlan,
    resetStream,
    setAbortController,
    stopStreaming,
  } = useChatStore()

  const [spaces, setSpaces] = useState<DataSpace[]>([])
  const [models, setModels] = useState<ModelOption[]>([])
  const [selectedModel, setSelectedModel] = useState<string>('')
  const isMobile = useIsMobile()
  const [inputValue, setInputValue] = useState('')
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [inputFocused, setInputFocused] = useState(false)
  const [loadingConversation, setLoadingConversation] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  // 用户是否贴在底部（决定流式时是否自动跟随滚动）
  const stickToBottomRef = useRef(true)
  const [showScrollToBottom, setShowScrollToBottom] = useState(false)
  const sseBufferRef = useRef('')
  const savedMsgIdRef = useRef<string | null>(null)
  const creditsUsedRef = useRef<number | null>(null)
  const activeStreamConvIdRef = useRef<string | null>(null)
  // 刚在本地创建的对话 id：conversationId 变化时不要再拉取服务端快照，
  // 否则会与发送请求竞态、把本地乐观插入的用户消息覆盖掉
  const justCreatedConvRef = useRef<string | null>(null)

  useEffect(() => {
    loadSpaces()
    loadModels()
  }, [])

  useEffect(() => {
    if (conversationId) {
      // 本地刚创建的对话：消息已在 state 中（含乐观插入的用户消息），跳过拉取
      if (justCreatedConvRef.current === conversationId) {
        justCreatedConvRef.current = null
        return
      }
      loadConversation(conversationId)
    } else {
      setCurrentConversation(null)
      setMessages([])
    }
  }, [conversationId])

  useEffect(() => {
    // 仅当用户贴在底部时才自动跟随；往上翻看历史时不打扰
    if (stickToBottomRef.current) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages, segments])

  // 切换对话时重置为贴底，并跳到最新消息
  useEffect(() => {
    stickToBottomRef.current = true
    setShowScrollToBottom(false)
    requestAnimationFrame(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: 'auto' })
    })
  }, [conversationId])

  const BOTTOM_THRESHOLD = 80

  const handleScroll = useCallback(() => {
    const el = scrollContainerRef.current
    if (!el) return
    const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    const atBottom = distanceFromBottom <= BOTTOM_THRESHOLD
    stickToBottomRef.current = atBottom
    setShowScrollToBottom(!atBottom)
  }, [])

  const scrollToBottom = useCallback(() => {
    stickToBottomRef.current = true
    setShowScrollToBottom(false)
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  useEffect(() => {
    if (selectedSpaceId) {
      loadSpaces()
      loadSuggestions()
    } else {
      setSuggestions(DEFAULT_SUGGESTIONS)
    }
  }, [selectedSpaceId])


  const loadSpaces = async (retry = 2) => {
    try {
      setSpaces((await dataSpacesApi.list()).data)
    } catch {
      if (retry > 0) setTimeout(() => loadSpaces(retry - 1), 2000)
    }
  }

  const loadModels = async () => {
    try {
      const res = await settingsApi.listModels()
      const available = res.data.length > 0 ? res.data : FALLBACK_MODELS
      setModels(available)
      if (available.length > 0 && !selectedModel) setSelectedModel(available[0].id)
    } catch {
      setModels(FALLBACK_MODELS)
      if (!selectedModel) setSelectedModel(FALLBACK_MODELS[0].id)
    }
  }

  const loadConversation = async (id: string) => {
    setLoadingConversation(true)
    try {
      const res = await chatApi.getConversation(id)
      setCurrentConversation(res.data)
      setMessages(res.data.messages)
      setSelectedModel(res.data.model_id)
    } catch {}
    finally { setLoadingConversation(false) }
  }

  const loadSuggestions = async () => {
    try {
      const res = await api.get(`/data-spaces/${selectedSpaceId}/suggestions`)
      const items = res.data.suggestions || []
      setSuggestions(items.length > 0 ? items : DEFAULT_SUGGESTIONS)
    } catch {
      setSuggestions(DEFAULT_SUGGESTIONS)
    }
  }

  const parseSSELine = useCallback(
    (line: string) => {
      if (!line.startsWith('data: ')) return
      const data = line.slice(6)
      if (data === '[DONE]') return
      try {
        const event: SSEEvent = JSON.parse(data)
        switch (event.type) {
          case 'text':
            if (event.delta) appendStreamDelta(event.delta)
            break
          case 'thinking':
            if (event.content) appendThinkingDelta(event.content)
            break
          case 'tool_use':
          case 'tool_result':
            addToolEvent(event)
            break
          case 'plan':
            if (event.steps) updatePlan(event.steps)
            break
          case 'done':
            if (event.credits_used != null) creditsUsedRef.current = event.credits_used
            break
          case 'saved':
            if (event.message_id) savedMsgIdRef.current = event.message_id
            break
          case 'error':
            message.error(event.message || 'Agent 执行出错')
            break
          case 'conversation_deleted':
            if (activeStreamConvIdRef.current === useChatStore.getState().currentConversation?.id) {
              setMessages([])
              setCurrentConversation(null)
              onConversationDeleted?.()
            }
            break
        }
      } catch {}
    },
    [appendStreamDelta, appendThinkingDelta, addToolEvent, updatePlan, setMessages, setCurrentConversation, onConversationDeleted]
  )

  const handleSendWithContent = async (content: string) => {
    if (!content.trim() || isStreaming) return
    if (!selectedModel) { message.warning('请先选择模型'); return }
    let convId = conversationId
    if (!convId) {
      try {
        const res = await chatApi.createConversation({ data_space_id: selectedSpaceId, model_id: selectedModel })
        setCurrentConversation(res.data)
        justCreatedConvRef.current = res.data.id
        onConversationCreated(res.data.id)
        convId = res.data.id
      } catch { message.error('创建对话失败'); return }
    }
    await sendMessage(convId, content)
  }

  const handleSend = async () => {
    if (!inputValue.trim() || isStreaming) return
    if (!selectedModel) {
      message.warning('请先选择模型')
      return
    }

    let convId = conversationId
    if (!convId) {
      try {
        const res = await chatApi.createConversation({
          data_space_id: selectedSpaceId,
          model_id: selectedModel,
        })
        setCurrentConversation(res.data)
        justCreatedConvRef.current = res.data.id
        onConversationCreated(res.data.id)
        convId = res.data.id
      } catch {
        message.error('创建对话失败')
        return
      }
    }
    await sendMessage(convId, inputValue)
  }

  const sendMessage = async (convId: string, content: string, skipAddUserMsg = false) => {
    // 发送/重新生成时回到底部并恢复跟随
    stickToBottomRef.current = true
    setShowScrollToBottom(false)
    if (!skipAddUserMsg) {
      const userMsg: Message = {
        id: Date.now().toString(),
        role: 'user',
        content,
        tool_calls: null,
        token_usage: null,
        credits_used: null,
        created_at: new Date().toISOString(),
      }
      setMessages([...useChatStore.getState().messages, userMsg])
    }
    setInputValue('')
    resetStream()
    setIsStreaming(true)
    setStreamingConversationId(convId)
    activeStreamConvIdRef.current = convId
    savedMsgIdRef.current = null
    creditsUsedRef.current = null
    const controller = new AbortController()
    setAbortController(controller)

    try {
      const response = await chatApi.sendMessage(
        convId,
        content,
        controller.signal,
        selectedModel
      )
      if (!response.ok) {
        if (response.status === 401) {
          useAuthStore.getState().logout()
        }
        throw new Error()
      }
      const reader = response.body?.getReader()
      const decoder = new TextDecoder()
      if (!reader) return
      sseBufferRef.current = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        sseBufferRef.current += decoder.decode(value, { stream: true })
        const lines = sseBufferRef.current.split('\n\n')
        sseBufferRef.current = lines.pop() || ''
        for (const block of lines) {
          for (const line of block.split('\n')) {
            parseSSELine(line.trim())
          }
        }
      }
      sseBufferRef.current += decoder.decode()
      if (sseBufferRef.current.trim()) {
        for (const line of sseBufferRef.current.split('\n')) {
          parseSSELine(line.trim())
        }
      }
      sseBufferRef.current = ''

      const state = useChatStore.getState()
      const finalContent = state.segments
        .filter((s) => s.type === 'text')
        .map((s) => s.content || '')
        .join('')
      // 即便没有 text 段（只有工具调用），也要把 tool_calls 留下，避免内容丢失
      if (finalContent || state.segments.length > 0) {
        if (useChatStore.getState().currentConversation?.id === convId) {
          const assistantMsg: Message = {
            id: savedMsgIdRef.current || (Date.now() + 1).toString(),
            role: 'assistant',
            content: finalContent,
            tool_calls: state.segments,
            token_usage: null,
            credits_used: creditsUsedRef.current,
            created_at: new Date().toISOString(),
          }
          setMessages([...useChatStore.getState().messages, assistantMsg])
        }
      }
    } catch (err: any) {
      if (err.name !== 'AbortError') message.error('发送失败')
    } finally {
      setIsStreaming(false)
      setStreamingConversationId(null)
      activeStreamConvIdRef.current = null
      setAbortController(null)
      resetStream()
    }
  }

  const handleRegenerate = useCallback(() => {
    if (isStreaming || !conversationId) return
    const currentMessages = useChatStore.getState().messages
    const userMessages = currentMessages.filter((m) => m.role === 'user')
    const lastUserMsg = userMessages[userMessages.length - 1]
    if (!lastUserMsg?.content) return
    const newMessages = currentMessages.slice(0, currentMessages.lastIndexOf(lastUserMsg) + 1)
    setMessages(newMessages)
    sendMessage(conversationId, lastUserMsg.content, true)
  }, [isStreaming, conversationId, selectedModel])

  const handleFeedback = useCallback(
    async (messageId: string, rating: number) => {
      try {
        await api.post('/feedback', { message_id: messageId, rating })
      } catch {}
    },
    []
  )

  const showStreaming = isStreaming && streamingConversationId === conversationId
  const showEmpty = messages.length === 0 && !showStreaming
  const inputDisabled = isStreaming

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        background: colors.bg,
      }}
    >
      {/* Top bar */}
      <div
        style={{
          padding: isMobile ? '8px 12px' : '10px 24px',
          borderBottom: `1px solid ${colors.border}`,
          background: colors.surface,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          minHeight: 56,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {spaceLockedByConversation && selectedSpaceId ? (
            <Tooltip title="此对话已绑定数据空间，不可切换" placement="bottom">
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '6px 12px',
                  borderRadius: 8,
                  background: colors.bgSubtle,
                  border: `1px solid ${colors.border}`,
                }}
              >
                <DatabaseOutlined
                  style={{ fontSize: 12, color: colors.textSecondary }}
                />
                <span
                  style={{
                    fontSize: 13,
                    color: colors.textPrimary,
                    fontWeight: 500,
                  }}
                >
                  {spaces.find((s) => s.id === selectedSpaceId)?.name ||
                    '数据空间'}
                </span>
                <LockOutlined
                  style={{ fontSize: 10, color: colors.textMuted }}
                />
              </div>
            </Tooltip>
          ) : (
            <Select
              value={spaces.some((s) => s.id === selectedSpaceId) ? selectedSpaceId : undefined}
              onChange={onSpaceChange}
              placeholder="数据空间"
              style={{ minWidth: isMobile ? 100 : 140 }}
              popupMatchSelectWidth={false}
              variant="borderless"
              options={spaces.map((s) => ({ label: s.name, value: s.id }))}
            />
          )}
          <span style={{ color: colors.border }}>|</span>
          <Select
            value={selectedModel || undefined}
            onChange={setSelectedModel}
            placeholder="模型"
            style={{ minWidth: isMobile ? 110 : 160, maxWidth: isMobile ? 160 : 320 }}
            variant="borderless"
            popupMatchSelectWidth={false}
            optionLabelProp="label"
            options={models.map((m) => ({
              label: m.display_name,
              value: m.id,
            }))}
          />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <ExportButton conversationId={conversationId} />
        </div>
      </div>

      {/* Messages */}
      <div
        ref={scrollContainerRef}
        onScroll={handleScroll}
        style={{ flex: 1, overflow: 'auto', position: 'relative' }}
      >
        <div
          style={{
            maxWidth: READING_WIDTH,
            margin: '0 auto',
            padding: showEmpty ? '0 24px' : isMobile ? '20px 14px 16px' : '32px 24px 24px',
          }}
        >
          {loadingConversation ? (
            <div style={{ textAlign: 'center', paddingTop: 120 }}>
              <Spin />
              <div style={{ marginTop: 12, color: colors.textMuted, fontSize: 13 }}>加载对话...</div>
            </div>
          ) : showEmpty ? (
            <div style={{ textAlign: 'center', paddingTop: 96 }}>
              <HeroMark />
              <Text
                style={{
                  fontSize: 22,
                  fontWeight: 600,
                  color: colors.textPrimary,
                  display: 'block',
                  marginBottom: 6,
                  letterSpacing: -0.3,
                }}
              >
                有什么可以帮你分析的？
              </Text>
              <Text
                style={{
                  fontSize: 14,
                  color: colors.textMuted,
                  display: 'block',
                  marginBottom: 36,
                }}
              >
                {selectedSpaceId
                  ? '基于你的数据，试试下面这些方向'
                  : '选择数据空间后可分析数据，也可以直接提问'}
              </Text>

              {suggestions.length > 0 ? (
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: isMobile ? '1fr' : 'repeat(2, 1fr)',
                    gap: 10,
                    maxWidth: 600,
                    margin: '0 auto',
                  }}
                >
                  {suggestions.slice(0, 4).map((q) => (
                    <div
                      key={q}
                      onClick={() => { if (!isStreaming && selectedModel) { setInputValue(''); handleSendWithContent(q) } else { setInputValue(q) } }}
                      style={{
                        padding: '14px 16px',
                        borderRadius: 12,
                        border: `1px solid ${colors.border}`,
                        background: colors.surface,
                        cursor: 'pointer',
                        textAlign: 'left',
                        fontSize: 13.5,
                        color: colors.textSecondary,
                        lineHeight: 1.55,
                        transition: 'all 0.15s',
                      }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.borderColor = colors.borderStrong
                        e.currentTarget.style.background = colors.bgMuted
                        e.currentTarget.style.color = colors.textPrimary
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.borderColor = colors.border
                        e.currentTarget.style.background = colors.surface
                        e.currentTarget.style.color = colors.textSecondary
                      }}
                    >
                      {q}
                    </div>
                  ))}
                </div>
              ) : null}
            </div>
          ) : (
            <>
              {messages.map((msg, idx) => (
                <div key={msg.id} style={{ marginBottom: 28 }}>
                  <MessageContent
                    message={msg}
                    onRegenerate={
                      msg.role === 'assistant' && idx === messages.length - 1 && !isStreaming
                        ? handleRegenerate
                        : undefined
                    }
                    onFeedback={msg.role === 'assistant' ? handleFeedback : undefined}
                  />
                </div>
              ))}
              {showStreaming && (
                <div
                  style={{
                    marginBottom: 24,
                    display: 'flex',
                    gap: 12,
                    alignItems: 'flex-start',
                  }}
                >
                  <div
                    style={{
                      width: 30,
                      height: 30,
                      borderRadius: 8,
                      background: colors.aiAvatar,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      flexShrink: 0,
                      boxShadow: '0 1px 2px rgba(15, 23, 42, 0.06)',
                    }}
                  >
                    <svg
                      width="16"
                      height="16"
                      viewBox="0 0 24 24"
                      fill="none"
                      aria-hidden
                    >
                      <path
                        d="M12 2.5L13.5 9L20 10.5L13.5 12L12 18.5L10.5 12L4 10.5L10.5 9L12 2.5Z"
                        fill="#ffffff"
                      />
                    </svg>
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    {segments.length === 0 && (
                      <div
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: 8,
                          padding: '6px 0',
                        }}
                      >
                        <Spin size="small" />
                        <Text
                          style={{ fontSize: 13, color: colors.textSecondary }}
                        >
                          思考中…
                        </Text>
                      </div>
                    )}
                    {segments.map((seg, i) =>
                      seg.type === 'text' ? (
                        <div
                          key={i}
                          className="markdown-body"
                          style={{ marginBottom: 8 }}
                        >
                          <MarkdownRenderer content={seg.content || ''} />
                          {/* 流式中显示输入光标 */}
                          {i === segments.length - 1 && (
                            <span className="typing-dot" />
                          )}
                        </div>
                      ) : seg.type === 'thinking' ? (
                        <div key={i} style={{ marginBottom: 10 }}>
                          <ThinkingBlock
                            thinkingText={seg.content || ''}
                            toolEvents={[]}
                            defaultExpanded={false}
                          />
                        </div>
                      ) : seg.type === 'plan' ? (
                        <div key={i} style={{ marginBottom: 10 }}>
                          <PlanCard steps={seg.steps || []} />
                        </div>
                      ) : (
                        <div key={i} style={{ marginBottom: 10 }}>
                          <ThinkingBlock
                            toolEvents={seg.events || []}
                            defaultExpanded={true}
                          />
                        </div>
                      )
                    )}
                  </div>
                </div>
              )}
            </>
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input */}
      <div style={{ padding: isMobile ? '8px 12px 14px' : '8px 24px 22px', background: colors.bg, position: 'relative' }}>
        {/* 回到底部悬浮按钮 — 仅在未贴底时显示 */}
        {showScrollToBottom && !showEmpty && (
          <Tooltip title="回到底部">
            <Button
              shape="circle"
              icon={<ArrowDownOutlined />}
              onClick={scrollToBottom}
              style={{
                position: 'absolute',
                top: -48,
                left: '50%',
                transform: 'translateX(-50%)',
                width: 36,
                height: 36,
                background: colors.surface,
                borderColor: colors.border,
                color: colors.textSecondary,
                boxShadow: '0 2px 10px rgba(15, 23, 42, 0.12)',
                zIndex: 5,
              }}
            />
          </Tooltip>
        )}
        <div
          style={{
            maxWidth: READING_WIDTH,
            margin: '0 auto',
            background: colors.surface,
            borderRadius: 18,
            border: `1px solid ${
              inputFocused ? colors.borderStrong : colors.border
            }`,
            padding: '8px 8px 8px 16px',
            display: 'flex',
            alignItems: 'flex-end',
            gap: 6,
            boxShadow: inputFocused
              ? '0 4px 16px rgba(15, 23, 42, 0.06)'
              : '0 1px 3px rgba(15, 23, 42, 0.04)',
            transition: 'border-color 0.15s, box-shadow 0.15s',
          }}
        >
          <TextArea
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onFocus={() => setInputFocused(true)}
            onBlur={() => setInputFocused(false)}
            placeholder={
              selectedSpaceId
                ? isMobile
                  ? '向 DataMind 提问…'
                  : '向 DataMind 提问…  Enter 发送，Shift+Enter 换行'
                : isMobile
                  ? '直接提问，或先选数据空间…'
                  : '选择数据空间后可分析数据，或直接提问…'
            }
            autoSize={{ minRows: 1, maxRows: 6 }}
            onPressEnter={(e) => {
              if (!e.shiftKey) {
                e.preventDefault()
                handleSend()
              }
            }}
            disabled={inputDisabled}
            variant="borderless"
            style={{
              flex: 1,
              resize: 'none',
              // 移动端用 16px 避免 iOS 聚焦时自动放大
              fontSize: isMobile ? 16 : 14.5,
              padding: '8px 0',
              lineHeight: 1.55,
            }}
          />
          {showStreaming ? (
            <Tooltip title="停止生成">
              <Button
                shape="circle"
                icon={<StopOutlined />}
                onClick={() => {
                  // 优雅暂停：只发中断信号，让后端把已产出内容收尾落盘，
                  // 流自然结束后走正常 finalize（保留全部 segments，可续）。
                  // 8s 兜底硬停，防后端无响应。
                  if (streamingConversationId) {
                    api.post(`/chat/conversations/${streamingConversationId}/abort`).catch(() => {})
                    const ctrl = useChatStore.getState().abortController
                    setTimeout(() => {
                      if (useChatStore.getState().abortController === ctrl) {
                        stopStreaming()
                      }
                    }, 8000)
                  } else {
                    stopStreaming()
                  }
                }}
                style={{
                  width: 36,
                  height: 36,
                  background: colors.textPrimary,
                  borderColor: colors.textPrimary,
                  color: '#fff',
                }}
              />
            </Tooltip>
          ) : (
            <Tooltip title={isStreaming ? '其他对话正在生成，请稍后' : inputValue.trim() ? '发送' : '请输入内容'}>
              <Button
                shape="circle"
                icon={<SendOutlined />}
                onClick={handleSend}
                disabled={!inputValue.trim() || isStreaming}
                style={{
                  width: 36,
                  height: 36,
                  background: inputValue.trim() && !isStreaming
                    ? colors.textPrimary
                    : colors.borderStrong,
                  borderColor: 'transparent',
                  color: '#fff',
                }}
              />
            </Tooltip>
          )}
        </div>
        <div
          style={{
            textAlign: 'center',
            fontSize: 11,
            color: colors.textMuted,
            marginTop: 8,
          }}
        >
          AI 生成的内容仅供参考，请核实关键数据后再使用
        </div>
      </div>
    </div>
  )
}
