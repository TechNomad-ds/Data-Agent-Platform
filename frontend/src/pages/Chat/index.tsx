import { useEffect, useState, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Layout, List, Button, Input, Select, Space, Typography, Card, Spin, message } from 'antd'
import {
  PlusOutlined, SendOutlined, RobotOutlined,
  DatabaseOutlined, DeleteOutlined,
} from '@ant-design/icons'
import { chatApi, Message, SSEEvent } from '@/api/chat'
import { dataSpacesApi, DataSpace } from '@/api/dataSpaces'
import { useChatStore } from '@/stores/chatStore'
import { useAuthStore } from '@/stores/authStore'
import ToolCard from '@/components/Chat/ToolCard'
import MessageContent from '@/components/Chat/MessageContent'

const { Sider, Content } = Layout
const { Text, Title } = Typography
const { TextArea } = Input

export default function Chat() {
  const { conversationId } = useParams()
  const navigate = useNavigate()
  const token = useAuthStore((s) => s.token)

  const {
    conversations, setConversations, currentConversation, setCurrentConversation,
    messages, setMessages, streamingContent, toolEvents,
    isStreaming, setIsStreaming, appendStreamDelta, addToolEvent, resetStream,
  } = useChatStore()

  const [spaces, setSpaces] = useState<DataSpace[]>([])
  const [selectedSpace, setSelectedSpace] = useState<string | undefined>()
  const [selectedModel, setSelectedModel] = useState('gpt-4o')
  const [inputValue, setInputValue] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    loadConversations()
    loadSpaces()
  }, [])

  useEffect(() => {
    if (conversationId) loadConversation(conversationId)
  }, [conversationId])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, streamingContent, toolEvents])

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

  const handleSend = async () => {
    if (!inputValue.trim() || isStreaming) return

    const convId = currentConversation?.id
    if (!convId) {
      // 自动创建对话
      try {
        const res = await chatApi.createConversation({
          data_space_id: selectedSpace,
          model_id: selectedModel,
        })
        setCurrentConversation(res.data)
        navigate(`/chat/${res.data.id}`)
        loadConversations()
        await sendMessage(res.data.id, inputValue)
      } catch {
        message.error('创建对话失败')
      }
      return
    }

    await sendMessage(convId, inputValue)
  }

  const sendMessage = async (convId: string, content: string) => {
    // 添加用户消息到界面
    const userMsg: Message = {
      id: Date.now().toString(),
      role: 'user',
      content,
      tool_calls: null,
      token_usage: null,
      credits_used: null,
      created_at: new Date().toISOString(),
    }
    setMessages([...messages, userMsg])
    setInputValue('')
    resetStream()
    setIsStreaming(true)

    try {
      const response = await fetch(`/api/chat/conversations/${convId}/messages`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({ content }),
      })

      if (!response.ok) {
        throw new Error('请求失败')
      }

      const reader = response.body?.getReader()
      const decoder = new TextDecoder()

      if (!reader) return

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        const text = decoder.decode(value, { stream: true })
        const lines = text.split('\n')

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const data = line.slice(6)
            if (data === '[DONE]') continue

            try {
              const event: SSEEvent = JSON.parse(data)
              if (event.type === 'text' && event.delta) {
                appendStreamDelta(event.delta)
              } else if (event.type === 'tool_use' || event.type === 'tool_result') {
                addToolEvent(event)
              } else if (event.type === 'error') {
                message.error(event.message || 'Agent 执行出错')
              }
            } catch {}
          }
        }
      }

      // 流结束，将内容添加为助手消息
      const finalContent = useChatStore.getState().streamingContent
      if (finalContent) {
        const assistantMsg: Message = {
          id: (Date.now() + 1).toString(),
          role: 'assistant',
          content: finalContent,
          tool_calls: null,
          token_usage: null,
          credits_used: null,
          created_at: new Date().toISOString(),
        }
        setMessages([...useChatStore.getState().messages, assistantMsg])
      }
    } catch (err) {
      message.error('发送消息失败')
    } finally {
      setIsStreaming(false)
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
      <Sider width={280} theme="light" style={{ borderRight: '1px solid #f0f0f0', borderRadius: 8, overflow: 'auto' }}>
        <div style={{ padding: 16 }}>
          <Button type="primary" icon={<PlusOutlined />} block onClick={handleNewConversation}>
            新建对话
          </Button>
        </div>
        <List
          dataSource={conversations}
          renderItem={(item) => (
            <List.Item
              style={{
                padding: '8px 16px',
                cursor: 'pointer',
                background: currentConversation?.id === item.id ? '#e6f4ff' : 'transparent',
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
                title={<Text ellipsis style={{ maxWidth: 160 }}>{item.title || '新对话'}</Text>}
                description={<Text type="secondary" style={{ fontSize: 12 }}>{new Date(item.updated_at).toLocaleString('zh-CN')}</Text>}
              />
            </List.Item>
          )}
        />
      </Sider>

      {/* 右侧聊天区域 */}
      <Content style={{ display: 'flex', flexDirection: 'column', padding: '0 0 0 16px' }}>
        {/* 顶部选择器 */}
        <Card size="small" style={{ marginBottom: 12, borderRadius: 8 }}>
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
              value={selectedModel}
              onChange={setSelectedModel}
              style={{ width: 160 }}
              options={[
                { label: '经济模型', value: 'deepseek-chat' },
                { label: '标准模型', value: 'gpt-4o-mini' },
                { label: '高级模型', value: 'gpt-4o' },
                { label: '顶级模型', value: 'claude-sonnet-4-6' },
              ]}
            />
          </Space>
        </Card>

        {/* 消息区域 */}
        <div style={{ flex: 1, overflow: 'auto', borderRadius: 8, background: '#fff', padding: 16 }}>
          {messages.length === 0 && !isStreaming ? (
            <div style={{ textAlign: 'center', paddingTop: 80 }}>
              <RobotOutlined style={{ fontSize: 48, color: '#bfbfbf' }} />
              <Title level={5} type="secondary" style={{ marginTop: 16 }}>
                选择数据空间，开始与 Data Agent 对话
              </Title>
              <Text type="secondary">
                我可以帮你分析数据、回答文档问题、执行代码、生成图表
              </Text>
            </div>
          ) : (
            <>
              {messages.map((msg) => (
                <div key={msg.id} style={{ marginBottom: 16 }}>
                  <MessageContent message={msg} />
                </div>
              ))}

              {/* 流式内容 */}
              {isStreaming && (
                <div style={{ marginBottom: 16 }}>
                  {toolEvents.map((event, i) => (
                    <ToolCard key={i} event={event} />
                  ))}
                  {streamingContent && (
                    <div style={{ display: 'flex', gap: 8 }}>
                      <RobotOutlined style={{ marginTop: 4, color: '#1677ff' }} />
                      <div style={{ flex: 1 }}>
                        <MessageContent message={{ id: 'streaming', role: 'assistant', content: streamingContent, tool_calls: null, token_usage: null, credits_used: null, created_at: '' }} />
                      </div>
                    </div>
                  )}
                  {!streamingContent && toolEvents.length === 0 && <Spin tip="思考中..." />}
                </div>
              )}
            </>
          )}
          <div ref={messagesEndRef} />
        </div>

        {/* 输入区域 */}
        <div style={{ marginTop: 12 }}>
          <Space.Compact style={{ width: '100%' }}>
            <TextArea
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              placeholder="输入你的问题..."
              autoSize={{ minRows: 1, maxRows: 4 }}
              onPressEnter={(e) => {
                if (!e.shiftKey) { e.preventDefault(); handleSend() }
              }}
              disabled={isStreaming}
              style={{ borderRadius: '8px 0 0 8px' }}
            />
            <Button
              type="primary"
              icon={<SendOutlined />}
              onClick={handleSend}
              loading={isStreaming}
              style={{ height: 'auto', borderRadius: '0 8px 8px 0' }}
            />
          </Space.Compact>
        </div>
      </Content>
    </Layout>
  )
}
