import { useEffect, useState } from 'react'
import { Tabs, Table, Card, Button, Typography, Tag, Modal, Form, Input, InputNumber, message, Statistic, Row, Col, Divider, Switch, Popconfirm, Space, Descriptions, Spin, Radio } from 'antd'
import {
  UserOutlined, ApiOutlined, BarChartOutlined, MessageOutlined,
  DatabaseOutlined, FileOutlined, WalletOutlined, TeamOutlined,
  RiseOutlined, ThunderboltOutlined, EditOutlined, DeleteOutlined,
  ExperimentOutlined, SettingOutlined, EyeOutlined, DownloadOutlined,
} from '@ant-design/icons'
import api from '@/api/client'
import { UserInfo } from '@/api/auth'
import { colors } from '@/styles/tokens'

const { Title, Text } = Typography

interface Stats {
  total_users: number
  total_files: number
  total_feedback: number
  total_conversations: number
  total_messages: number
  total_spaces: number
  active_users_today: number
  new_users_week: number
  messages_today: number
  total_credits_consumed: number
}

interface AdminConversation {
  id: string
  title: string
  model_id: string
  user_id: string
  username: string
  email: string
  created_at: string
  updated_at: string
}

export default function Admin() {
  const [activeTab, setActiveTab] = useState('stats')
  const [users, setUsers] = useState<UserInfo[]>([])
  const [models, setModels] = useState<any[]>([])
  const [conversations, setConversations] = useState<AdminConversation[]>([])
  const [convTotal, setConvTotal] = useState(0)
  const [convPage, setConvPage] = useState(1)
  const [stats, setStats] = useState<Stats>({
    total_users: 0, total_files: 0, total_feedback: 0,
    total_conversations: 0, total_messages: 0, total_spaces: 0,
    active_users_today: 0, new_users_week: 0, messages_today: 0,
    total_credits_consumed: 0,
  })
  const [modelModalOpen, setModelModalOpen] = useState(false)
  const [modelForm] = Form.useForm()
  const [editingModel, setEditingModel] = useState<any>(null)
  const [testing, setTesting] = useState(false)
  const [creditModalOpen, setCreditModalOpen] = useState(false)
  const [creditForm] = Form.useForm()
  const [runtimeConfig, setRuntimeConfig] = useState<Record<string, any>>({})
  const [configLoading, setConfigLoading] = useState(false)
  const [userDetail, setUserDetail] = useState<any>(null)
  const [userDetailLoading, setUserDetailLoading] = useState(false)
  const [userDetailModalOpen, setUserDetailModalOpen] = useState(false)
  const [researchStats, setResearchStats] = useState<any>(null)
  const [blockIp, setBlockIp] = useState('')
  const [blockHours, setBlockHours] = useState(24)
  const [unlockEmail, setUnlockEmail] = useState('')
  const [globalApiBase, setGlobalApiBase] = useState('')
  const [globalApiKey, setGlobalApiKey] = useState('')
  const [globalApiKeySet, setGlobalApiKeySet] = useState(false)
  const [exportFormat, setExportFormat] = useState<'json' | 'csv'>('json')
  const [exportConsentOnly, setExportConsentOnly] = useState(true)
  const [exporting, setExporting] = useState(false)

  useEffect(() => {
    if (activeTab === 'stats') loadStats()
    if (activeTab === 'users') loadUsers()
    if (activeTab === 'models') loadModels()
    if (activeTab === 'conversations') loadConversations()
    if (activeTab === 'config') loadConfig()
    if (activeTab === 'models') { loadModels(); loadGlobalApi() }
    if (activeTab === 'research') loadResearchStats()
  }, [activeTab, convPage])

  const loadStats = async () => {
    try {
      const res = await api.get('/admin/stats')
      setStats(res.data)
    } catch {}
  }

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

  const loadConversations = async () => {
    try {
      const res = await api.get('/admin/conversations', { params: { page: convPage, page_size: 20 } })
      setConversations(res.data.conversations)
      setConvTotal(res.data.total)
    } catch {}
  }

  const loadGlobalApi = async () => {
    try {
      const res = await api.get('/admin/global-api')
      setGlobalApiBase(res.data.api_base || '')
      setGlobalApiKeySet(res.data.api_key_set)
    } catch {}
  }

  const handleSaveGlobalApi = async () => {
    try {
      await api.put('/admin/global-api', { api_base: globalApiBase, api_key: globalApiKey })
      message.success('全局 API 配置已更新，所有模型已同步')
      setGlobalApiKey('')
      loadGlobalApi()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '保存失败')
    }
  }

  const loadConfig = async () => {
    setConfigLoading(true)
    try {
      const res = await api.get('/admin/config')
      setRuntimeConfig(res.data)
    } catch {}
    finally { setConfigLoading(false) }
  }

  const updateConfig = async (key: string, value: string) => {
    try {
      await api.put('/admin/config', { key, value })
      message.success('已更新')
      loadConfig()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '更新失败')
    }
  }

  const loadResearchStats = async () => {
    try {
      const res = await api.get('/admin/research/stats')
      setResearchStats(res.data)
    } catch {}
  }

  const handleExportResearch = async () => {
    setExporting(true)
    try {
      const res = await api.get('/admin/research/export', {
        params: { format: exportFormat, consent_only: exportConsentOnly },
        responseType: 'blob',
      })
      const ext = exportFormat === 'csv' ? 'csv' : 'jsonl'
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = `datamind_research_export.${ext}`
      a.click()
      URL.revokeObjectURL(url)
      message.success('导出成功')
    } catch {
      message.error('导出失败')
    } finally {
      setExporting(false)
    }
  }

  const loadUserDetail = async (userId: string) => {
    setUserDetailLoading(true)
    setUserDetailModalOpen(true)
    try {
      const res = await api.get(`/admin/users/${userId}/detail`)
      setUserDetail(res.data)
    } catch { message.error('加载失败') }
    finally { setUserDetailLoading(false) }
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
      if (editingModel) {
        await api.put(`/admin/models/${editingModel.id}`, values)
        message.success('模型已更新')
      } else {
        await api.post('/admin/models', values)
        message.success('模型已添加')
      }
      setModelModalOpen(false)
      setEditingModel(null)
      modelForm.resetFields()
      loadModels()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '操作失败')
    }
  }

  const handleEditModel = (model: any) => {
    setEditingModel(model)
    modelForm.setFieldsValue({
      ...model,
      api_key: '',
    })
    setModelModalOpen(true)
  }

  const handleDeleteModel = async (modelId: string) => {
    try {
      await api.delete(`/admin/models/${modelId}`)
      message.success('模型已删除')
      loadModels()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '删除失败')
    }
  }

  const handleToggleModel = async (modelId: string, field: 'is_active' | 'visible_to_users', value: boolean) => {
    setModels(prev => prev.map(m => m.id === modelId ? { ...m, [field]: value } : m))
    try {
      await api.put(`/admin/models/${modelId}`, { [field]: value })
    } catch {
      loadModels()
    }
  }

  const handleTestModel = async () => {
    const values = modelForm.getFieldsValue()
    if (!values.model_name) {
      message.warning('请先填写模型名称')
      return
    }
    if (!globalApiBase) {
      message.warning('请先在上方保存全局 API 配置')
      return
    }
    setTesting(true)
    try {
      const res = await api.post('/admin/models/test', {
        id: values.id || 'test',
        display_name: values.display_name || 'test',
        model_name: values.model_name,
        api_base: globalApiBase,
        api_key: globalApiKey || 'use-saved',
        provider: 'openai',
      })
      if (res.data.status === 'ok') {
        message.success(res.data.message)
      } else {
        message.error(res.data.message)
      }
    } catch (err: any) {
      message.error('测试请求失败')
    } finally {
      setTesting(false)
    }
  }

  const handleGrantCredits = async (values: { user_id: string; amount: number; description: string }) => {
    try {
      await api.post('/admin/credits/grant', values)
      message.success('额度已调整')
      setCreditModalOpen(false)
      creditForm.resetFields()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '操作失败')
    }
  }

  const statCardStyle: React.CSSProperties = {
    borderRadius: 12,
    border: `1px solid ${colors.border}`,
  }

  const userColumns = [
    { title: '用户名', dataIndex: 'username', key: 'username' },
    { title: '邮箱', dataIndex: 'email', key: 'email' },
    { title: '角色', dataIndex: 'role', key: 'role', width: 80, render: (r: string) => <Tag color={r === 'admin' ? 'gold' : 'default'}>{r}</Tag> },
    {
      title: '状态', dataIndex: 'is_active', key: 'is_active', width: 80,
      render: (v: boolean) => <Tag color={v ? 'success' : 'error'}>{v ? '正常' : '已禁用'}</Tag>,
    },
    { title: '注册时间', dataIndex: 'created_at', key: 'created_at', width: 120, render: (t: string) => new Date(t).toLocaleDateString('zh-CN') },
    { title: '最后登录', dataIndex: 'last_login_at', key: 'last_login_at', width: 120, render: (t: string | null) => t ? new Date(t).toLocaleDateString('zh-CN') : '-' },
    {
      title: '操作', key: 'action', width: 200,
      render: (_: unknown, record: UserInfo) => (
        <Space size={4}>
          <Button size="small" icon={<EyeOutlined />} onClick={() => loadUserDetail(record.id)}>详情</Button>
          <Button size="small" danger={record.is_active} onClick={() => toggleUserStatus(record.id, record.is_active)}>
            {record.is_active ? '禁用' : '启用'}
          </Button>
          <Button
            size="small"
            onClick={() => {
              creditForm.setFieldsValue({ user_id: record.id, amount: 100, description: '管理员手动调整' })
              setCreditModalOpen(true)
            }}
          >
            调额度
          </Button>
        </Space>
      ),
    },
  ]

  const modelColumns = [
    { title: '显示名称', dataIndex: 'display_name', key: 'display_name', width: 150 },
    { title: '供应商', dataIndex: 'provider', key: 'provider', width: 90, render: (v: string) => <Tag>{v}</Tag> },
    { title: 'API 模型名', dataIndex: 'model_name', key: 'model_name', width: 160 },
    {
      title: '启用', dataIndex: 'is_active', key: 'is_active', width: 70,
      render: (v: boolean, record: any) => (
        <Switch size="small" checked={v} onChange={(checked) => handleToggleModel(record.id, 'is_active', checked)} />
      ),
    },
    {
      title: '用户可见', dataIndex: 'visible_to_users', key: 'visible_to_users', width: 80,
      render: (v: boolean, record: any) => (
        <Switch size="small" checked={v} onChange={(checked) => handleToggleModel(record.id, 'visible_to_users', checked)} />
      ),
    },
    {
      title: '操作', key: 'action', width: 120,
      render: (_: unknown, record: any) => (
        <Space size={4}>
          <Button type="text" size="small" icon={<EditOutlined />} onClick={() => handleEditModel(record)} />
          <Popconfirm title={`确定删除模型「${record.display_name}」？`} onConfirm={() => handleDeleteModel(record.id)} okText="删除" cancelText="取消" okButtonProps={{ danger: true }}>
            <Button type="text" size="small" danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ]

  const convColumns = [
    { title: '标题', dataIndex: 'title', key: 'title', ellipsis: true, render: (t: string) => t || '新对话' },
    { title: '用户', dataIndex: 'username', key: 'username', width: 100 },
    { title: '邮箱', dataIndex: 'email', key: 'email', width: 180, ellipsis: true },
    { title: '模型', dataIndex: 'model_id', key: 'model_id', width: 140, render: (v: string) => <Tag>{v}</Tag> },
    { title: '更新时间', dataIndex: 'updated_at', key: 'updated_at', width: 160, render: (t: string) => t ? new Date(t).toLocaleString('zh-CN') : '-' },
  ]

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <Title level={4} style={{ marginBottom: 4 }}>管理后台</Title>
        <Text type="secondary">平台管理与运营数据</Text>
      </div>

      <Card>
        <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
          {
            key: 'stats',
            label: <span><BarChartOutlined /> 运营概览</span>,
            children: (
              <div>
                <Text strong style={{ fontSize: 14, display: 'block', marginBottom: 16, color: colors.textSecondary }}>
                  核心指标
                </Text>
                <Row gutter={[16, 16]}>
                  <Col xs={12} sm={8} md={6}>
                    <Card size="small" style={statCardStyle}>
                      <Statistic title="注册用户" value={stats.total_users} prefix={<UserOutlined />} />
                    </Card>
                  </Col>
                  <Col xs={12} sm={8} md={6}>
                    <Card size="small" style={statCardStyle}>
                      <Statistic title="今日活跃" value={stats.active_users_today} prefix={<TeamOutlined />} valueStyle={{ color: colors.success }} />
                    </Card>
                  </Col>
                  <Col xs={12} sm={8} md={6}>
                    <Card size="small" style={statCardStyle}>
                      <Statistic title="本周新增" value={stats.new_users_week} prefix={<RiseOutlined />} valueStyle={{ color: colors.primary }} />
                    </Card>
                  </Col>
                  <Col xs={12} sm={8} md={6}>
                    <Card size="small" style={statCardStyle}>
                      <Statistic title="今日消息" value={stats.messages_today} prefix={<ThunderboltOutlined />} />
                    </Card>
                  </Col>
                </Row>

                <Divider />

                <Text strong style={{ fontSize: 14, display: 'block', marginBottom: 16, color: colors.textSecondary }}>
                  平台数据
                </Text>
                <Row gutter={[16, 16]}>
                  <Col xs={12} sm={8} md={6}>
                    <Card size="small" style={statCardStyle}>
                      <Statistic title="数据空间" value={stats.total_spaces} prefix={<DatabaseOutlined />} />
                    </Card>
                  </Col>
                  <Col xs={12} sm={8} md={6}>
                    <Card size="small" style={statCardStyle}>
                      <Statistic title="文件总数" value={stats.total_files} prefix={<FileOutlined />} />
                    </Card>
                  </Col>
                  <Col xs={12} sm={8} md={6}>
                    <Card size="small" style={statCardStyle}>
                      <Statistic title="对话总数" value={stats.total_conversations} prefix={<MessageOutlined />} />
                    </Card>
                  </Col>
                  <Col xs={12} sm={8} md={6}>
                    <Card size="small" style={statCardStyle}>
                      <Statistic title="消息总数" value={stats.total_messages} prefix={<MessageOutlined />} />
                    </Card>
                  </Col>
                  <Col xs={12} sm={8} md={6}>
                    <Card size="small" style={statCardStyle}>
                      <Statistic title="用户反馈" value={stats.total_feedback} />
                    </Card>
                  </Col>
                  <Col xs={12} sm={8} md={6}>
                    <Card size="small" style={statCardStyle}>
                      <Statistic title="总消耗额度" value={stats.total_credits_consumed} prefix={<WalletOutlined />} />
                    </Card>
                  </Col>
                </Row>
              </div>
            ),
          },
          {
            key: 'users',
            label: <span><UserOutlined /> 用户管理</span>,
            children: (
              <div>
                <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Text type="secondary">共 {users.length} 个用户</Text>
                  <Button onClick={() => setCreditModalOpen(true)} icon={<WalletOutlined />}>手动调整额度</Button>
                </div>
                <Table columns={userColumns} dataSource={users} rowKey="id" size="small" />
              </div>
            ),
          },
          {
            key: 'conversations',
            label: <span><MessageOutlined /> 对话管理</span>,
            children: (
              <Table
                columns={convColumns}
                dataSource={conversations}
                rowKey="id"
                size="small"
                pagination={{
                  current: convPage,
                  total: convTotal,
                  pageSize: 20,
                  onChange: setConvPage,
                  showTotal: (t) => `共 ${t} 条对话`,
                }}
              />
            ),
          },
          {
            key: 'config',
            label: <span><SettingOutlined /> 系统设置</span>,
            children: configLoading ? <Spin /> : (
              <div style={{ maxWidth: 600 }}>
                <Text type="secondary" style={{ display: 'block', marginBottom: 20 }}>
                  修改即时生效，无需重启服务
                </Text>
                {Object.entries(runtimeConfig).map(([key, meta]: [string, any]) => (
                  <div key={key} style={{
                    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                    padding: '12px 0', borderBottom: `1px solid ${colors.border}`,
                  }}>
                    <div>
                      <Text strong style={{ fontSize: 13 }}>{meta.label}</Text>
                      <br />
                      <Text type="secondary" style={{ fontSize: 11 }}>{key}</Text>
                    </div>
                    {meta.type === 'bool' ? (
                      <Switch
                        checked={meta.value}
                        onChange={(checked) => updateConfig(key, String(checked))}
                        checkedChildren="开" unCheckedChildren="关"
                      />
                    ) : (
                      <InputNumber
                        value={meta.value}
                        min={meta.min} max={meta.max}
                        style={{ width: 120 }}
                        onBlur={(e) => {
                          const val = e.target.value
                          if (val && String(val) !== String(meta.value)) {
                            updateConfig(key, String(val))
                          }
                        }}
                        onPressEnter={(e) => {
                          const val = (e.target as HTMLInputElement).value
                          if (val) updateConfig(key, val)
                        }}
                      />
                    )}
                  </div>
                ))}
              </div>
            ),
          },
          {
            key: 'security',
            label: <span><SettingOutlined /> 安全管理</span>,
            children: (
              <div style={{ maxWidth: 600 }}>
                <Text type="secondary" style={{ display: 'block', marginBottom: 20 }}>
                  封禁恶意 IP、解锁被锁定的账号
                </Text>

                <Card title="封禁 IP" size="small" style={{ marginBottom: 16, borderRadius: 12 }}>
                  <Space.Compact style={{ width: '100%', marginBottom: 8 }}>
                    <Input
                      placeholder="IP 地址，如 1.2.3.4"
                      value={blockIp}
                      onChange={(e) => setBlockIp(e.target.value)}
                      style={{ flex: 1 }}
                    />
                    <InputNumber
                      value={blockHours}
                      onChange={(v) => setBlockHours(v || 24)}
                      min={1} max={8760}
                      addonAfter="小时"
                      style={{ width: 140 }}
                    />
                    <Button
                      type="primary" danger
                      onClick={async () => {
                        if (!blockIp.trim()) return
                        try {
                          await api.post('/admin/security/block-ip', { ip: blockIp.trim(), hours: blockHours })
                          message.success(`已封禁 ${blockIp}`)
                          setBlockIp('')
                        } catch (err: any) { message.error(err.response?.data?.detail || '操作失败') }
                      }}
                    >
                      封禁
                    </Button>
                  </Space.Compact>
                  <Space.Compact style={{ width: '100%' }}>
                    <Input
                      placeholder="输入 IP 解封"
                      onPressEnter={async (e) => {
                        const ip = (e.target as HTMLInputElement).value.trim()
                        if (!ip) return
                        try {
                          await api.post('/admin/security/unblock-ip', { ip })
                          message.success(`已解封 ${ip}`)
                        } catch { message.error('操作失败') }
                      }}
                      style={{ flex: 1 }}
                    />
                    <Button onClick={async () => { message.info('在输入框输入 IP 后按回车解封') }}>解封</Button>
                  </Space.Compact>
                </Card>

                <Card title="解锁账号" size="small" style={{ borderRadius: 12 }}>
                  <Text type="secondary" style={{ display: 'block', marginBottom: 8, fontSize: 12 }}>
                    用户连续 5 次登录失败会被锁定 15 分钟，可在此手动解锁
                  </Text>
                  <Space.Compact style={{ width: '100%' }}>
                    <Input
                      placeholder="用户邮箱"
                      value={unlockEmail}
                      onChange={(e) => setUnlockEmail(e.target.value)}
                      style={{ flex: 1 }}
                    />
                    <Button
                      type="primary"
                      onClick={async () => {
                        if (!unlockEmail.trim()) return
                        try {
                          await api.post('/admin/security/unlock-account', { email: unlockEmail.trim() })
                          message.success(`已解锁 ${unlockEmail}`)
                          setUnlockEmail('')
                        } catch (err: any) { message.error(err.response?.data?.detail || '操作失败') }
                      }}
                    >
                      解锁
                    </Button>
                  </Space.Compact>
                </Card>
              </div>
            ),
          },
          {
            key: 'research',
            label: <span><ExperimentOutlined /> 研究数据</span>,
            children: (
              <div style={{ maxWidth: 700 }}>
                <Text type="secondary" style={{ display: 'block', marginBottom: 20 }}>
                  导出用户对话数据用于学术研究。默认只导出用户勾选了「研究授权」的数据。
                </Text>

                {researchStats && (
                  <Row gutter={16} style={{ marginBottom: 24 }}>
                    <Col span={6}>
                      <Card size="small" style={{ borderRadius: 12, border: `1px solid ${colors.border}` }}>
                        <Statistic title="已授权用户" value={researchStats.consented_users} suffix={`/ ${researchStats.total_users}`} valueStyle={{ fontSize: 20 }} />
                      </Card>
                    </Col>
                    <Col span={6}>
                      <Card size="small" style={{ borderRadius: 12, border: `1px solid ${colors.border}` }}>
                        <Statistic title="授权率" value={researchStats.consent_rate} suffix="%" valueStyle={{ fontSize: 20 }} />
                      </Card>
                    </Col>
                    <Col span={6}>
                      <Card size="small" style={{ borderRadius: 12, border: `1px solid ${colors.border}` }}>
                        <Statistic title="可导出对话" value={researchStats.consented_conversations} valueStyle={{ fontSize: 20 }} />
                      </Card>
                    </Col>
                    <Col span={6}>
                      <Card size="small" style={{ borderRadius: 12, border: `1px solid ${colors.border}` }}>
                        <Statistic title="可导出消息" value={researchStats.consented_messages} valueStyle={{ fontSize: 20 }} />
                      </Card>
                    </Col>
                  </Row>
                )}

                <Card style={{ borderRadius: 12 }}>
                  <div style={{ marginBottom: 20 }}>
                    <Text strong style={{ display: 'block', marginBottom: 8, fontSize: 13 }}>导出格式</Text>
                    <Radio.Group value={exportFormat} onChange={(e) => setExportFormat(e.target.value)}>
                      <Radio.Button value="json">JSONL（完整对话，含工具调用）</Radio.Button>
                      <Radio.Button value="csv">CSV（平铺消息，适合 Excel）</Radio.Button>
                    </Radio.Group>
                  </div>

                  <div style={{ marginBottom: 20 }}>
                    <Text strong style={{ display: 'block', marginBottom: 8, fontSize: 13 }}>数据范围</Text>
                    <Switch
                      checked={exportConsentOnly}
                      onChange={setExportConsentOnly}
                      checkedChildren="仅授权用户"
                      unCheckedChildren="全部用户"
                    />
                    <Text type="secondary" style={{ marginLeft: 12, fontSize: 12 }}>
                      {exportConsentOnly ? '只导出勾选了「参与研究授权」的用户数据' : '导出全部用户数据（请确保合规）'}
                    </Text>
                  </div>

                  <Button
                    type="primary"
                    icon={<DownloadOutlined />}
                    loading={exporting}
                    onClick={handleExportResearch}
                    size="large"
                    style={{ borderRadius: 10 }}
                  >
                    {exporting ? '正在导出...' : '导出研究数据'}
                  </Button>

                  <div style={{ marginTop: 16, padding: 12, background: colors.bgSubtle, borderRadius: 8, fontSize: 12, color: colors.textMuted, lineHeight: 1.8 }}>
                    <strong>导出说明：</strong><br />
                    · 用户 ID 和对话 ID 会自动匿名化（UUID hash）<br />
                    · JSONL 格式每行一个完整对话，包含所有轮次、工具调用记录、token 消耗<br />
                    · CSV 格式每行一条消息，适合直接用 Excel/Pandas 分析<br />
                    · 用户在注册时勾选「参与研究授权」的数据才会被导出
                  </div>
                </Card>
              </div>
            ),
          },
          {
            key: 'models',
            label: <span><ApiOutlined /> 模型配置</span>,
            children: (
              <>
                <Card size="small" style={{ marginBottom: 16, borderRadius: 10 }} title="全局 API 配置（所有模型共用）">
                  <div style={{ display: 'flex', gap: 12, alignItems: 'flex-end' }}>
                    <div style={{ flex: 1 }}>
                      <Text style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>API 中转站地址</Text>
                      <Input
                        value={globalApiBase}
                        onChange={(e) => setGlobalApiBase(e.target.value)}
                        placeholder="https://api.example.com/v1"
                        size="small"
                      />
                    </div>
                    <div style={{ flex: 1 }}>
                      <Text style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
                        API Key {globalApiKeySet && <Tag color="success" style={{ fontSize: 10, lineHeight: '16px', padding: '0 4px', marginLeft: 4 }}>已配置</Tag>}
                      </Text>
                      <Input.Password
                        value={globalApiKey}
                        onChange={(e) => setGlobalApiKey(e.target.value)}
                        placeholder={globalApiKeySet ? '留空则不修改' : 'sk-...'}
                        size="small"
                      />
                    </div>
                    <Button type="primary" size="small" onClick={handleSaveGlobalApi}>保存</Button>
                  </div>
                </Card>

                <div style={{ marginBottom: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <Text type="secondary" style={{ fontSize: 12 }}>下方模型添加时自动使用全局 API 配置</Text>
                  <Button type="primary" onClick={() => { setEditingModel(null); modelForm.resetFields(); setModelModalOpen(true) }}>
                    添加模型
                  </Button>
                </div>
                <Table columns={modelColumns} dataSource={models} rowKey="id" size="small" />
              </>
            ),
          },
        ]} />
      </Card>

      <Modal
        title={editingModel ? `编辑模型 — ${editingModel.display_name}` : '添加模型配置'}
        open={modelModalOpen}
        onCancel={() => { setModelModalOpen(false); setEditingModel(null); modelForm.resetFields() }}
        footer={[
          <Button key="test" icon={<ExperimentOutlined />} loading={testing} onClick={handleTestModel}>
            测试连通性
          </Button>,
          <Button key="cancel" onClick={() => { setModelModalOpen(false); setEditingModel(null); modelForm.resetFields() }}>
            取消
          </Button>,
          <Button key="ok" type="primary" onClick={() => modelForm.submit()}>
            {editingModel ? '保存' : '添加'}
          </Button>,
        ]}
      >
        <Form form={modelForm} layout="vertical" onFinish={handleAddModel}>
          {!editingModel && (
            <Form.Item name="id" label="模型 ID（唯一标识，添加后不可修改）" rules={[{ required: true }]}>
              <Input placeholder="例如: gpt-4o、claude-sonnet" />
            </Form.Item>
          )}
          <Form.Item name="display_name" label="前端显示名称" rules={[{ required: !editingModel }]} extra="用户在对话页面看到的模型名">
            <Input placeholder="例如: GPT-4o、Claude Sonnet" />
          </Form.Item>
          <Form.Item name="model_name" label="API 实际模型名" rules={[{ required: !editingModel }]} extra="调用 API 时传的 model 参数值">
            <Input placeholder="例如: gpt-4o、deepseek-chat" />
          </Form.Item>
          <Row gutter={16}>
            <Col span={24}>
              <Form.Item name="max_tokens" label="最大 Token" initialValue={4096}>
                <InputNumber min={256} max={128000} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
          </Row>
        </Form>
      </Modal>

      <Modal title="调整用户额度" open={creditModalOpen} onCancel={() => setCreditModalOpen(false)} onOk={() => creditForm.submit()} okText="确认" cancelText="取消">
        <Form form={creditForm} layout="vertical" onFinish={handleGrantCredits}>
          <Form.Item name="user_id" label="用户 ID" rules={[{ required: true, message: '请输入用户 ID' }]}>
            <Input placeholder="用户 UUID" />
          </Form.Item>
          <Form.Item name="amount" label="调整数量" rules={[{ required: true }]} extra="正数为增加，负数为扣除">
            <InputNumber style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="description" label="说明" initialValue="管理员手动调整">
            <Input />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title="用户详情"
        open={userDetailModalOpen}
        onCancel={() => { setUserDetailModalOpen(false); setUserDetail(null) }}
        footer={<Button onClick={() => { setUserDetailModalOpen(false); setUserDetail(null) }}>关闭</Button>}
        width={560}
      >
        {userDetailLoading ? <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div> : userDetail && (
          <div>
            <Descriptions column={2} size="small" bordered style={{ marginBottom: 16 }}>
              <Descriptions.Item label="用户名">{userDetail.user.username}</Descriptions.Item>
              <Descriptions.Item label="邮箱">{userDetail.user.email}</Descriptions.Item>
              <Descriptions.Item label="角色"><Tag color={userDetail.user.role === 'admin' ? 'gold' : 'default'}>{userDetail.user.role}</Tag></Descriptions.Item>
              <Descriptions.Item label="状态"><Tag color={userDetail.user.is_active ? 'success' : 'error'}>{userDetail.user.is_active ? '正常' : '禁用'}</Tag></Descriptions.Item>
              <Descriptions.Item label="注册时间">{userDetail.user.created_at ? new Date(userDetail.user.created_at).toLocaleString('zh-CN') : '-'}</Descriptions.Item>
              <Descriptions.Item label="最后登录">{userDetail.user.last_login_at ? new Date(userDetail.user.last_login_at).toLocaleString('zh-CN') : '-'}</Descriptions.Item>
            </Descriptions>

            <Row gutter={16} style={{ marginBottom: 16 }}>
              <Col span={6}><Card size="small"><Statistic title="数据空间" value={userDetail.spaces?.length || 0} valueStyle={{ fontSize: 20 }} /></Card></Col>
              <Col span={6}><Card size="small"><Statistic title="文件" value={userDetail.file_count} valueStyle={{ fontSize: 20 }} /></Card></Col>
              <Col span={6}><Card size="small"><Statistic title="对话" value={userDetail.conversation_count} valueStyle={{ fontSize: 20 }} /></Card></Col>
              <Col span={6}><Card size="small"><Statistic title="余额" value={userDetail.credit_balance} valueStyle={{ fontSize: 20 }} /></Card></Col>
            </Row>

            {userDetail.spaces?.length > 0 && (
              <>
                <Text strong style={{ fontSize: 13, display: 'block', marginBottom: 8 }}>数据空间</Text>
                {userDetail.spaces.map((s: any) => (
                  <div key={s.id} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0', borderBottom: `1px solid ${colors.border}` }}>
                    <DatabaseOutlined style={{ color: colors.primary, fontSize: 12 }} />
                    <Text style={{ flex: 1, fontSize: 13 }}>{s.name}</Text>
                    <Text type="secondary" style={{ fontSize: 11 }}>{s.updated_at ? new Date(s.updated_at).toLocaleDateString('zh-CN') : ''}</Text>
                  </div>
                ))}
              </>
            )}
          </div>
        )}
      </Modal>
    </div>
  )
}
