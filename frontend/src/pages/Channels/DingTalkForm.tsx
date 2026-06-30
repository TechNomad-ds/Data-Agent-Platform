/**
 * 钉钉渠道配置表单
 * 凭据：Client ID + Client Secret
 */
import { useState } from 'react'
import {
  Button, Divider, Form, Input, Spin, Typography, message,
} from 'antd'
import {
  ApiOutlined, CheckCircleOutlined, DisconnectOutlined,
} from '@ant-design/icons'
import { channelsApi, type ChannelStatus } from '@/api/channels'
import ChannelSettingsRow from './ChannelSettingsRow'
import PairingsPanel from './PairingsPanel'

const { Text } = Typography

interface Props {
  status: ChannelStatus | null
  onStatusChange: (s: ChannelStatus) => void
}

interface DingCreds {
  client_id: string
  client_secret: string
}

export default function DingTalkForm({ status, onStatusChange }: Props) {
  const [form] = Form.useForm<DingCreds>()
  const [testLoading, setTestLoading] = useState(false)
  const [enableLoading, setEnableLoading] = useState(false)
  const [tested, setTested] = useState(false)

  const hasCredentials = status?.has_credentials ?? false
  const enabled = status?.enabled ?? false
  const connected = status?.connected ?? false
  const credLocked = hasCredentials && enabled

  const getCredentials = (): Record<string, string> => {
    const vals = form.getFieldsValue()
    return {
      client_id: vals.client_id ?? '',
      client_secret: vals.client_secret ?? '',
    }
  }

  const handleTest = async () => {
    try {
      await form.validateFields()
    } catch {
      return
    }
    setTestLoading(true)
    setTested(false)
    try {
      const res = await channelsApi.test('dingtalk', getCredentials())
      if (res.data.ok) {
        message.success('钉钉连接测试成功')
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
      await form.validateFields()
    } catch {
      return
    }
    setEnableLoading(true)
    try {
      await channelsApi.enable('dingtalk', getCredentials())
      message.success('钉钉渠道已启用')
      const res = await channelsApi.list()
      const next = res.data.find((s) => s.id === 'dingtalk')
      if (next) onStatusChange(next)
    } catch (err: any) {
      message.error(err.response?.data?.detail ?? '启用失败')
    } finally {
      setEnableLoading(false)
    }
  }

  const handleDisable = async () => {
    setEnableLoading(true)
    try {
      await channelsApi.disable('dingtalk')
      message.success('钉钉渠道已停用')
      const res = await channelsApi.list()
      const next = res.data.find((s) => s.id === 'dingtalk')
      if (next) onStatusChange(next)
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
        <Form.Item
          label="Client ID"
          name="client_id"
          rules={[{ required: true, message: '请输入 Client ID' }]}
        >
          <Input placeholder="ding_xxxxxxxxxxxxxxxx" />
        </Form.Item>
        <Form.Item
          label="Client Secret"
          name="client_secret"
          rules={[{ required: true, message: '请输入 Client Secret' }]}
        >
          <Input.Password placeholder="Client Secret" />
        </Form.Item>

        <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
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
      <ChannelSettingsRow channelId="dingtalk" />

      {/* ── 配对 & 用户 ── */}
      <PairingsPanel channelId="dingtalk" />
    </div>
  )
}
