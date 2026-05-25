import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Row, Col, Card, Statistic, Typography, Space, Button, List } from 'antd'
import {
  DatabaseOutlined,
  FileOutlined,
  MessageOutlined,
  WalletOutlined,
  PlusOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons'
import { dataSpacesApi, DataSpace } from '@/api/dataSpaces'
import { chatApi, Conversation } from '@/api/chat'
import api from '@/api/client'

const { Title, Text } = Typography

export default function Dashboard() {
  const navigate = useNavigate()
  const [spaces, setSpaces] = useState<DataSpace[]>([])
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [balance, setBalance] = useState(0)
  const [fileCount, setFileCount] = useState(0)

  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    try {
      const [spacesRes, convsRes, creditsRes, filesRes] = await Promise.all([
        dataSpacesApi.list(),
        chatApi.listConversations(),
        api.get('/credits/balance'),
        api.get('/files', { params: { page: 1, page_size: 1 } }),
      ])
      setSpaces(spacesRes.data)
      setConversations(convsRes.data)
      setBalance(creditsRes.data.balance)
      setFileCount(filesRes.data.total)
    } catch {
      // 静默处理
    }
  }

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <Title level={4} style={{ marginBottom: 4 }}>工作台</Title>
        <Text type="secondary">欢迎使用 Data Agent 智能数据交互平台</Text>
      </div>

      {/* 统计卡片 */}
      <Row gutter={[16, 16]} style={{ marginBottom: 24 }}>
        <Col xs={12} sm={6}>
          <Card hoverable onClick={() => navigate('/data-spaces')}>
            <Statistic title="数据空间" value={spaces.length} prefix={<DatabaseOutlined />} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card hoverable onClick={() => navigate('/data-spaces')}>
            <Statistic title="文件总数" value={fileCount} prefix={<FileOutlined />} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card hoverable onClick={() => navigate('/chat')}>
            <Statistic title="对话数" value={conversations.length} prefix={<MessageOutlined />} />
          </Card>
        </Col>
        <Col xs={12} sm={6}>
          <Card hoverable onClick={() => navigate('/credits')}>
            <Statistic title="剩余额度" value={balance} prefix={<WalletOutlined />} suffix="点" />
          </Card>
        </Col>
      </Row>

      {/* 快捷操作 */}
      <Row gutter={[16, 16]}>
        <Col xs={24} md={12}>
          <Card
            title="快速开始"
            extra={<Button type="link" onClick={() => navigate('/chat')}>开始对话</Button>}
          >
            <Space direction="vertical" style={{ width: '100%' }}>
              <Button
                icon={<PlusOutlined />}
                block
                onClick={() => navigate('/data-spaces')}
                style={{ textAlign: 'left' }}
              >
                创建数据空间
              </Button>
              <Button
                icon={<FileOutlined />}
                block
                onClick={() => navigate('/data-spaces')}
                style={{ textAlign: 'left' }}
              >
                上传数据文件
              </Button>
              <Button
                icon={<ThunderboltOutlined />}
                block
                type="primary"
                onClick={() => navigate('/chat')}
                style={{ textAlign: 'left' }}
              >
                与 Data Agent 对话
              </Button>
            </Space>
          </Card>
        </Col>
        <Col xs={24} md={12}>
          <Card title="最近对话">
            <List
              dataSource={conversations.slice(0, 5)}
              renderItem={(item) => (
                <List.Item
                  style={{ cursor: 'pointer' }}
                  onClick={() => navigate(`/chat/${item.id}`)}
                >
                  <List.Item.Meta
                    title={item.title || '新对话'}
                    description={new Date(item.updated_at).toLocaleString('zh-CN')}
                  />
                </List.Item>
              )}
              locale={{ emptyText: '暂无对话记录' }}
            />
          </Card>
        </Col>
      </Row>
    </div>
  )
}
