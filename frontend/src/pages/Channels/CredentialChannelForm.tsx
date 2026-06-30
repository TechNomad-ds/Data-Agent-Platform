/**
 * 「凭据型」渠道（飞书等）的通用配置表单。
 * 各渠道只提供 channelId / 文案 / 字段定义，连接状态、测试/启用/停用逻辑、设置与配对面板在此统一。
 * 微信走扫码登录，不用此组件（见 WeixinForm）。
 */
import { useState } from 'react'
import {
  Button, Collapse, Divider, Form, Input, Spin, Typography, message,
} from 'antd'
import {
  ApiOutlined, CheckCircleOutlined, DisconnectOutlined,
} from '@ant-design/icons'
import { channelsApi, type ChannelStatus, type ChannelId } from '@/api/channels'
import ChannelSettingsRow from './ChannelSettingsRow'
import PairingsPanel from './PairingsPanel'

const { Text } = Typography

export interface CredField {
  name: string
  label: string
  placeholder?: string
  password?: boolean
}

interface Props {
  channelId: ChannelId
  channelLabel: string
  /** 必填凭据字段 */
  fields: CredField[]
  /** 折叠展示的可选字段（如飞书 Encrypt Key / Verification Token） */
  optionalFields?: CredField[]
  optionalLabel?: string
  status: ChannelStatus | null
  onStatusChange: (s: ChannelStatus) => void
}

export default function CredentialChannelForm({
  channelId,
  channelLabel,
  fields,
  optionalFields = [],
  optionalLabel = '显示可选配置',
  status,
  onStatusChange,
}: Props) {
  const [form] = Form.useForm()
  const [testLoading, setTestLoading] = useState(false)
  const [enableLoading, setEnableLoading] = useState(false)
  const [tested, setTested] = useState(false)

  const hasCredentials = status?.has_credentials ?? false
  const enabled = status?.enabled ?? false
  const connected = status?.connected ?? false
  const credLocked = hasCredentials && enabled

  const requiredNames = fields.map((f) => f.name)

  const getCredentials = (): Record<string, string> => {
    const vals = form.getFieldsValue()
    const creds: Record<string, string> = {}
    for (const f of fields) creds[f.name] = vals[f.name] ?? ''
    for (const f of optionalFields) {
      if (vals[f.name]) creds[f.name] = vals[f.name]
    }
    return creds
  }

  const refreshStatus = async () => {
    const res = await channelsApi.list()
    const next = res.data.find((s) => s.id === channelId)
    if (next) onStatusChange(next)
  }

  const handleTest = async () => {
    try {
      await form.validateFields(requiredNames)
    } catch {
      return
    }
    setTestLoading(true)
    setTested(false)
    try {
      const res = await channelsApi.test(channelId, getCredentials())
      if (res.data.ok) {
        message.success(`${channelLabel}连接测试成功`)
        setTested(true)
      } else {
        message.error(`测试失败：${res.data.detail ?? '未知错误'}`)
      }
    } catch (err: any) {
      message.error(err.response?.data?.detail ?? '测试请求失败')
    } finally {
      setTestLoading(false)
    }
  }

  const handleEnable = async () => {
    try {
      await form.validateFields(requiredNames)
    } catch {
      return
    }
    setEnableLoading(true)
    try {
      await channelsApi.enable(channelId, getCredentials())
      message.success(`${channelLabel}渠道已启用`)
      await refreshStatus()
    } catch (err: any) {
      message.error(err.response?.data?.detail ?? '启用失败')
    } finally {
      setEnableLoading(false)
    }
  }

  const handleDisable = async () => {
    setEnableLoading(true)
    try {
      await channelsApi.disable(channelId)
      message.success(`${channelLabel}渠道已停用`)
      await refreshStatus()
    } catch (err: any) {
      message.error(err.response?.data?.detail ?? '停用失败')
    } finally {
      setEnableLoading(false)
    }
  }

  return (
    <div style={{ padding: '4px 0' }}>
      {/* ── 连接状态 ── */}
      {connected ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          <CheckCircleOutlined style={{ color: '#10a37f' }} />
          <Text style={{ color: '#10a37f' }}>已连接</Text>
          <Button size="small" danger icon={<DisconnectOutlined />} loading={enableLoading} onClick={handleDisable}>
            断开
          </Button>
        </div>
      ) : hasCredentials ? (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
          <DisconnectOutlined style={{ color: '#94a3b8' }} />
          <Text type="secondary">未连接（凭据已保存）</Text>
          <Button size="small" type="primary" loading={enableLoading} onClick={handleEnable}>
            启用
          </Button>
        </div>
      ) : null}

      {/* ── 凭据表单 ── */}
      <Form form={form} layout="vertical" size="small" disabled={credLocked}>
        {fields.map((f) => (
          <Form.Item
            key={f.name}
            label={f.label}
            name={f.name}
            rules={[{ required: true, message: `请输入 ${f.label}` }]}
          >
            {f.password ? <Input.Password placeholder={f.placeholder} /> : <Input placeholder={f.placeholder} />}
          </Form.Item>
        ))}

        {optionalFields.length > 0 && (
          <Collapse
            size="small"
            ghost
            items={[{
              key: 'optional',
              label: <Text type="secondary" style={{ fontSize: 12 }}>{optionalLabel}</Text>,
              children: (
                <>
                  {optionalFields.map((f) => (
                    <Form.Item key={f.name} label={f.label} name={f.name}>
                      <Input placeholder={f.placeholder ?? '可选'} />
                    </Form.Item>
                  ))}
                </>
              ),
            }]}
          />
        )}

        <div style={{ display: 'flex', gap: 8, marginTop: 8 }}>
          <Button
            icon={<ApiOutlined />}
            loading={testLoading}
            onClick={handleTest}
            disabled={credLocked}
          >
            测试连接
          </Button>
          {tested && !enabled && (
            <Button type="primary" loading={enableLoading} onClick={handleEnable}>
              启用渠道
            </Button>
          )}
          {enableLoading && <Spin size="small" />}
        </div>
      </Form>

      <Divider style={{ margin: '16px 0 8px' }} />

      {/* ── 渠道通用设置 ── */}
      <Text strong style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>渠道设置</Text>
      <ChannelSettingsRow channelId={channelId} />

      {/* ── 配对 & 用户 ── */}
      <PairingsPanel channelId={channelId} />
    </div>
  )
}
