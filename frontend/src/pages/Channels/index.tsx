/**
 * 渠道配置页
 * 菜单入口由主控在 NavRail + MainLayout 挂载
 */
import { useCallback, useEffect, useState } from 'react'
import { Collapse, Switch, Tag, Tooltip, Typography, Spin, message } from 'antd'
import { useIsMobile } from '@/hooks/useIsMobile'
import { channelsApi, type ChannelStatus } from '@/api/channels'
import { colors } from '@/styles/tokens'
import LarkForm from './LarkForm'
import WeixinForm from './WeixinForm'

const { Title, Text } = Typography

// ── emoji logos (no static asset needed) ─────────────────────────────────
const CHANNEL_META: Record<string, { label: string; emoji: string; desc: string }> = {
  lark: { label: '飞书', emoji: '🪶', desc: '自建应用 BYO — WSS 出站，免公网回调' },
  weixin: { label: '微信', emoji: '💬', desc: '官方 iLink 协议，扫码登录个人微信' },
}

// ── channel header (logo + name + switch) ────────────────────────────────
interface HeaderProps {
  channelId: string
  status: ChannelStatus | null
  enableLoading: boolean
  onToggle: (enabled: boolean) => void
}

function ChannelHeader({ channelId, status, enableLoading, onToggle }: HeaderProps) {
  const meta = CHANNEL_META[channelId]
  const enabled = status?.enabled ?? false
  const connected = status?.connected ?? false

  return (
    <div
      style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}
      data-channel-id={channelId}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0 }}>
        <span style={{ fontSize: 14 }}>{meta?.emoji}</span>
        <Text strong style={{ fontSize: 14 }}>{meta?.label ?? channelId}</Text>
        {connected && <Tag color="green" style={{ fontSize: 11 }}>已连接</Tag>}
        {enabled && !connected && <Tag color="orange" style={{ fontSize: 11 }}>启用中</Tag>}
      </div>
      <div onClick={(e) => e.stopPropagation()} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        {enableLoading && <Spin size="small" />}
        <Tooltip
          title={
            status?.has_credentials
              ? (enabled ? '点击停用该渠道' : '点击启用该渠道')
              : '尚未配置，点击填写凭据'
          }
        >
          <Switch
            size="small"
            checked={enabled}
            loading={enableLoading}
            onChange={onToggle}
            disabled={enableLoading}
          />
        </Tooltip>
      </div>
    </div>
  )
}

// ── main page ─────────────────────────────────────────────────────────────
export default function ChannelsPage() {
  const isMobile = useIsMobile()
  const [statuses, setStatuses] = useState<Record<string, ChannelStatus>>({})
  const [loading, setLoading] = useState(true)
  const [toggleLoading, setToggleLoading] = useState<Record<string, boolean>>({})
  const [activeKeys, setActiveKeys] = useState<string[]>([])

  const loadStatuses = useCallback(async () => {
    try {
      const res = await channelsApi.list()
      const map: Record<string, ChannelStatus> = {}
      res.data.forEach((s) => { map[s.id] = s })
      setStatuses(map)
    } catch {
      message.error('加载渠道状态失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void loadStatuses() }, [loadStatuses])

  const handleStatusChange = useCallback((s: ChannelStatus) => {
    setStatuses((prev) => ({ ...prev, [s.id]: s }))
  }, [])

  const handleToggle = useCallback(async (channelId: string, enabled: boolean) => {
    // 未配置凭据却想开启：展开卡片引导填写，而不是直接启用（启用需要凭据）
    if (enabled && !statuses[channelId]?.has_credentials) {
      setActiveKeys((prev) => (prev.includes(channelId) ? prev : [...prev, channelId]))
      message.info('请先填写凭据并测试连接')
      return
    }
    setToggleLoading((prev) => ({ ...prev, [channelId]: true }))
    try {
      if (enabled) {
        await channelsApi.enable(channelId as any) // 复用已存凭据重新启用
      } else {
        await channelsApi.disable(channelId as any)
      }
      await loadStatuses()
    } catch (err: any) {
      const detail = err.response?.data?.detail ?? (enabled ? '启用失败' : '停用失败')
      message.error(detail)
    } finally {
      setToggleLoading((prev) => ({ ...prev, [channelId]: false }))
    }
  }, [loadStatuses, statuses])

  const channels: Array<{ id: string; form: React.ReactNode }> = [
    {
      id: 'lark',
      form: (
        <LarkForm
          status={statuses['lark'] ?? null}
          onStatusChange={handleStatusChange}
        />
      ),
    },
    {
      id: 'weixin',
      form: (
        <WeixinForm
          status={statuses['weixin'] ?? null}
          onStatusChange={handleStatusChange}
        />
      ),
    },
  ]

  const collapseItems = channels.map(({ id, form }) => ({
    key: id,
    label: (
      <ChannelHeader
        channelId={id}
        status={statuses[id] ?? null}
        enableLoading={toggleLoading[id] ?? false}
        onToggle={(enabled) => handleToggle(id, enabled)}
      />
    ),
    children: form,
    styles: { body: { padding: '12px 16px 16px' } },
  }))

  return (
    <div
      style={{
        height: '100%',
        overflow: 'auto',
        background: '#f8fafc',
        padding: isMobile ? 16 : 32,
      }}
    >
      <div style={{ maxWidth: 720, margin: '0 auto' }}>
        <Title level={3} style={{ marginBottom: 4 }}>渠道配置</Title>
        <Text type="secondary" style={{ display: 'block', marginBottom: 24 }}>
          接入飞书、微信，让用户直接在 IM 里和 DataMind 对话。
          采用出站长连接（BYO 凭据），无需公网回调地址。
        </Text>

        {loading ? (
          <div style={{ textAlign: 'center', padding: 48 }}>
            <Spin tip="加载渠道状态..." />
          </div>
        ) : (
          <Collapse
            accordion={false}
            bordered={false}
            activeKey={activeKeys}
            onChange={(keys) => setActiveKeys(keys as string[])}
            style={{ background: 'transparent', display: 'flex', flexDirection: 'column', gap: 8 }}
            expandIconPosition="end"
            items={collapseItems.map((item) => ({
              ...item,
              style: {
                background: colors.surface,
                border: `1px solid ${colors.border}`,
                borderRadius: 10,
                overflow: 'hidden',
              },
            }))}
          />
        )}
      </div>
    </div>
  )
}
