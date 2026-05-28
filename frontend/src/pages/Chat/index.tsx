import { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Input, Button, Select, Typography, Spin, message, Tooltip, Tag } from 'antd'
import {
  SendOutlined, RobotOutlined, StopOutlined,
} from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { chatApi, Message, SSEEvent } from '@/api/chat'
import { dataSpacesApi, DataSpace } from '@/api/dataSpaces'
import { modelsApi, ModelInfo } from '@/api/models'
import { useChatStore } from '@/stores/chatStore'
import { useAuthStore } from '@/stores/authStore'
import MessageContent from '@/components/Chat/MessageContent'
import ThinkingBlock from '@/components/Chat/ThinkingBlock'
import ExportButton from '@/components/Chat/ExportButton'

const { Text } = Typography
const { TextArea } = Input

export default function ChatView() {
  const { conversationId } = useParams()
  const navigate = useNavigate()

  const {
    setConversations, currentConversation, setCurrentConversation,
    messages, setMessages, segments, thinkingText,
    isStreaming, setIsStreaming, appendStreamDelta, addToolEvent,
    setThinkingText, resetStream, setAbortController, stopStreaming,
  } = useChatStore()

  const [spaces, setSpaces] = useState<DataSpace[]>([])
  const [models, setModels] = useState<ModelInfo[]>([])
  const [selectedSpace, setSelectedSpace] = useState<string | undefined>()
  const [selectedModel, setSelectedModel] = useState<string>('')
  const [inputValue, setInputValue] = useState('')
  const [suggestions, setSuggestions] = useState<string[]>([])
  const [spaceSummary, setSpaceSummary] = useState<string>('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const sseBufferRef = useRef('')

  useEffect(() => {
    loadSpaces()
    loadModels()
  }, [])

  useEffect(() => {
    if (selectedSpace) loadSuggestions()
    else { setSuggestions([]); setSpaceSummary('') }
  }, [selectedSpace])

  useEffect(() => {
    if (conversationId && !isStreaming) loadConversation(conversationId)
  }, [conversationId])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, segments])

  const loadSpaces = async () => {
    try {
      const res = await dataSpacesApi.list()
      setSpaces(res.data)
    } catch {}
  }

  const loadSuggestions = async () => {
    if (!selectedSpace) return
    try {
      const res = await import('@/api/client').then(m => m.default.get(`/data-spaces/${selectedSpace}/suggestions`))
      setSuggestions(res.data.suggestions || [])
      setSpaceSummary(res.data.summary || '')
    } catch {
      setSuggestions([])
    }
  }

  const loadModels = async () => {
    try {
      const res = await modelsApi.listAvailable()
      setModels(res.data)
      if (res.data.length > 0 && !selectedModel) {
        setSelectedModel(res.data[0].id)
      }
    } catch {}
  }

  const loadConversation = async (id: string) => {
    try {
      const res = await chatApi.getConversation(id)
      setCurrentConversation(res.data)
      setMessages(res.data.messages)
      if (res.data.data_space_id) setSelectedSpace(res.data.data_space_id)
      setSelectedModel(res.data.model_id)
    } catch {}
  }

  const loadConversations = async () => {
    try {
      const res = await chatApi.listConversations()
      setConversations(res.data)
    } catch {}
  }

  const parseSSELine = useCallback((line: string) => {
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
          if (event.content) setThinkingText(event.content)
          break
        case 'tool_use':
        case 'tool_result':
          addToolEvent(event)
          break
        case 'error':
          message.error(event.message || 'Agent 执行出错')
          break
        case 'done':
          break
      }
    } catch {}
  }, [appendStreamDelta, setThinkingText, addToolEvent])

  const handleSend = async () => {
    if (!inputValue.trim() || isStreaming) return

    let convId = currentConversation?.id
    if (!convId) {
      if (!selectedModel) {
        message.warning('请先选择模型')
        return
      }
      try {
        const res = await chatApi.createConversation({
          data_space_id: selectedSpace,
          model_id: selectedModel,
        })
        setCurrentConversation(res.data)
        navigate(`/chat/${res.data.id}`)
        loadConversations()
        convId = res.data.id
      } catch {
        message.error('创建对话失败')
        return
      }
    }

    await sendMessage(convId, inputValue)
  }

  const sendMessage = async (convId: string, content: string) => {
    const userMsg: Message = {
      id: Date.now().toString(),
      role: 'user',
      content,
      tool_calls: null,
      token_usage: null,
      credits_used: null,
      created_at: new Date().toISOString(),
    }
    const currentMessages = useChatStore.getState().messages
    setMessages([...currentMessages, userMsg])
    setInputValue('')
    resetStream()
    setIsStreaming(true)

    const controller = new AbortController()
    setAbortController(controller)

    try {
      const response = await chatApi.sendMessage(convId, content, controller.signal)
      if (!response.ok) {
        if (response.status === 401) {
          message.error('登录已过期')
          useAuthStore.getState().logout()
          return
        }
        throw new Error('请求失败')
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

      const state = useChatStore.getState()
      const finalContent = state.segments.filter(s => s.type === 'text').map(s => s.content || '').join('')
      if (finalContent) {
        const assistantMsg: Message = {
          id: (Date.now() + 1).toString(),
          role: 'assistant',
          content: finalContent,
          tool_calls: state.segments,
          token_usage: null,
          credits_used: null,
          created_at: new Date().toISOString(),
        }
        setMessages([...useChatStore.getState().messages, assistantMsg])
      }
    } catch (err: any) {
      if (err.name !== 'AbortError') message.error('发送消息失败')
    } finally {
      setIsStreaming(false)
      setAbortController(null)
      resetStream()
      loadConversations()
      loadConversation(convId)
    }
  }

  return (
    <div style={{
      flex: 1,
      display: 'flex',
      flexDirection: 'column',
      height: '100vh',
      background: '#f8fafc',
      overflow: 'hidden',
    }}>
      {/* Top bar with model selector */}
      <div style={{
        padding: '10px 20px',
        borderBottom: '1px solid #e2e8f0',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Select
            value={selectedModel || undefined}
            onChange={setSelectedModel}
            placeholder="选择模型"
            style={{ width: 200 }}
            popupMatchSelectWidth={false}
            options={models.map(m => ({
              label: (
                <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <span>{m.display_name}</span>
                  <Tag color="purple" style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px', margin: 0 }}>
                    x{m.credit_multiplier}
                  </Tag>
                </span>
              ),
              value: m.id,
            }))}
          />
          {selectedSpace && (
            <Tag color="blue" style={{ margin: 0, fontSize: 12 }}>
              {spaces.find(s => s.id === selectedSpace)?.name || '数据空间'}
            </Tag>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Text style={{ fontSize: 12, color: '#94a3b8' }}>
            {currentConversation?.title || '新对话'}
          </Text>
          <ExportButton conversationId={currentConversation?.id} />
        </div>
      </div>

      {/* Messages area */}
      <div style={{
        flex: 1,
        overflow: 'auto',
        padding: '24px 0',
      }}>
        <div style={{ maxWidth: 800, margin: '0 auto', padding: '0 24px' }}>
          {messages.length === 0 && !isStreaming ? (
            <div style={{ textAlign: 'center', paddingTop: 120 }}>
              <div style={{
                width: 72, height: 72, borderRadius: 16,
                background: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                margin: '0 auto 24px', boxShadow: '0 8px 32px rgba(99,102,241,0.3)',
              }}>
                <RobotOutlined style={{ fontSize: 32, color: '#fff' }} />
              </div>
              <Text style={{ fontSize: 20, fontWeight: 600, color: '#1e293b', display: 'block', marginBottom: 8 }}>
                有什么可以帮你分析的？
              </Text>
              <Text style={{ fontSize: 14, color: '#94a3b8' }}>
                {spaceSummary || '选择数据空间，上传数据，然后开始对话'}
              </Text>
              <div style={{ marginTop: 32, display: 'flex', gap: 10, justifyContent: 'center', flexWrap: 'wrap', maxWidth: 600 }}>
                {(suggestions.length > 0 ? suggestions : ['帮我分析数据概况', '数据有哪些异常？', '生成可视化图表', '导出分析报告']).map(q => (
                  <Button
                    key={q}
                    type="default"
                    size="small"
                    onClick={() => setInputValue(q)}
                    style={{
                      borderRadius: 20,
                      padding: '4px 16px',
                      fontSize: 13,
                      background: '#ffffff',
                      borderColor: '#e2e8f0',
                      color: '#475569',
                    }}
                  >
                    {q}
                  </Button>
                ))}
              </div>
            </div>
          ) : (
            <>
              {messages.map(msg => (
                <div key={msg.id} style={{ marginBottom: 24 }}>
                  <MessageContent message={msg} />
                </div>
              ))}

              {isStreaming && (
                <div style={{ marginBottom: 16, display: 'flex', gap: 12 }}>
                  <div style={{
                    width: 32, height: 32, borderRadius: 8,
                    background: 'linear-gradient(135deg, #6366f1, #8b5cf6)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    flexShrink: 0,
                  }}>
                    <RobotOutlined style={{ color: '#fff', fontSize: 14 }} />
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    {segments.length === 0 && !thinkingText && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 0' }}>
                        <Spin size="small" />
                        <Text style={{ fontSize: 13, color: '#64748b' }}>思考中...</Text>
                      </div>
                    )}
                    {thinkingText && segments.length === 0 && (
                      <Text style={{ fontSize: 12, color: '#94a3b8', fontStyle: 'italic' }}>{thinkingText}</Text>
                    )}
                    {segments.map((seg, i) => (
                      seg.type === 'text' ? (
                        <div key={i} className="markdown-body" style={{
                          fontSize: 14, lineHeight: 1.7, padding: '10px 14px',
                          borderRadius: 10, background: '#ffffff', color: '#1e293b',
                          marginBottom: 8,
                        }}>
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>{seg.content || ''}</ReactMarkdown>
                        </div>
                      ) : (
                        <div key={i} style={{ marginBottom: 8 }}>
                          <ThinkingBlock toolEvents={seg.events || []} defaultExpanded={true} />
                        </div>
                      )
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input area */}
      <div style={{
        padding: '12px 24px 20px',
        flexShrink: 0,
      }}>
        <div style={{
          maxWidth: 800,
          margin: '0 auto',
          background: '#ffffff',
          borderRadius: 14,
          border: '1px solid #e2e8f0',
          padding: '10px 14px',
          display: 'flex',
          alignItems: 'flex-end',
          gap: 8,
          transition: 'border-color 0.2s',
        }}>
          <TextArea
            value={inputValue}
            onChange={e => setInputValue(e.target.value)}
            placeholder="输入你的问题，按 Enter 发送..."
            autoSize={{ minRows: 1, maxRows: 5 }}
            onPressEnter={e => {
              if (!e.shiftKey) { e.preventDefault(); handleSend() }
            }}
            disabled={isStreaming}
            variant="borderless"
            style={{
              flex: 1, resize: 'none', fontSize: 14,
              color: '#1e293b', background: 'transparent',
            }}
          />
          {isStreaming ? (
            <Tooltip title="停止生成">
              <Button
                type="default"
                danger
                icon={<StopOutlined />}
                onClick={stopStreaming}
                style={{ borderRadius: 8, height: 34, width: 34 }}
              />
            </Tooltip>
          ) : (
            <Button
              type="primary"
              icon={<SendOutlined />}
              onClick={handleSend}
              disabled={!inputValue.trim()}
              style={{ borderRadius: 8, height: 34, width: 34 }}
            />
          )}
        </div>
      </div>
    </div>
  )
}
