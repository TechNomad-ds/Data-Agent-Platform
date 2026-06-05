import { useEffect, useState } from 'react'
import { Card, Statistic, Table, Typography, Tag, Button, Input, Form, Modal, Select, Popconfirm, message } from 'antd'
import { WalletOutlined, ThunderboltOutlined, ApiOutlined, DeleteOutlined, PlusOutlined, CheckCircleOutlined } from '@ant-design/icons'
import api from '@/api/client'
import { settingsApi, ApiConfig, ModelOption } from '@/api/settings'
import { useIsMobile } from '@/hooks/useIsMobile'

const { Title, Text } = Typography

interface Transaction {
  id: string
  amount: number
  balance_after: number
  transaction_type: string
  description: string | null
  created_at: string
}

export default function Credits() {
  const [balance, setBalance] = useState(0)
  const [dailyAllowance, setDailyAllowance] = useState(0)
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)

  const [apiMode, setApiMode] = useState<'credits' | 'own_api'>('credits')
  const [apiConfig, setApiConfig] = useState<ApiConfig>({ configured: false })
  const [models, setModels] = useState<ModelOption[]>([])

  const [configModalOpen, setConfigModalOpen] = useState(false)
  const [configForm] = Form.useForm()
  const isMobile = useIsMobile()
  const [saving, setSaving] = useState(false)

  const [mappingModalOpen, setMappingModalOpen] = useState(false)
  const [mappingForm] = Form.useForm()
  const [addingMapping, setAddingMapping] = useState(false)

  useEffect(() => {
    loadBalance()
    loadHistory()
  }, [page])

  useEffect(() => {
    loadApiMode()
    loadApiConfig()
    loadModels()
  }, [])

  const loadBalance = async () => {
    try {
      const res = await api.get('/credits/balance')
      setBalance(res.data.balance)
      setDailyAllowance(res.data.daily_free_allowance)
    } catch {}
  }

  const loadHistory = async () => {
    try {
      const res = await api.get('/credits/history', { params: { page, page_size: 20 } })
      setTransactions(res.data.transactions)
      setTotal(res.data.total)
    } catch {}
  }

  const loadApiMode = async () => {
    try {
      const res = await settingsApi.getApiMode()
      setApiMode(res.data.mode as 'credits' | 'own_api')
    } catch {}
  }

  const loadApiConfig = async () => {
    try {
      const res = await settingsApi.getApiConfig()
      setApiConfig(res.data)
    } catch {}
  }

  const loadModels = async () => {
    try {
      const res = await settingsApi.listModels()
      setModels(res.data)
    } catch {}
  }

  const handleSwitchMode = async (mode: 'credits' | 'own_api') => {
    if (mode === 'own_api') {
      try {
        const latest = await settingsApi.getApiConfig()
        setApiConfig(latest.data)
        if (!latest.data.configured) {
          message.warning('请先配置 API')
          setConfigModalOpen(true)
          return
        }
      } catch {
        message.error('获取配置失败')
        return
      }
    }
    try {
      await settingsApi.setApiMode(mode)
      setApiMode(mode)
    } catch {}
  }

  const handleSaveConfig = async (values: { api_base_url: string; api_key: string }) => {
    setSaving(true)
    try {
      const res = await settingsApi.saveApiConfig(values)
      setApiConfig(res.data)
      message.success('API 配置已保存')
      setConfigModalOpen(false)
      configForm.resetFields()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const handleDeleteConfig = async () => {
    try {
      await settingsApi.deleteApiConfig()
      setApiConfig({ configured: false })
      setApiMode('credits')
      message.success('API 配置已删除')
    } catch {}
  }

  const handleAddMapping = async (values: { platform_model_id: string; api_model_name: string }) => {
    setAddingMapping(true)
    try {
      const res = await settingsApi.addMapping(values.platform_model_id, values.api_model_name)
      setApiConfig(prev => ({ ...prev, model_mappings: res.data.model_mappings }))
      message.success('映射已添加，验证通过')
      setMappingModalOpen(false)
      mappingForm.resetFields()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '添加失败')
    } finally {
      setAddingMapping(false)
    }
  }

  const handleDeleteMapping = async (modelId: string) => {
    try {
      const res = await settingsApi.deleteMapping(modelId)
      setApiConfig(prev => ({ ...prev, model_mappings: res.data.model_mappings }))
      message.success('映射已删除')
    } catch {}
  }

  const mappings = apiConfig.model_mappings || {}
  const unmappedModels = models.filter(m => !(m.id in mappings))

  const typeMap: Record<string, { label: string; color: string }> = {
    usage: { label: '使用消耗', color: 'red' },
    daily_grant: { label: '每日赠送', color: 'green' },
    admin_grant: { label: '管理员调整', color: 'blue' },
    purchase: { label: '充值', color: 'gold' },
  }

  const cardStyle = (active: boolean): React.CSSProperties => ({
    flex: 1,
    cursor: 'pointer',
    border: active ? '2px solid #1677ff' : '1px solid #e2e8f0',
    borderRadius: 12,
    transition: 'all 0.2s',
    opacity: active ? 1 : 0.6,
  })

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <Title level={4} style={{ marginBottom: 4 }}>额度与 API</Title>
        <Text type="secondary">选择使用平台额度或自己的 API</Text>
      </div>

      {/* 两个模式卡片 */}
      <div style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', gap: 16, marginBottom: 24 }}>
        {/* 使用平台额度 */}
        <Card
          style={cardStyle(apiMode === 'credits')}
          onClick={() => handleSwitchMode('credits')}
          bodyStyle={{ padding: 20 }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
            <Text strong style={{ fontSize: 15 }}>使用平台额度</Text>
            {apiMode === 'credits' && <CheckCircleOutlined style={{ color: '#1677ff', marginLeft: 'auto' }} />}
          </div>
          <Statistic title="当前余额" value={balance} prefix={<WalletOutlined />} suffix="点" />
          <div style={{ marginTop: 12 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>
              <ThunderboltOutlined /> 每日免费 {dailyAllowance} 点
            </Text>
          </div>
        </Card>

        {/* 使用自己的 API */}
        <Card
          style={cardStyle(apiMode === 'own_api')}
          onClick={() => handleSwitchMode('own_api')}
          bodyStyle={{ padding: 20 }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
            <Text strong style={{ fontSize: 15 }}>使用自己的 API</Text>
            <Text type="secondary" style={{ fontSize: 12 }}>不消耗平台额度</Text>
            {apiMode === 'own_api' && <CheckCircleOutlined style={{ color: '#1677ff', marginLeft: 'auto' }} />}
          </div>

          {!apiConfig.configured ? (
            <div style={{ textAlign: 'center', padding: '12px 0' }}>
              <ApiOutlined style={{ fontSize: 28, color: '#d9d9d9', marginBottom: 8 }} />
              <br />
              <Button size="small" onClick={(e) => { e.stopPropagation(); setConfigModalOpen(true) }}>
                配置 API
              </Button>
            </div>
          ) : (
            <div onClick={(e) => e.stopPropagation()}>
              <div style={{ fontSize: 12, color: '#64748b', marginBottom: 4 }}>
                API 地址: <Text code style={{ fontSize: 11 }}>{apiConfig.api_base_url}</Text>
              </div>
              <div style={{ fontSize: 12, color: '#64748b', marginBottom: 12 }}>
                API Key: <Text code style={{ fontSize: 11 }}>{apiConfig.api_key_masked}</Text>
                <Button type="link" size="small" onClick={() => setConfigModalOpen(true)} style={{ fontSize: 11, padding: '0 4px' }}>修改</Button>
                <Popconfirm title="确定删除 API 配置？" onConfirm={handleDeleteConfig} okText="删除" cancelText="取消">
                  <Button type="link" size="small" danger style={{ fontSize: 11, padding: '0 4px' }}>删除</Button>
                </Popconfirm>
              </div>

              {/* 模型映射 */}
              <div style={{ fontSize: 12, fontWeight: 500, color: '#334155', marginBottom: 8 }}>模型映射</div>
              {Object.entries(mappings).map(([platformId, apiName]) => {
                const model = models.find(m => m.id === platformId)
                return (
                  <div key={platformId} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6, fontSize: 12 }}>
                    <Tag color="blue">{model?.display_name || platformId}</Tag>
                    <span style={{ color: '#94a3b8' }}>→</span>
                    <Tag>{apiName}</Tag>
                    <Popconfirm title="删除映射？" onConfirm={() => handleDeleteMapping(platformId)} okText="删" cancelText="取消">
                      <DeleteOutlined style={{ color: '#ef4444', cursor: 'pointer', fontSize: 11 }} />
                    </Popconfirm>
                  </div>
                )
              })}
              {unmappedModels.length > 0 && (
                <Button
                  type="dashed"
                  size="small"
                  icon={<PlusOutlined />}
                  onClick={() => setMappingModalOpen(true)}
                  style={{ fontSize: 11, marginTop: 4 }}
                >
                  添加映射
                </Button>
              )}
            </div>
          )}
        </Card>
      </div>

      {/* 使用记录 */}
      <Card title="使用记录">
        <Table
          columns={[
            { title: '时间', dataIndex: 'created_at', width: 180, render: (t: string) => new Date(t).toLocaleString('zh-CN') },
            { title: '类型', dataIndex: 'transaction_type', width: 120, render: (t: string) => { const m = typeMap[t] || { label: t, color: 'default' }; return <Tag color={m.color}>{m.label}</Tag> } },
            { title: '变动', dataIndex: 'amount', width: 100, render: (a: number) => <Text style={{ fontWeight: 500 }} type={a > 0 ? 'success' : 'danger'}>{a > 0 ? '+' : ''}{a}</Text> },
            { title: '余额', dataIndex: 'balance_after', width: 100 },
            { title: '说明', dataIndex: 'description', render: (d: string | null) => d || '-' },
          ]}
          dataSource={transactions}
          rowKey="id"
          size="small"
          scroll={{ x: 'max-content' }}
          pagination={{ current: page, total, pageSize: 20, onChange: setPage, showTotal: (t) => `共 ${t} 条记录` }}
        />
      </Card>

      {/* 配置 API Modal */}
      <Modal
        title="配置 API"
        open={configModalOpen}
        onCancel={() => { if (!saving) { setConfigModalOpen(false); configForm.resetFields() } }}
        onOk={() => configForm.submit()}
        okText={saving ? '验证中...' : '保存'}
        confirmLoading={saving}
        cancelText="取消"
      >
        <Form form={configForm} layout="vertical" onFinish={handleSaveConfig}>
          <Form.Item name="api_base_url" label="API 地址" rules={[{ required: true, message: '请输入 API 地址' }]}>
            <Input placeholder="https://api.deepseek.com/v1" />
          </Form.Item>
          <Form.Item name="api_key" label="API Key" rules={[{ required: true, message: '请输入 API Key' }]}>
            <Input.Password placeholder="sk-..." />
          </Form.Item>
        </Form>
        <Text type="secondary" style={{ fontSize: 12 }}>
          支持所有 OpenAI 兼容接口。保存后还需添加模型映射才能使用。
        </Text>
      </Modal>

      {/* 添加映射 Modal */}
      <Modal
        title="添加模型映射"
        open={mappingModalOpen}
        onCancel={() => { if (!addingMapping) { setMappingModalOpen(false); mappingForm.resetFields() } }}
        onOk={() => mappingForm.submit()}
        okText={addingMapping ? '验证中...' : '添加'}
        confirmLoading={addingMapping}
        cancelText="取消"
      >
        <Form form={mappingForm} layout="vertical" onFinish={handleAddMapping}>
          <Form.Item name="platform_model_id" label="平台模型" rules={[{ required: true, message: '请选择' }]}>
            <Select
              placeholder="选择要映射的模型"
              options={unmappedModels.map(m => ({ label: m.display_name, value: m.id }))}
            />
          </Form.Item>
          <Form.Item name="api_model_name" label="你的 API 对应的模型名称" rules={[{ required: true, message: '请输入你的 API 使用的模型名' }]}>
            <Input placeholder="如 deepseek-chat、gpt-4o 等" />
          </Form.Item>
        </Form>
        <Text type="secondary" style={{ fontSize: 12 }}>
          添加时会用你的 API 测试该模型是否可用。
        </Text>
      </Modal>
    </div>
  )
}
