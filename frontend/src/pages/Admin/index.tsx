import { useEffect, useState } from 'react'
import { Tabs, Table, Card, Button, Typography, Tag, Modal, Form, Input, InputNumber, message } from 'antd'
import api from '@/api/client'
import { UserInfo } from '@/api/auth'

const { Title, Text } = Typography

export default function Admin() {
  const [activeTab, setActiveTab] = useState('users')
  const [users, setUsers] = useState<UserInfo[]>([])
  const [models, setModels] = useState<any[]>([])
  const [modelModalOpen, setModelModalOpen] = useState(false)
  const [modelForm] = Form.useForm()

  useEffect(() => {
    if (activeTab === 'users') loadUsers()
    if (activeTab === 'models') loadModels()
  }, [activeTab])

  const loadUsers = async () => {
    try {
      const res = await api.get('/admin/users')
      setUsers(res.data)
    } catch {}
  }

  const loadModels = async () => {
    try {
      const res = await api.get('/admin/models')
      setModels(res.data)
    } catch {}
  }

  const toggleUserStatus = async (userId: string, isActive: boolean) => {
    try {
      await api.put(`/admin/users/${userId}`, { is_active: !isActive })
      message.success('已更新')
      loadUsers()
    } catch {}
  }

  const handleAddModel = async (values: any) => {
    try {
      await api.post('/admin/models', values)
      message.success('模型已添加')
      setModelModalOpen(false)
      modelForm.resetFields()
      loadModels()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '添加失败')
    }
  }

  const userColumns = [
    { title: '用户名', dataIndex: 'username', key: 'username' },
    { title: '邮箱', dataIndex: 'email', key: 'email' },
    { title: '角色', dataIndex: 'role', key: 'role', render: (r: string) => <Tag>{r}</Tag> },
    {
      title: '状态', dataIndex: 'is_active', key: 'is_active',
      render: (v: boolean) => <Tag color={v ? 'success' : 'error'}>{v ? '正常' : '已禁用'}</Tag>,
    },
    { title: '注册时间', dataIndex: 'created_at', key: 'created_at', render: (t: string) => new Date(t).toLocaleDateString('zh-CN') },
    {
      title: '操作', key: 'action',
      render: (_: unknown, record: UserInfo) => (
        <Button size="small" onClick={() => toggleUserStatus(record.id, record.is_active)}>
          {record.is_active ? '禁用' : '启用'}
        </Button>
      ),
    },
  ]

  const modelColumns = [
    { title: 'ID', dataIndex: 'id', key: 'id' },
    { title: '显示名称', dataIndex: 'display_name', key: 'display_name' },
    { title: '供应商', dataIndex: 'provider', key: 'provider' },
    { title: '模型名', dataIndex: 'model_name', key: 'model_name' },
    { title: '倍率', dataIndex: 'credit_multiplier', key: 'credit_multiplier' },
    {
      title: '状态', dataIndex: 'is_active', key: 'is_active',
      render: (v: boolean) => <Tag color={v ? 'success' : 'default'}>{v ? '启用' : '停用'}</Tag>,
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <Title level={4} style={{ marginBottom: 4 }}>管理后台</Title>
        <Text type="secondary">平台管理与配置</Text>
      </div>

      <Card>
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
          {
            key: 'users',
            label: '用户管理',
            children: <Table columns={userColumns} dataSource={users} rowKey="id" />,
          },
          {
            key: 'models',
            label: '模型配置',
            children: (
              <>
                <Button type="primary" style={{ marginBottom: 16 }} onClick={() => setModelModalOpen(true)}>
                  添加模型
                </Button>
                <Table columns={modelColumns} dataSource={models} rowKey="id" />
              </>
            ),
          },
        ]} />
      </Card>

      <Modal title="添加模型配置" open={modelModalOpen} onCancel={() => setModelModalOpen(false)} onOk={() => modelForm.submit()}>
        <Form form={modelForm} layout="vertical" onFinish={handleAddModel}>
          <Form.Item name="id" label="模型 ID" rules={[{ required: true }]}>
            <Input placeholder="例如: gpt-4o" />
          </Form.Item>
          <Form.Item name="display_name" label="显示名称" rules={[{ required: true }]}>
            <Input placeholder="例如: GPT-4o 高级模型" />
          </Form.Item>
          <Form.Item name="provider" label="供应商" rules={[{ required: true }]}>
            <Input placeholder="例如: openai" />
          </Form.Item>
          <Form.Item name="api_base" label="API 地址" rules={[{ required: true }]}>
            <Input placeholder="https://api.example.com/v1" />
          </Form.Item>
          <Form.Item name="api_key" label="API Key" rules={[{ required: true }]}>
            <Input.Password placeholder="sk-..." />
          </Form.Item>
          <Form.Item name="model_name" label="模型名称" rules={[{ required: true }]}>
            <Input placeholder="实际调用的模型名" />
          </Form.Item>
          <Form.Item name="credit_multiplier" label="额度倍率" initialValue={1.0}>
            <InputNumber min={0.1} max={100} step={0.5} />
          </Form.Item>
          <Form.Item name="max_tokens" label="最大 Token" initialValue={4096}>
            <InputNumber min={256} max={128000} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
