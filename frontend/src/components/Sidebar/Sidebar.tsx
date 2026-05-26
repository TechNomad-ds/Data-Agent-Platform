import { useState, useEffect } from 'react'
import { Input, Button, Typography, Upload, message, Tooltip } from 'antd'
import { PlusOutlined, SearchOutlined, CloudUploadOutlined } from '@ant-design/icons'
import { useNavigate } from 'react-router-dom'
import { DataSpace, dataSpacesApi } from '@/api/dataSpaces'
import { chatApi } from '@/api/chat'
import { useChatStore } from '@/stores/chatStore'
import DataSpaceSelector from './DataSpaceSelector'
import ConversationList from './ConversationList'

const { Text } = Typography

interface Props {
  collapsed: boolean
  onSpaceChange?: (spaceId: string | undefined) => void
}

export default function Sidebar({ collapsed, onSpaceChange }: Props) {
  const navigate = useNavigate()
  const {
    conversations, setConversations,
    currentConversation, setCurrentConversation,
    setMessages, resetStream,
  } = useChatStore()

  const [spaces, setSpaces] = useState<DataSpace[]>([])
  const [selectedSpaceId, setSelectedSpaceId] = useState<string | undefined>()
  const [searchText, setSearchText] = useState('')

  useEffect(() => {
    onSpaceChange?.(selectedSpaceId)
  }, [selectedSpaceId])

  useEffect(() => {
    loadSpaces()
    loadConversations()
  }, [])

  const loadSpaces = async () => {
    try {
      const res = await dataSpacesApi.list()
      setSpaces(res.data)
    } catch {}
  }

  const loadConversations = async () => {
    try {
      const res = await chatApi.listConversations()
      setConversations(res.data)
    } catch {}
  }

  const handleNewConversation = () => {
    setCurrentConversation(null)
    setMessages([])
    resetStream()
    navigate('/chat')
  }

  const handleSelectConversation = (id: string) => {
    navigate(`/chat/${id}`)
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

  const handleUpload = async (file: File) => {
    if (!selectedSpaceId) {
      message.warning('请先选择数据空间')
      return false
    }
    const formData = new FormData()
    formData.append('files', file)
    try {
      await dataSpacesApi.uploadFiles(selectedSpaceId, formData)
      message.success(`${file.name} 上传成功`)
      loadSpaces()
    } catch {
      message.error('上传失败')
    }
    return false
  }

  const filteredConversations = searchText
    ? conversations.filter(c =>
        (c.title || '').toLowerCase().includes(searchText.toLowerCase())
      )
    : conversations

  const spaceConversations = selectedSpaceId
    ? filteredConversations.filter(c => c.data_space_id === selectedSpaceId)
    : filteredConversations

  if (collapsed) return null

  return (
    <div style={{
      width: 300,
      height: '100vh',
      display: 'flex',
      flexDirection: 'column',
      background: '#ffffff',
      borderRight: '1px solid #e2e8f0',
      flexShrink: 0,
    }}>
      {/* Header */}
      <div style={{ padding: '16px 14px 12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 14 }}>
          <div style={{
            width: 32, height: 32, borderRadius: 8,
            background: 'linear-gradient(135deg, #4f46e5, #7c3aed)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 16, color: '#fff', fontWeight: 700,
          }}>
            D
          </div>
          <Text style={{ fontSize: 15, fontWeight: 600, color: '#1e293b' }}>
            Data Agent
          </Text>
        </div>

        <DataSpaceSelector
          spaces={spaces}
          selectedSpaceId={selectedSpaceId}
          onSelect={setSelectedSpaceId}
          onRefresh={loadSpaces}
        />
      </div>

      {/* Actions */}
      <div style={{ padding: '0 14px 10px', display: 'flex', gap: 6 }}>
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={handleNewConversation}
          style={{ flex: 1, height: 34, fontSize: 13 }}
        >
          新对话
        </Button>
        <Upload
          showUploadList={false}
          multiple
          beforeUpload={handleUpload}
          accept=".csv,.xlsx,.xls,.json,.txt,.md,.pdf,.docx,.py,.sql,.html,.xml,.zip"
        >
          <Tooltip title={selectedSpaceId ? '上传文件到数据空间' : '请先选择数据空间'}>
            <Button
              icon={<CloudUploadOutlined />}
              style={{ height: 34 }}
              disabled={!selectedSpaceId}
            />
          </Tooltip>
        </Upload>
      </div>

      {/* Search */}
      <div style={{ padding: '0 14px 10px' }}>
        <Input
          prefix={<SearchOutlined style={{ color: '#94a3b8' }} />}
          placeholder="搜索对话..."
          value={searchText}
          onChange={e => setSearchText(e.target.value)}
          allowClear
          style={{ height: 32, fontSize: 13 }}
        />
      </div>

      {/* Conversation List */}
      <ConversationList
        conversations={spaceConversations}
        currentId={currentConversation?.id}
        onSelect={handleSelectConversation}
        onDelete={handleDeleteConversation}
      />

      {/* Footer */}
      <div style={{
        padding: '12px 14px',
        borderTop: '1px solid #e2e8f0',
        fontSize: 11,
        color: '#94a3b8',
        textAlign: 'center',
      }}>
        Data Agent Platform v1.0
      </div>
    </div>
  )
}
