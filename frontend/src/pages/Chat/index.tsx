import { useEffect, useState, useRef, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Layout, List, Button, Input, Select, Space, Typography, Card, Spin, message, Empty, Tooltip, Tag } from 'antd'
import {
  PlusOutlined, SendOutlined, RobotOutlined,
  DatabaseOutlined, DeleteOutlined, StopOutlined,
} from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { chatApi, Message, SSEEvent } from '@/api/chat'
import { dataSpacesApi, DataSpace } from '@/api/dataSpaces'
import { modelsApi, ModelInfo } from '@/api/models'
import { useChatStore } from '@/stores/chatStore'
import { useAuthStore } from '@/stores/authStore'
import ThinkingBlock from '@/components/Chat/ThinkingBlock'
import MessageContent from '@/components/Chat/MessageContent'

const { Sider, Content } = Layout
const { Text, Title } = Typography
const { TextArea } = Input

export default function Chat() {
  const { conversationId } = useParams()
  const navigate = useNavigate()

  const {
    conversations, setConversations, currentConversation, setCurrentConversation,
    messages, setMessages, segments, thinkingText,
    isStreaming, setIsStreaming, appendStreamDelta, addToolEvent,
    setThinkingText, resetStream, setAbortController, stopStreaming,
  } = useChatStore()

  const [spaces, setSpaces] = useState<DataSpace[]>([])
  const [models, setModels] = useState<ModelInfo[]>([])
  const [selectedSpace, setSelectedSpace] = useState<string | undefined>()
  const [selectedModel, setSelectedModel] = useState<string>('')
  const [inputValue, setInputValue] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const sseBufferRef = useRef('')

  useEffect(() => {
    loadConversations()
    loadSpaces()
    loadModels()
  }, [])

  useEffect(() => {
    if (conversationId) loadConversation(conversationId)
  }, [conversationId])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, segments])

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

  const handleNewConversation = async () => {
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
      setMessages([])
      resetStream()
      navigate(`/chat/${res.data.id}`)
      loadConversations()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '创建对话失败')
    }
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
          message.error('登录已过期，请重新登录')
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
          const dataLines = block.split('\n')
          for (const line of dataLines) {
            parseSSELine(line.trim())
          }
        }
      }

      // Flush decoder
      sseBufferRef.current += decoder.decode()

      // Process any remaining buffer
      if (sseBufferRef.current.trim()) {
        const remaining = sseBufferRef.current.split('\n')
        for (const line of remaining) {
          parseSSELine(line.trim())
        }
      }

      // Stream ended, add assistant message with segments
      const state = useChatStore.getState()
      const finalSegments = state.segments
      const finalContent = finalSegments.filter(s => s.type === 'text').map(s => s.content || '').join('')
      if (finalContent) {
        const assistantMsg: Message = {
          id: (Date.now() + 1).toString(),
          role: 'assistant',
          content: finalContent,
          tool_calls: finalSegments,
          token_usage: null,
          credits_used: null,
          created_at: new Date().toISOString(),
        }
        setMessages([...useChatStore.getState().messages, assistantMsg])
      }
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        message.error('发送消息失败')
      }
    } finally {
      setIsStreaming(false)
      setAbortController(null)
      resetStream()
      loadConversations()
    }
  }

  const handleDeleteConversation = async (id: string) => {
    try {
      await chatApi.deleteConversation(id)
      if (currentConversation?.id === id) {
        setCurrentConversation(null)
        setMessages([])
        navigate('/chat')
      }
      loadConversations()
    } catch {}
  }

  return (
    <Layout style={{ height: 'calc(100vh - 64px - 48px)', background: 'transparent' }}>
      {/* 左侧对话列表 */}
      <Sider width={280} theme="light" style={{
        borderRight: '1px solid #e8e8e8',
        borderRadius: 12,
        overflow: 'auto',
        boxShadow: '0 2px 8px rgba(0,0,0,0.04)',
      }}>
        <div style={{ padding: 16 }}>
          <Button
            type="primary"
            icon={<PlusOutlined />}
            block
            onClick={handleNewConversation}
            style={{ borderRadius: 8, height: 40, fontWeight: 500 }}
          >
            新建对话
          </Button>
        </div>
        {conversations.length === 0 ? (
          <Empty description="暂无对话" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ marginTop: 40 }} />
        ) : (
          <List
            dataSource={conversations}
            renderItem={(item) => (
              <List.Item
                style={{
                  padding: '10px 16px',
                  cursor: 'pointer',
                  background: currentConversation?.id === item.id ? '#e6f7ff' : 'transparent',
                  borderLeft: currentConversation?.id === item.id ? '3px solid #1677ff' : '3px solid transparent',
                  transition: 'all 0.2s',
                }}
                onClick={() => navigate(`/chat/${item.id}`)}
                actions={[
                  <Button
                    type="text"
                    size="small"
                    danger
                    icon={<DeleteOutlined />}
                    onClick={(e) => { e.stopPropagation(); handleDeleteConversation(item.id) }}
                  />,
                ]}
              >
                <List.Item.Meta
                  title={<Text ellipsis style={{ maxWidth: 160, fontSize: 13 }}>{item.title || '新对话'}</Text>}
                  description={<Text type="secondary" style={{ fontSize: 11 }}>{new Date(item.updated_at).toLocaleString('zh-CN')}</Text>}
                />
              </List.Item>
            )}
          />
        )}
      </Sider>

      {/* 右侧聊天区域 */}
      <Content style={{ display: 'flex', flexDirection: 'column', padding: '0 0 0 16px' }}>
        {/* 顶部选择器 */}
        <Card size="small" style={{
          marginBottom: 12,
          borderRadius: 12,
          boxShadow: '0 2px 8px rgba(0,0,0,0.04)',
          border: '1px solid #f0f0f0',
        }}>
          <Space wrap>
            <Select
              placeholder="选择数据空间"
              value={selectedSpace}
              onChange={setSelectedSpace}
              style={{ width: 200 }}
              allowClear
              options={spaces.map((s) => ({ label: s.name, value: s.id }))}
              suffixIcon={<DatabaseOutlined />}
            />
            <Select
              value={selectedModel || undefined}
              onChange={setSelectedModel}
              placeholder="选择模型"
              style={{ width: 220 }}
              options={models.map((m) => ({
                label: (
                  <Space>
                    <span>{m.display_name}</span>
                    <Tag color="blue" style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px' }}>
                      x{m.credit_multiplier}
                    </Tag>
                  </Space>
                ),
                value: m.id,
              }))}
            />
          </Space>
        </Card>

        {/* 消息区域 */}
        <div style={{
          flex: 1,
          overflow: 'auto',
          borderRadius: 12,
          background: '#fff',
          padding: 20,
          boxShadow: '0 2px 8px rgba(0,0,0,0.04)',
          border: '1px solid #f0f0f0',
        }}>
          {messages.length === 0 && !isStreaming ? (
            <div style={{ textAlign: 'center', paddingTop: 80 }}>
              <div style={{
                width: 80, height: 80, borderRadius: '50%',
                background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                margin: '0 auto 20px',
              }}>
                <RobotOutlined style={{ fontSize: 36, color: '#fff' }} />
              </div>
              <Title level={4} style={{ marginBottom: 8, color: '#333' }}>
                Data Agent 准备就绪
              </Title>
              <Text type="secondary" style={{ fontSize: 14 }}>
                选择数据空间和模型，开始智能数据分析对话
              </Text>
            </div>
          ) : (
            <>
              {messages.map((msg) => (
                <div key={msg.id} style={{ marginBottom: 20 }}>
                  <MessageContent message={msg} />
                </div>
              ))}

              {/* 流式内容 */}
              {isStreaming && (
                <div style={{ marginBottom: 16, display: 'flex', gap: 12 }}>
                  <div style={{
                    width: 34, height: 34, borderRadius: '50%',
                    background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    flexShrink: 0,
                  }}>
                    <RobotOutlined style={{ color: '#fff', fontSize: 14 }} />
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    {segments.length === 0 && !thinkingText && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '12px 0' }}>
                        <Spin size="small" />
                        <Text type="secondary" style={{ fontSize: 13 }}>思考中...</Text>
                      </div>
                    )}
                    {thinkingText && segments.length === 0 && (
                      <div style={{ padding: '6px 0', marginBottom: 6 }}>
                        <Text type="secondary" style={{ fontSize: 12, fontStyle: 'italic' }}>{thinkingText}</Text>
                      </div>
                    )}
                    {segments.map((seg, i) => (
                      seg.type === 'text' ? (
                        <div key={i} className="markdown-body" style={{
                          fontSize: 14, lineHeight: 1.7, marginBottom: 8,
                          padding: '12px 16px', borderRadius: 12,
                          background: '#f8f9fa', color: '#1f2937',
                          boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
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

        {/* 输入区域 */}
        <div style={{ marginTop: 12 }}>
          <div style={{
            display: 'flex',
            gap: 8,
            background: '#fff',
            borderRadius: 12,
            padding: '8px 12px',
            boxShadow: '0 2px 12px rgba(0,0,0,0.08)',
            border: '1px solid #e8e8e8',
            alignItems: 'flex-end',
          }}>
            <TextArea
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder="输入你的问题..."
              autoSize={{ minRows: 1, maxRows: 4 }}
              onPressEnter={(e) => {
                if (!e.shiftKey) { e.preventDefault(); handleSend() }
              }}
              disabled={isStreaming}
              variant="borderless"
              style={{ flex: 1, resize: 'none' }}
            />
            {isStreaming ? (
              <Tooltip title="停止生成">
                <Button
                  type="default"
                  danger
                  icon={<StopOutlined />}
                  onClick={stopStreaming}
                  style={{ borderRadius: 8 }}
                />
              </Tooltip>
            ) : (
              <Button
                type="primary"
                icon={<SendOutlined />}
                onClick={handleSend}
                disabled={!inputValue.trim()}
                style={{ borderRadius: 8 }}
              />
            )}
          </div>
        </div>
      </Content>
    </Layout>
  )
}
