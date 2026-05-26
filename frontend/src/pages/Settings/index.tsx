import { useState, useEffect } from 'react'
import { Typography, Card, Button, Table, Tag, Modal, Form, Input, Select, message, Popconfirm, Empty } from 'antd'
import { PlusOutlined, DeleteOutlined, KeyOutlined, ApiOutlined } from '@ant-design/icons'
import { settingsApi, ApiKeyConfig, ApiKeyCreateData } from '@/api/settings'

const { Title, Text } = Typography

export default function SettingsPage() {
  const [keys, setKeys] = useState<ApiKeyConfig[]>([])
  const [modalOpen, setModalOpen] = useState(false)
  const [form] = Form.useForm()
  const [provider, setProvider] = useState<string>('openai')

  useEffect(() => { loadKeys() }, [])

  const loadKeys = async () => {
    try { setKeys((await settingsApi.listApiKeys()).data) }
    catch { /* ignore */ }
  }

  const handleCreate = async (values: ApiKeyCreateData) => {
    try {
      await settingsApi.createApiKey(values)
      message.success('API Key 已添加')
      setModalOpen(false)
      form.resetFields()
      loadKeys()
    } catch {
      message.error('添加失败，请检查配置')
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await settingsApi.deleteApiKey(id)
      message.success('已删除')
      loadKeys()
    } catch {
      message.error('删除失败')
    }
  }

  return (
    <div style={{ height: '100vh', overflow: 'auto', background: '#f8fafc', padding: 32 }}>
      <div style={{ maxWidth: 800, margin: '0 auto' }}>
        <Title level={3} style={{ marginBottom: 8 }}>设置</Title>
        <Text type="secondary" style={{ display: 'block', marginBottom: 24 }}>
          配置你自己的 API Key 来使用模型，无需消耗平台额度
        </Text>

        <Card
          title={<span><KeyOutlined style={{ marginRight: 8 }} />我的 API Keys</span>}
          extra={<Button type="primary" icon={<PlusOutlined />} onClick={() => setModalOpen(true)}>添加 Key</Button>}
        >
          {keys.length === 0 ? (
            <Empty
              image={<ApiOutlined style={{ fontSize: 48, color: '#d9d9d9' }} />}
              description={
                <span>
                  <Text type="secondary">还没有配置 API Key</Text><br />
                  <Text type="secondary" style={{ fontSize: 12 }}>添加后可在聊天中选择"我的模型"，不消耗平台额度</Text>
                </span>
              }
            />
          ) : (
            <Table
              dataSource={keys}
              rowKey="id"
              size="small"
              pagination={false}
              columns={[
                {
                  title: '名称',
                  dataIndex: 'display_name',
                  render: (v: string, r: ApiKeyConfig) => (
                    <div>
                      <Text strong style={{ fontSize: 13 }}>{v}</Text>
                      <br />
                      <Text type="secondary" style={{ fontSize: 11 }}>{r.model_name}</Text>
                    </div>
                  ),
                },
                {
                  title: 'Provider',
                  dataIndex: 'provider',
                  width: 100,
                  render: (v: string) => <Tag color={v === 'anthropic' ? 'orange' : 'blue'}>{v}</Tag>,
                },
                {
                  title: 'API Key',
                  dataIndex: 'api_key_masked',
                  width: 140,
                  render: (v: string) => <Text code style={{ fontSize: 11 }}>{v}</Text>,
                },
                {
                  title: '状态',
                  dataIndex: 'is_active',
                  width: 70,
                  render: (v: boolean) => <Tag color={v ? 'green' : 'default'}>{v ? '启用' : '禁用'}</Tag>,
                },
                {
                  title: '',
                  width: 50,
                  render: (_: unknown, r: ApiKeyConfig) => (
                    <Popconfirm title="确定删除？" onConfirm={() => handleDelete(r.id)} okText="删除" cancelText="取消">
                      <Button type="text" size="small" danger icon={<DeleteOutlined />} />
                    </Popconfirm>
                  ),
                },
              ]}
            />
          )}
        </Card>

        <Card title="使用说明" style={{ marginTop: 16 }} size="small">
          <div style={{ fontSize: 13, color: '#64748b', lineHeight: 2 }}>
            <p><strong>Anthropic</strong>：直接填入 API Key，模型名如 <code>claude-sonnet-4-20250514</code></p>
            <p><strong>OpenAI 兼容</strong>：支持 DeepSeek、Qwen、GLM 等。填入 API Key + Base URL + 模型名</p>
            <p>配置后在聊天界面的模型选择器中会出现"我的模型"分组，选择后不消耗平台额度。</p>
          </div>
        </Card>
      </div>

      <Modal
        title="添加 API Key"
        open={modalOpen}
        onCancel={() => { setModalOpen(false); form.resetFields() }}
        onOk={() => form.submit()}
        okText="添加"
        cancelText="取消"
      >
        <Form form={form} layout="vertical" onFinish={handleCreate} initialValues={{ provider: 'openai' }}>
          <Form.Item name="display_name" label="显示名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="如：我的 Claude Sonnet" />
          </Form.Item>
          <Form.Item name="provider" label="Provider" rules={[{ required: true }]}>
            <Select onChange={setProvider} options={[
              { label: 'OpenAI 兼容（DeepSeek/Qwen/GLM 等）', value: 'openai' },
              { label: 'Anthropic（Claude）', value: 'anthropic' },
            ]} />
          </Form.Item>
          <Form.Item name="api_key" label="API Key" rules={[{ required: true, message: '请输入 API Key' }]}>
            <Input.Password placeholder="sk-..." />
          </Form.Item>
          {provider === 'openai' && (
            <Form.Item name="api_base_url" label="Base URL" rules={[{ required: true, message: '请输入 API 地址' }]}>
              <Input placeholder="https://api.deepseek.com/v1" />
            </Form.Item>
          )}
          <Form.Item name="model_name" label="模型名称" rules={[{ required: true, message: '请输入模型名' }]}>
            <Input placeholder={provider === 'anthropic' ? 'claude-sonnet-4-20250514' : 'deepseek-chat'} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
