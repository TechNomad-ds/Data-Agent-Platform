import { useState, useEffect, useRef, useCallback } from 'react'
import { Input, Button, Select, Typography, Spin, message } from 'antd'
import { SendOutlined, RobotOutlined, StopOutlined, LockOutlined, DatabaseOutlined } from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { chatApi, Message, SSEEvent } from '@/api/chat'
import { dataSpacesApi, DataSpace } from '@/api/dataSpaces'
import { settingsApi, ModelOption } from '@/api/settings'
import { useChatStore } from '@/stores/chatStore'
import { useAuthStore } from '@/stores/authStore'
import MessageContent from '@/components/Chat/MessageContent'
import ThinkingBlock from '@/components/Chat/ThinkingBlock'
import ExportButton from '@/components/Chat/ExportButton'
import api from '@/api/client'

const { Text } = Typography
const { TextArea } = Input

const FALLBACK_MODELS: ModelOption[] = [
  { id: 'deepseek-v4-flash', display_name: 'DeepSeek V4 Flash', model_name: 'deepseek-v4-flash', provider: 'deepseek', source: 'platform', credit_multiplier: 1.0 },
  { id: 'qwen3.5-flash', display_name: 'Qwen 3.5 Flash', model_name: 'qwen3.5-flash', provider: 'qwen', source: 'platform', credit_multiplier: 1.5 },
  { id: 'claude-haiku-4-5-20251001', display_name: 'Claude Haiku 4.5', model_name: 'claude-haiku-4-5-20251001', provider: 'anthropic', source: 'platform', credit_multiplier: 3.0 },
  { id: 'gpt-4o-mini', display_name: 'GPT-4o Mini', model_name: 'gpt-4o-mini', provider: 'openai', source: 'platform', credit_multiplier: 2.0 },
  { id: 'deepseek-r1', display_name: 'DeepSeek R1', model_name: 'deepseek-r1', provider: 'deepseek', source: 'platform', credit_multiplier: 2.0 },
]

const DEFAULT_SUGGESTIONS = [
  '这份数据有哪些字段，各自是什么含义？',
  '数据整体质量如何，有没有缺失或异常值？',
  '帮我做一个关键指标的统计摘要',
  '数据中有哪些值得关注的趋势或规律？',
]

interface Props {
  selectedSpaceId: string | undefined
  conversationId: string | undefined
  onConversationCreated: (id: string) => void
  onSpaceChange: (id: string | undefined) => void
  spaceLockedByConversation?: boolean
}

export default function ChatView({ selectedSpaceId, conversationId, onConversationCreated, onSpaceChange, spaceLockedByConversation = false }: Props) {
  const {
    setCurrentConversation,
    messages, setMessages, segments, thinkingText,
    isStreaming, setIsStreaming, appendStreamDelta, addToolEvent,
    setThinkingText, resetStream, setAbortController, stopStreaming,
  } = useChatStore()

  const [spaces, setSpaces] = useState<DataSpace[]>([])
  const [models, setModels] = useState<ModelOption[]>([])
  const [selectedModel, setSelectedModel] = useState<string>('')
  const [inputValue, setInputValue] = useState('')
  const [suggestions, setSuggestions] = useState<string[]>([])
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const sseBufferRef = useRef('')

  useEffect(() => { loadSpaces(); loadModels() }, [])
  useEffect(() => {
    if (conversationId) loadConversation(conversationId)
    else { setCurrentConversation(null); setMessages([]) }
  }, [conversationId])
  useEffect(() => { messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' }) }, [messages, segments])
  useEffect(() => { if (selectedSpaceId) loadSuggestions(); else setSuggestions([]) }, [selectedSpaceId])

  const loadSpaces = async () => { try { setSpaces((await dataSpacesApi.list()).data) } catch {} }
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
    try {
      const res = await chatApi.getConversation(id)
      setCurrentConversation(res.data)
      setMessages(res.data.messages)
      setSelectedModel(res.data.model_id)
    } catch {}
  }
  const loadSuggestions = async () => {
    try {
      const res = await api.get(`/data-spaces/${selectedSpaceId}/suggestions`)
      const items = res.data.suggestions || []
      setSuggestions(items.length > 0 ? items : DEFAULT_SUGGESTIONS)
    } catch { setSuggestions(DEFAULT_SUGGESTIONS) }
  }

  const parseSSELine = useCallback((line: string) => {
    if (!line.startsWith('data: ')) return
    const data = line.slice(6)
    if (data === '[DONE]') return
    try {
      const event: SSEEvent = JSON.parse(data)
      switch (event.type) {
        case 'text': if (event.delta) appendStreamDelta(event.delta); break
        case 'thinking': if (event.content) setThinkingText(event.content); break
        case 'tool_use': case 'tool_result': addToolEvent(event); break
        case 'error': message.error(event.message || 'Agent 执行出错'); break
      }
    } catch {}
  }, [appendStreamDelta, setThinkingText, addToolEvent])

  const handleSend = async () => {
    if (!inputValue.trim() || isStreaming) return
    if (!selectedSpaceId) { message.warning('请先选择数据空间'); return }
    if (!selectedModel) { message.warning('请先选择模型'); return }

    let convId = conversationId
    if (!convId) {
      try {
        const res = await chatApi.createConversation({ data_space_id: selectedSpaceId, model_id: selectedModel })
        setCurrentConversation(res.data)
        onConversationCreated(res.data.id)
        convId = res.data.id
      } catch { message.error('创建对话失败'); return }
    }
    await sendMessage(convId, inputValue)
  }

  const sendMessage = async (convId: string, content: string) => {
    const userMsg: Message = { id: Date.now().toString(), role: 'user', content, tool_calls: null, token_usage: null, credits_used: null, created_at: new Date().toISOString() }
    setMessages([...useChatStore.getState().messages, userMsg])
    setInputValue('')
    resetStream()
    setIsStreaming(true)
    const controller = new AbortController()
    setAbortController(controller)

    try {
      const response = await chatApi.sendMessage(convId, content, controller.signal, selectedModel)
      if (!response.ok) { if (response.status === 401) { useAuthStore.getState().logout() }; throw new Error() }
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
        for (const block of lines) { for (const line of block.split('\n')) { parseSSELine(line.trim()) } }
      }
      sseBufferRef.current += decoder.decode()
      if (sseBufferRef.current.trim()) { for (const line of sseBufferRef.current.split('\n')) { parseSSELine(line.trim()) } }

      const state = useChatStore.getState()
      const finalContent = state.segments.filter(s => s.type === 'text').map(s => s.content || '').join('')
      if (finalContent) {
        const assistantMsg: Message = { id: (Date.now() + 1).toString(), role: 'assistant', content: finalContent, tool_calls: state.segments, token_usage: null, credits_used: null, created_at: new Date().toISOString() }
        setMessages([...useChatStore.getState().messages, assistantMsg])
      }
    } catch (err: any) { if (err.name !== 'AbortError') message.error('发送失败') }
    finally { setIsStreaming(false); setAbortController(null); resetStream() }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: '#f8fafc' }}>
      {/* Top bar */}
      <div style={{ padding: '10px 24px', borderBottom: '1px solid #e2e8f0', background: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {spaceLockedByConversation && selectedSpaceId ? (
            <div style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '5px 12px', borderRadius: 6, background: '#f1f5f9', border: '1px solid #e2e8f0',
            }}>
              <DatabaseOutlined style={{ fontSize: 12, color: '#64748b' }} />
              <span style={{ fontSize: 13, color: '#334155', fontWeight: 500 }}>
                {spaces.find(s => s.id === selectedSpaceId)?.name || '数据空间'}
              </span>
              <LockOutlined style={{ fontSize: 10, color: '#94a3b8' }} />
            </div>
          ) : (
            <Select
              value={selectedSpaceId}
              onChange={onSpaceChange}
              placeholder="选择数据空间"
              style={{ width: 180 }}
              popupMatchSelectWidth={false}
              options={spaces.map(s => ({
                label: s.name,
                value: s.id,
              }))}
            />
          )}
          <Select
            value={selectedModel || undefined}
            onChange={setSelectedModel}
            placeholder="选择模型"
            style={{ width: 180 }}
            options={[
              {
                label: '平台模型',
                options: models.filter(m => m.source === 'platform').map(m => ({
                  label: m.display_name,
                  value: m.id,
                })),
              },
              ...(models.some(m => m.source === 'user') ? [{
                label: '我的模型',
                options: models.filter(m => m.source === 'user').map(m => ({
                  label: m.display_name,
                  value: m.id,
                })),
              }] : []),
            ]}
          />
        </div>
        <ExportButton conversationId={conversationId} />
      </div>

      {/* Messages */}
      <div style={{ flex: 1, overflow: 'auto', padding: '24px 0' }}>
        <div style={{ maxWidth: 1100, margin: '0 auto', padding: '0 24px' }}>
          {messages.length === 0 && !isStreaming ? (
            <div style={{ textAlign: 'center', paddingTop: 80 }}>
              <div style={{ width: 56, height: 56, borderRadius: 14, background: 'linear-gradient(135deg, #4f46e5, #7c3aed)', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 16px' }}>
                <RobotOutlined style={{ fontSize: 24, color: '#fff' }} />
              </div>
              <Text style={{ fontSize: 18, fontWeight: 600, color: '#1e293b', display: 'block', marginBottom: 4 }}>
                有什么可以帮你分析的？
              </Text>
              <Text style={{ fontSize: 13, color: '#94a3b8', display: 'block', marginBottom: 28 }}>
                {selectedSpaceId ? '基于你的数据，试试下面的问题' : '选择一个数据空间开始'}
              </Text>

              {!selectedSpaceId && spaces.length > 0 ? (
                <div style={{ maxWidth: 400, margin: '0 auto' }}>
                  {spaces.slice(0, 4).map(s => (
                    <div
                      key={s.id}
                      onClick={() => onSpaceChange(s.id)}
                      style={{
                        padding: '12px 16px', borderRadius: 10, marginBottom: 8,
                        border: '1px solid #e2e8f0', background: '#fff', cursor: 'pointer',
                        display: 'flex', alignItems: 'center', gap: 12, textAlign: 'left',
                        transition: 'all 0.15s',
                      }}
                      onMouseEnter={e => { e.currentTarget.style.borderColor = '#a5b4fc'; e.currentTarget.style.background = '#f8faff' }}
                      onMouseLeave={e => { e.currentTarget.style.borderColor = '#e2e8f0'; e.currentTarget.style.background = '#fff' }}
                    >
                      <DatabaseOutlined style={{ fontSize: 16, color: '#4f46e5' }} />
                      <div>
                        <div style={{ fontSize: 13, color: '#1e293b', fontWeight: 500 }}>{s.name}</div>
                        <div style={{ fontSize: 11, color: '#94a3b8' }}>{s.file_count} 个文件</div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : suggestions.length > 0 ? (
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(2, 1fr)',
                  gap: 12,
                  maxWidth: 560,
                  margin: '0 auto',
                }}>
                  {suggestions.slice(0, 4).map(q => (
                    <div
                      key={q}
                      onClick={() => setInputValue(q)}
                      style={{
                        padding: '14px 16px',
                        borderRadius: 10,
                        border: '1px solid #e2e8f0',
                        background: '#fff',
                        cursor: 'pointer',
                        textAlign: 'left',
                        fontSize: 13,
                        color: '#334155',
                        lineHeight: 1.5,
                        transition: 'all 0.15s',
                      }}
                      onMouseEnter={e => {
                        e.currentTarget.style.borderColor = '#a5b4fc'
                        e.currentTarget.style.background = '#f8faff'
                      }}
                      onMouseLeave={e => {
                        e.currentTarget.style.borderColor = '#e2e8f0'
                        e.currentTarget.style.background = '#fff'
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
              {messages.map(msg => <div key={msg.id} style={{ marginBottom: 20 }}><MessageContent message={msg} /></div>)}
              {isStreaming && (
                <div style={{ marginBottom: 16, display: 'flex', gap: 12 }}>
                  <div style={{ width: 30, height: 30, borderRadius: 8, background: 'linear-gradient(135deg, #4f46e5, #7c3aed)', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                    <RobotOutlined style={{ color: '#fff', fontSize: 13 }} />
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    {segments.length === 0 && !thinkingText && <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0' }}><Spin size="small" /><Text style={{ fontSize: 13, color: '#64748b' }}>思考中...</Text></div>}
                    {thinkingText && segments.length === 0 && <Text style={{ fontSize: 12, color: '#94a3b8', fontStyle: 'italic' }}>{thinkingText}</Text>}
                    {segments.map((seg, i) => seg.type === 'text' ? (
                      <div key={i} className="markdown-body" style={{ fontSize: 14, lineHeight: 1.7, padding: '8px 12px', borderRadius: 8, background: '#fff', border: '1px solid #e2e8f0', marginBottom: 6 }}>
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{seg.content || ''}</ReactMarkdown>
                      </div>
                    ) : (
                      <div key={i} style={{ marginBottom: 6 }}><ThinkingBlock toolEvents={seg.events || []} defaultExpanded={true} /></div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
          <div ref={messagesEndRef} />
        </div>
      </div>

      {/* Input */}
      <div style={{ padding: '12px 24px 20px' }}>
        <div style={{ maxWidth: 1100, margin: '0 auto', background: '#fff', borderRadius: 12, border: '1px solid #e2e8f0', padding: '10px 14px', display: 'flex', alignItems: 'flex-end', gap: 8, boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}>
          <TextArea
            value={inputValue}
            onChange={e => setInputValue(e.target.value)}
            placeholder={selectedSpaceId ? '输入你的问题...  Enter 发送，Shift+Enter 换行' : '请先选择数据空间'}
            autoSize={{ minRows: 1, maxRows: 5 }}
            onPressEnter={e => { if (!e.shiftKey) { e.preventDefault(); handleSend() } }}
            disabled={isStreaming || !selectedSpaceId}
            variant="borderless"
            style={{ flex: 1, resize: 'none', fontSize: 14 }}
          />
          {isStreaming ? (
            <Button danger icon={<StopOutlined />} onClick={stopStreaming} style={{ borderRadius: 8, height: 34, width: 34 }} />
          ) : (
            <Button type="primary" icon={<SendOutlined />} onClick={handleSend} disabled={!inputValue.trim() || !selectedSpaceId} style={{ borderRadius: 8, height: 34, width: 34 }} />
          )}
        </div>
      </div>
    </div>
  )
}
