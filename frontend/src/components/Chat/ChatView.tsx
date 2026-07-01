import { useState, useEffect, useRef, useCallback } from 'react'
import { Input, Button, Select, Typography, Spin, message, Tooltip, Dropdown, Modal, Radio } from 'antd'
import type { TextAreaRef } from 'antd/es/input/TextArea'
import {
  SendOutlined,
  StopOutlined,
  ArrowDownOutlined,
  PaperClipOutlined,
  FileOutlined,
  SaveOutlined,
  FolderOutlined,
  MessageOutlined,
  RobotOutlined,
  DownOutlined,
  FolderAddOutlined,
  DeleteOutlined,
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

// 普通对话（未选项目）：通用问答/写作类，不假设有文件可分析。
// 每条都是「点了即有用」的完整问题，不需要用户再补充上下文。
const GENERAL_SUGGESTIONS = [
  '用三个例子讲清楚什么是机器学习',
  '帮我制定一份高效的每日时间管理计划',
  '写一封向客户致歉并说明补偿方案的邮件',
  '推荐几个适合入门的提升表达能力的方法',
]

// 项目对话的兜底建议（后端没返回时用）：围绕项目里的文件
const PROJECT_SUGGESTIONS = [
  '帮我看看项目里有什么文件',
  '帮我概述一下这些文件的整体情况',
  '帮我做一个关键内容的摘要',
  '这些资料里有哪些值得关注的重点？',
]

const READING_WIDTH = 760

interface Props {
  selectedSpaceId: string | undefined
  selectedSpaceIds?: string[]
  conversationId: string | undefined
  onConversationCreated: (id: string) => void
  onConversationDeleted?: () => void
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
  selectedSpaceIds: selectedSpaceIdsProp,
  conversationId,
  onConversationCreated,
  onConversationDeleted,
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
  // 聊天附件（#8）：拖拽或按钮上传的文件，上传到当前绑定的项目后以 chip 展示
  const [attachments, setAttachments] = useState<{ id: string; name: string; type: string }[]>([])
  const [uploadingFiles, setUploadingFiles] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const textAreaRef = useRef<TextAreaRef>(null)
  // 拖拽进入/离开计数：拖过子元素时浏览器会连发 enter/leave，
  // 用计数器判断是否真正离开根容器，避免高亮闪烁。
  const dragDepthRef = useRef(0)
  // #12 多项目：本轮活跃空间集合（含主空间，主空间=第一个）。来自外层 prop；
  // 回退到单空间 selectedSpaceId，保证旧路径不变。
  const selectedSpaceIds: string[] = (selectedSpaceIdsProp && selectedSpaceIdsProp.length)
    ? selectedSpaceIdsProp
    : (selectedSpaceId ? [selectedSpaceId] : [])
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  // 输入法（拼音等）组字状态：组字中按回车是确认候选词，不应触发发送
  const isComposingRef = useRef(false)
  // 同步发送锁：isStreaming 是异步 state，快速连点（如连点两条建议）时两次点击
  // 都可能在 setIsStreaming 生效前通过守卫，导致两路 SSE 流写进同一缓冲区交织成乱码。
  // 这个 ref 在 sendMessage 入口同步置位、finally 释放，杜绝并发发送。
  const sendingRef = useRef(false)
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
      setAttachments([])  // 新对话：清空上一对话残留的临时文件 chip
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
      setSuggestions(GENERAL_SUGGESTIONS)
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
    loadConversationFiles(id)
  }

  // 加载本对话临时区里的文件，恢复输入框上方的 chip（重开对话时）
  const loadConversationFiles = async (id: string) => {
    try {
      const res = await dataSpacesApi.listConversationFiles(id)
      setAttachments(
        (res.data || []).map((f) => ({
          id: f.file_id,
          name: f.filename,
          type: f.file_type || '',
        }))
      )
    } catch {
      setAttachments([])
    }
  }

  const loadSuggestions = async () => {
    try {
      const res = await api.get(`/data-spaces/${selectedSpaceId}/suggestions`)
      const items = res.data.suggestions || []
      setSuggestions(items.length > 0 ? items : PROJECT_SUGGESTIONS)
    } catch {
      setSuggestions(PROJECT_SUGGESTIONS)
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

  // 确保存在一个对话（聊天框上传需要 conversationId 来归属临时文件区）。
  // 新对话在首次上传时惰性创建，沿用当前项目与模型。
  const ensureConversation = useCallback(async (): Promise<string | undefined> => {
    if (conversationId) return conversationId
    if (!selectedModel) { message.warning('请先选择模型'); return undefined }
    try {
      const res = await chatApi.createConversation({
        data_space_id: selectedSpaceId,
        data_space_ids: selectedSpaceIds.length > 1 ? selectedSpaceIds : undefined,
        model_id: selectedModel,
      })
      setCurrentConversation(res.data)
      justCreatedConvRef.current = res.data.id
      onConversationCreated(res.data.id)
      return res.data.id
    } catch {
      message.error('创建对话失败')
      return undefined
    }
  }, [conversationId, selectedModel, selectedSpaceId, setCurrentConversation, onConversationCreated])

  // 聊天框上传：文件进入「本次对话的临时文件区」，不进正式项目。
  // 普通对话也可用；agent 发消息时会自动把临时区并入检索范围。
  const uploadAttachments = useCallback(
    async (files: File[]) => {
      if (files.length === 0) return
      const convId = await ensureConversation()
      // ensureConversation 失败时已自行给出提示（未选模型 / 创建失败），这里直接退出即可
      if (!convId) return
      setUploadingFiles(true)
      try {
        const formData = new FormData()
        files.forEach((f) => formData.append('files', f))
        const res = await dataSpacesApi.uploadToConversation(convId, formData)
        const uploaded = (res.data || []).map((f: any) => ({
          id: f.id,
          name: f.filename || f.original_filename || '文件',
          type: f.file_type || '',
        }))
        setAttachments((prev) => [...prev, ...uploaded])
        message.success(`已添加 ${uploaded.length} 个文件，仅本次对话可见`)
      } catch (err: any) {
        message.error(err?.response?.data?.detail || '文件上传失败')
      } finally {
        setUploadingFiles(false)
      }
    },
    [ensureConversation]
  )

  // chip 操作：把临时文件「加入项目」（转入正式项目，长期保留+建索引）
  const handlePromoteAttachment = useCallback(async (fileId: string, targetSpaceId: string) => {
    if (!conversationId) return
    try {
      await dataSpacesApi.promoteConversationFile(conversationId, fileId, targetSpaceId)
      setAttachments((prev) => prev.filter((x) => x.id !== fileId))
      message.success('已加入项目，可在数据管理中查看')
      loadSpaces()
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '加入项目失败')
    }
  }, [conversationId])

  // chip 操作：从本对话临时区删除该文件（agent 不再看到）
  const handleRemoveAttachment = useCallback(async (fileId: string) => {
    setAttachments((prev) => prev.filter((x) => x.id !== fileId))
    if (!conversationId) return
    try {
      await dataSpacesApi.deleteConversationFile(conversationId, fileId)
    } catch {
      // 删除失败不阻断：前端已移除 chip，后端残留不影响主流程
    }
  }, [conversationId])

  // 只在拖入的是文件时才高亮（拖文字/拖元素不算）
  const isFileDrag = (e: React.DragEvent) =>
    Array.from(e.dataTransfer?.types || []).includes('Files')

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    if (!isFileDrag(e)) return
    e.preventDefault()
    dragDepthRef.current += 1
    setDragOver(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    if (!isFileDrag(e)) return
    e.preventDefault()
    dragDepthRef.current = Math.max(0, dragDepthRef.current - 1)
    if (dragDepthRef.current === 0) setDragOver(false)
  }, [])

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault()
      dragDepthRef.current = 0
      setDragOver(false)
      const files = Array.from(e.dataTransfer.files || [])
      if (files.length) uploadAttachments(files)
    },
    [uploadAttachments]
  )

  const handleSend = async () => {
    if (!inputValue.trim() || isStreaming || sendingRef.current) return
    if (!selectedModel) {
      message.warning('请先选择模型')
      return
    }

    let convId = conversationId
    if (!convId) {
      try {
        const res = await chatApi.createConversation({
          data_space_id: selectedSpaceId,
          data_space_ids: selectedSpaceIds.length > 1 ? selectedSpaceIds : undefined,
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
    // 上传的文件后端会自动并入本对话的检索范围（临时空间），
    // agent 通过 list_files / read_file / search_data_space 即可感知并分析，
    // 无需在提示词里塞「【本次附带文件：…】」，保持用户消息干净、无感。
    setAttachments([])
    await sendMessage(convId, inputValue)
  }

  const sendMessage = async (convId: string, content: string, skipAddUserMsg = false) => {
    // 同步并发锁：已有发送在途则直接忽略本次（防止快速连点导致两路流交织）
    if (sendingRef.current) return
    sendingRef.current = true
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
        selectedModel,
        selectedSpaceId,
        selectedSpaceIds.length > 1 ? selectedSpaceIds : undefined
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
      sendingRef.current = false
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

  // 编辑某条用户消息并重新发送：截断到该消息之前，插入编辑后的新消息，再发起请求。
  const handleEditResend = useCallback(
    (messageId: string, newContent: string) => {
      if (isStreaming || !conversationId) return
      const currentMessages = useChatStore.getState().messages
      const idx = currentMessages.findIndex((m) => m.id === messageId)
      if (idx < 0) return
      const editedMsg: Message = {
        ...currentMessages[idx],
        content: newContent,
        created_at: new Date().toISOString(),
      }
      // 保留被编辑消息之前的历史 + 编辑后的这条；其后（旧回答等）丢弃
      setMessages([...currentMessages.slice(0, idx), editedMsg])
      // skipAddUserMsg：用户消息已手动插入，避免重复
      sendMessage(conversationId, newContent, true)
    },
    [isStreaming, conversationId, selectedModel]
  )

  const handleFeedback = useCallback(
    async (messageId: string, rating: number) => {
      try {
        await api.post('/feedback', { message_id: messageId, rating })
      } catch {}
    },
    []
  )

  // #7 把当前对话沉淀为项目里的 Markdown 文件
  const doPersist = useCallback(async (targetSpaceId: string) => {
    if (!conversationId) return
    try {
      const res = await chatApi.persistToSpace(conversationId, { data_space_id: targetSpaceId })
      message.success(`已沉淀为「${res.data.filename}」，正在建索引`)
      loadSpaces()
    } catch (err: any) {
      message.error(err?.response?.data?.detail || '沉淀失败，请稍后重试')
    }
  }, [conversationId])

  const handlePersistToSpace = useCallback(() => {
    if (!conversationId) return
    if (!selectedSpaceId) {
      message.warning('请先绑定一个项目，再沉淀对话')
      return
    }
    // 单项目：直接沉淀，不打扰。多项目：让用户选存到哪个项目，避免默默存进第一个。
    const targets = spaces.filter((s) => selectedSpaceIds.includes(s.id))
    if (targets.length <= 1) {
      doPersist(selectedSpaceId)
      return
    }
    let picked = targets[0].id
    Modal.confirm({
      title: '沉淀到哪个项目？',
      content: (
        <div style={{ marginTop: 12 }}>
          <div style={{ fontSize: 13, color: colors.textMuted, marginBottom: 10 }}>
            这次对话绑定了多个项目，请选择把沉淀文件存到哪一个：
          </div>
          <Radio.Group
            defaultValue={picked}
            onChange={(e) => { picked = e.target.value }}
            style={{ display: 'flex', flexDirection: 'column', gap: 8 }}
          >
            {targets.map((s) => (
              <Radio key={s.id} value={s.id}>
                {s.name}　<span style={{ color: colors.textMuted, fontSize: 12 }}>{s.file_count} 个文件</span>
              </Radio>
            ))}
          </Radio.Group>
        </div>
      ),
      okText: '沉淀到此项目',
      cancelText: '取消',
      onOk: () => doPersist(picked),
    })
  }, [conversationId, selectedSpaceId, selectedSpaceIds, spaces, doPersist])

  const showStreaming = isStreaming && streamingConversationId === conversationId
  const showEmpty = messages.length === 0 && !showStreaming

  // 当前主项目对象（用于状态条展示项目名 + 文件数）
  const activeSpace = spaces.find((s) => s.id === selectedSpaceId)
  const activeModel = models.find((m) => m.id === selectedModel)
  // 多项目：选中的全部项目对象 + 合计文件数（用于状态条/空状态展示）
  const activeSpaces = selectedSpaceIds
    .map((id) => spaces.find((s) => s.id === id))
    .filter(Boolean) as DataSpace[]
  const isMulti = activeSpaces.length > 1
  const totalFiles = activeSpaces.reduce((n, s) => n + (s.file_count || 0), 0)
  // 项目上下文的一句话描述（单/多项目通用）
  const spaceLabel = activeSpaces.length === 0
    ? ''
    : isMulti
      ? `${activeSpaces.length} 个项目`
      : activeSpaces[0].name

  return (
    <div
      onDragEnter={handleDragEnter}
      onDragOver={(e) => { if (isFileDrag(e)) e.preventDefault() }}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        background: colors.bg,
        position: 'relative',
      }}
    >
      {/* 拖拽上传遮罩：覆盖整个聊天区，拖文件到页面任意位置都能上传 */}
      {dragOver && (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            zIndex: 50,
            background: 'rgba(79, 70, 229, 0.06)',
            border: `2px dashed ${colors.primary}`,
            borderRadius: 12,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: colors.primary,
            fontSize: 16,
            fontWeight: 500,
            pointerEvents: 'none',
          }}
        >
          松开以添加文件（仅本次对话可见）
        </div>
      )}
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
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
          {/* 项目状态条（只读）：告诉用户这条对话用的是哪个项目的数据。
              切换项目的唯一入口在左侧项目栏，这里不再提供切换，避免双控件混淆。 */}
          <Tooltip title={
            activeSpaces.length === 0
              ? '普通对话不分析你的文件，如需分析文件请在左侧选择项目'
              : isMulti
                ? `这条对话同时基于这些项目的文件回答：${activeSpaces.map((s) => s.name).join('、')}。如需增减项目请在左侧项目栏操作`
                : '这条对话基于该项目的文件回答，如需切换项目请在左侧项目栏操作'
          }>
            <div className="ctx-pill ctx-pill-readonly">
              <span className="ctx-pill-icon" style={{ color: activeSpaces.length ? colors.primary : colors.textMuted }}>
                {activeSpaces.length ? <FolderOutlined /> : <MessageOutlined />}
              </span>
              <span className="ctx-pill-text">
                {activeSpaces.length ? spaceLabel : '普通对话'}
              </span>
              {activeSpaces.length > 0 && (
                <span className="ctx-pill-sub">{totalFiles} 个文件</span>
              )}
            </div>
          </Tooltip>
          {/* 模型选择器：与项目条并列，组成「这次对话的上下文」带。显式标注，避免被当成次要操作。 */}
          <div className="ctx-divider" />
          <Tooltip title="选择回答这次对话所用的 AI 模型，可随时切换">
            <div className="ctx-model">
              <span className="ctx-model-label">模型</span>
              <Select
                value={selectedModel || undefined}
                onChange={setSelectedModel}
                placeholder="选择模型"
                variant="borderless"
                style={{ minWidth: isMobile ? 120 : 168, maxWidth: isMobile ? 160 : 300 }}
                popupMatchSelectWidth={false}
                optionLabelProp="label"
                suffixIcon={<DownOutlined style={{ fontSize: 11, color: colors.textMuted }} />}
                prefix={<RobotOutlined style={{ color: colors.primary, fontSize: 14 }} />}
                options={models.map((m) => ({
                  label: m.display_name,
                  value: m.id,
                }))}
              />
            </div>
          </Tooltip>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {conversationId && selectedSpaceId && (
            <Tooltip title="把这段对话沉淀为项目里的文档，便于以后检索引用">
              <Button
                type="text"
                icon={<SaveOutlined />}
                onClick={handlePersistToSpace}
                style={{ color: colors.textSecondary }}
                size="small"
              >
                沉淀
              </Button>
            </Tooltip>
          )}
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
                  fontSize: 26,
                  fontWeight: 600,
                  color: colors.textPrimary,
                  display: 'block',
                  marginBottom: 8,
                  letterSpacing: -0.4,
                }}
              >
                {activeSpaces.length === 0
                  ? '有什么可以帮你的？'
                  : isMulti
                    ? `正在 ${activeSpaces.length} 个项目中对话`
                    : `正在「${activeSpaces[0].name}」中对话`}
              </Text>
              <Text
                style={{
                  fontSize: 15,
                  color: colors.textMuted,
                  display: 'block',
                  marginBottom: 12,
                }}
              >
                {activeSpaces.length === 0
                  ? '普通对话：直接提问、写作、答疑都可以'
                  : isMulti
                    ? `我可以一起分析这些项目里的 ${totalFiles} 个文件：${activeSpaces.map((s) => s.name).join('、')}`
                    : `我可以分析这个项目里的 ${activeSpaces[0].file_count} 个文件`}
              </Text>
              {/* 上下文提示：明确告诉用户「用哪个项目的数据 + 哪个模型」，并给出切换出口 */}
              <div
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: 8,
                  flexWrap: 'wrap',
                  justifyContent: 'center',
                  marginBottom: 32,
                  fontSize: 12.5,
                  color: colors.textMuted,
                }}
              >
                {activeSpaces.length === 0 && (
                  <span>
                    想分析文件？在左侧
                    <FolderOutlined style={{ margin: '0 3px', color: colors.primary }} />
                    选择一个或多个项目
                  </span>
                )}
                {activeModel && (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                    <RobotOutlined /> 当前模型：{activeModel.display_name}
                  </span>
                )}
              </div>

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
                      onClick={() => {
                        // 点击示例只预填入输入框，不直接发送，方便用户改完再发
                        setInputValue(q)
                        // 等 value 更新后聚焦并把光标移到末尾
                        requestAnimationFrame(() => {
                          const el = textAreaRef.current?.resizableTextArea?.textArea
                          if (el) {
                            el.focus()
                            el.setSelectionRange(q.length, q.length)
                          }
                        })
                      }}
                      style={{
                        padding: '15px 17px',
                        borderRadius: 12,
                        border: `1px solid ${colors.border}`,
                        background: colors.surface,
                        cursor: 'pointer',
                        textAlign: 'left',
                        fontSize: 14.5,
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
                    conversationId={conversationId}
                    onRegenerate={
                      msg.role === 'assistant' && idx === messages.length - 1 && !isStreaming
                        ? handleRegenerate
                        : undefined
                    }
                    onFeedback={msg.role === 'assistant' ? handleFeedback : undefined}
                    onEditResend={msg.role === 'user' && !isStreaming ? handleEditResend : undefined}
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
                        <div key={i} style={{ marginBottom: 8 }}>
                          <Text
                            style={{
                              fontSize: 13,
                              color: colors.textMuted,
                              fontStyle: 'italic',
                              whiteSpace: 'pre-wrap',
                            }}
                          >
                            {seg.content || ''}
                          </Text>
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
            display: 'flex',
            flexDirection: 'column',
            gap: 8,
            position: 'relative',
          }}
        >
          {/* 附件 chips — 置于输入框上方 */}
          {(attachments.length > 0 || uploadingFiles) && (
            <div>
              <div style={{ fontSize: 11, color: colors.textMuted, marginBottom: 4, paddingLeft: 2 }}>
                本次对话的文件（仅此对话可见，不在项目中）
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, paddingRight: 4 }}>
              {attachments.map((a) => {
                // 「加入项目」目标：有当前项目则直接加入它；否则列出所有项目供选择
                const promoteChildren = selectedSpaceId
                  ? [{
                      key: `p_${selectedSpaceId}`,
                      label: `加入「${activeSpace?.name || '当前项目'}」`,
                      icon: <FolderAddOutlined />,
                      onClick: () => handlePromoteAttachment(a.id, selectedSpaceId),
                    }]
                  : spaces.length > 0
                    ? spaces.map((s) => ({
                        key: `p_${s.id}`,
                        label: `加入「${s.name}」`,
                        icon: <FolderAddOutlined />,
                        onClick: () => handlePromoteAttachment(a.id, s.id),
                      }))
                    : [{ key: 'none', label: '暂无项目，请先在数据管理创建', disabled: true }]
                const menuItems = [
                  ...promoteChildren,
                  { type: 'divider' as const },
                  {
                    key: 'remove',
                    label: '删除',
                    icon: <DeleteOutlined />,
                    danger: true,
                    onClick: () => handleRemoveAttachment(a.id),
                  },
                ]
                return (
                  <Dropdown key={a.id} trigger={['click']} menu={{ items: menuItems }}>
                    <div
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 6,
                        padding: '4px 6px 4px 10px',
                        background: colors.bgSubtle,
                        border: `1px solid ${colors.border}`,
                        borderRadius: 8,
                        fontSize: 12.5,
                        color: colors.textPrimary,
                        maxWidth: 240,
                        cursor: 'pointer',
                      }}
                    >
                      <FileOutlined style={{ color: colors.primary, fontSize: 13 }} />
                      <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {a.name}
                      </span>
                      <DownOutlined style={{ fontSize: 9, color: colors.textMuted }} />
                    </div>
                  </Dropdown>
                )
              })}
              {uploadingFiles && (
                <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 10px', fontSize: 12.5, color: colors.textMuted }}>
                  <Spin size="small" /> 上传中…
                </div>
              )}
              </div>
            </div>
          )}
          <div
            style={{
              display: 'flex',
              alignItems: 'flex-end',
              gap: 6,
              background: colors.surface,
              borderRadius: 18,
              border: `1px solid ${
                dragOver ? colors.primary : inputFocused ? colors.borderStrong : colors.border
              }`,
              padding: '8px 8px 8px 16px',
              boxShadow: inputFocused
                ? '0 4px 16px rgba(15, 23, 42, 0.06)'
                : '0 1px 3px rgba(15, 23, 42, 0.04)',
              transition: 'border-color 0.15s, box-shadow 0.15s',
            }}
          >
          <input
            ref={fileInputRef}
            type="file"
            multiple
            style={{ display: 'none' }}
            onChange={(e) => {
              const files = Array.from(e.target.files || [])
              if (files.length) uploadAttachments(files)
              if (fileInputRef.current) fileInputRef.current.value = ''
            }}
          />
          <Tooltip title="上传文件（仅本次对话可见，可在文件上选择加入项目）">
            <Button
              type="text"
              icon={<PaperClipOutlined />}
              onClick={() => fileInputRef.current?.click()}
              disabled={isStreaming || uploadingFiles}
              style={{ width: 34, height: 34, color: colors.textMuted, flexShrink: 0 }}
            />
          </Tooltip>
          <TextArea
            ref={textAreaRef}
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onFocus={() => setInputFocused(true)}
            onBlur={() => setInputFocused(false)}
            onCompositionStart={() => { isComposingRef.current = true }}
            onCompositionEnd={() => { isComposingRef.current = false }}
            placeholder={
              selectedSpaceId
                ? isMobile
                  ? '向 DataMind 提问…'
                  : '向 DataMind 提问…  Enter 发送，Shift+Enter 换行'
                : isMobile
                  ? '直接提问，或先选项目…'
                  : '选择项目后可分析数据，或直接提问…'
            }
            autoSize={{ minRows: 1, maxRows: 6 }}
            onKeyDown={(e) => {
              // 仅在「非组字 + 非 Shift」时回车发送。
              // 拼音/输入法组字中按回车是确认候选词（e.nativeEvent.isComposing 为 true），
              // 不能当成发送——这正是「想上屏英文却被直接发送」的根因。
              if (e.key !== 'Enter') return
              if (e.shiftKey) return
              if (isComposingRef.current || (e.nativeEvent as any).isComposing || (e.nativeEvent as any).keyCode === 229) return
              e.preventDefault()
              // 生成回复期间允许继续打字/换行，但不允许发送：回车时给个轻提示，内容保留
              if (isStreaming) {
                message.info('正在生成回复，请等当前回答结束后再发送')
                return
              }
              handleSend()
            }}
            variant="borderless"
            style={{
              flex: 1,
              resize: 'none',
              // 移动端用 16px 避免 iOS 聚焦时自动放大
              fontSize: isMobile ? 16 : 15.5,
              padding: '8px 0',
              lineHeight: 1.6,
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
        </div>
        <div
          style={{
            textAlign: 'center',
            fontSize: 11,
            color: colors.textMuted,
            marginTop: 12,
          }}
        >
          AI 生成的内容仅供参考，请核实关键数据后再使用
        </div>
      </div>
    </div>
  )
}
