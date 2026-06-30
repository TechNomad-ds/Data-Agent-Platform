/**
 * 待配对请求 + 已授权用户 面板（per-channel，嵌在各渠道表单底部）
 */
import { useCallback, useEffect, useState } from 'react'
import {
  Button, Input, List, Space, Tag, Spin, Empty, Popconfirm, Typography, Divider,
} from 'antd'
import { ReloadOutlined, CheckOutlined, CloseOutlined, DeleteOutlined, LinkOutlined } from '@ant-design/icons'
import { channelsApi, type ChannelId, type PairingRequest, type AuthorizedUser } from '@/api/channels'
import { message } from 'antd'

const { Text } = Typography

function remainingMinutes(expiresAt: string): number {
  return Math.max(0, Math.ceil((new Date(expiresAt).getTime() - Date.now()) / 60_000))
}

interface Props {
  channelId: ChannelId
}

export default function PairingsPanel({ channelId }: Props) {
  const [pairings, setPairings] = useState<PairingRequest[]>([])
  const [users, setUsers] = useState<AuthorizedUser[]>([])
  const [loadingPairings, setLoadingPairings] = useState(false)
  const [loadingUsers, setLoadingUsers] = useState(false)
  const [approvingCode, setApprovingCode] = useState<string | null>(null)
  const [rejectingCode, setRejectingCode] = useState<string | null>(null)
  const [revokingId, setRevokingId] = useState<string | null>(null)
  const [manualCode, setManualCode] = useState('')
  const [manualBinding, setManualBinding] = useState(false)

  const loadPairings = useCallback(async () => {
    setLoadingPairings(true)
    try {
      const res = await channelsApi.getPairings()
      setPairings(res.data.filter((p) => p.platform === channelId))
    } catch {
      // silent — user can retry
    } finally {
      setLoadingPairings(false)
    }
  }, [channelId])

  const loadUsers = useCallback(async () => {
    setLoadingUsers(true)
    try {
      const res = await channelsApi.getAuthorizedUsers()
      setUsers(res.data.filter((u) => u.platform === channelId))
    } catch {
      // silent
    } finally {
      setLoadingUsers(false)
    }
  }, [channelId])

  useEffect(() => {
    void loadPairings()
    void loadUsers()
  }, [loadPairings, loadUsers])

  // 手动输入配对码绑定（对应 IM 内「请在网页端输入配对码 XXXX 绑定」的提示）。
  // 走 approve-by-code，凭 Redis 共享码本，跨进程（web / manager 分离部署）有效。
  const handleManualBind = async () => {
    const code = manualCode.trim()
    if (!code) return
    setManualBinding(true)
    try {
      await channelsApi.approvePairing(code)
      message.success('绑定成功')
      setManualCode('')
      await Promise.all([loadPairings(), loadUsers()])
    } catch (err: any) {
      message.error(err.response?.data?.detail ?? '绑定失败：配对码无效或已过期')
    } finally {
      setManualBinding(false)
    }
  }

  const handleApprove = async (code: string) => {
    setApprovingCode(code)
    try {
      await channelsApi.approvePairing(code)
      message.success('配对已批准')
      await Promise.all([loadPairings(), loadUsers()])
    } catch (err: any) {
      message.error(err.response?.data?.detail ?? '批准失败')
    } finally {
      setApprovingCode(null)
    }
  }

  const handleReject = async (code: string) => {
    setRejectingCode(code)
    try {
      await channelsApi.rejectPairing(code)
      message.info('配对已拒绝')
      await loadPairings()
    } catch (err: any) {
      message.error(err.response?.data?.detail ?? '拒绝失败')
    } finally {
      setRejectingCode(null)
    }
  }

  const handleRevoke = async (userId: string) => {
    setRevokingId(userId)
    try {
      await channelsApi.revokeUser(userId)
      message.success('已撤销授权')
      await loadUsers()
    } catch (err: any) {
      message.error(err.response?.data?.detail ?? '撤销失败')
    } finally {
      setRevokingId(null)
    }
  }

  return (
    <div style={{ marginTop: 24 }}>
      {/* ── 输入配对码绑定（对应 IM 内提示「请在网页端输入配对码」）── */}
      <Text strong style={{ fontSize: 13, display: 'block', marginBottom: 8 }}>输入配对码绑定</Text>
      <Space.Compact style={{ width: '100%', marginBottom: 8 }}>
        <Input
          size="small"
          placeholder="在 IM 收到的配对码，如 123456"
          value={manualCode}
          onChange={(e) => setManualCode(e.target.value)}
          onPressEnter={handleManualBind}
          allowClear
        />
        <Button
          size="small"
          type="primary"
          icon={<LinkOutlined />}
          loading={manualBinding}
          disabled={!manualCode.trim()}
          onClick={handleManualBind}
        >
          绑定
        </Button>
      </Space.Compact>
      <Text type="secondary" style={{ fontSize: 11, display: 'block', marginBottom: 16 }}>
        在 IM 里给 bot 发消息会收到配对码，在此输入即可把该 IM 账号绑定到当前账号。
      </Text>

      {/* ── Pending pairings ── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <Text strong style={{ fontSize: 13 }}>待配对请求</Text>
        <Button
          size="small"
          icon={<ReloadOutlined />}
          onClick={loadPairings}
          loading={loadingPairings}
        >
          刷新
        </Button>
      </div>

      {loadingPairings ? (
        <div style={{ textAlign: 'center', padding: 16 }}><Spin size="small" /></div>
      ) : pairings.length === 0 ? (
        <Empty description="暂无待配对请求" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ margin: '8px 0' }} />
      ) : (
        <List
          size="small"
          bordered
          dataSource={pairings}
          style={{ marginBottom: 16 }}
          renderItem={(req) => (
            <List.Item
              actions={[
                <Button
                  key="approve"
                  type="primary"
                  size="small"
                  icon={<CheckOutlined />}
                  loading={approvingCode === req.code}
                  onClick={() => handleApprove(req.code)}
                >
                  批准
                </Button>,
                <Button
                  key="reject"
                  danger
                  size="small"
                  icon={<CloseOutlined />}
                  loading={rejectingCode === req.code}
                  onClick={() => handleReject(req.code)}
                >
                  拒绝
                </Button>,
              ]}
            >
              <Space size={8} wrap>
                <Text strong>{req.platform_username || req.platform_user_id}</Text>
                <Tag color="blue">码: {req.code}</Tag>
                <Tag color={remainingMinutes(req.expires_at) > 2 ? 'green' : 'red'}>
                  剩余 {remainingMinutes(req.expires_at)} 分钟
                </Tag>
              </Space>
            </List.Item>
          )}
        />
      )}

      <Divider style={{ margin: '12px 0' }} />

      {/* ── Authorized users ── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <Text strong style={{ fontSize: 13 }}>
          已授权用户
          {users.length > 0 && (
            <Text type="secondary" style={{ fontSize: 11, fontWeight: 400, marginLeft: 6 }}>
              （有授权用户时凭据字段已锁定）
            </Text>
          )}
        </Text>
        <Button
          size="small"
          icon={<ReloadOutlined />}
          onClick={loadUsers}
          loading={loadingUsers}
        >
          刷新
        </Button>
      </div>

      {loadingUsers ? (
        <div style={{ textAlign: 'center', padding: 16 }}><Spin size="small" /></div>
      ) : users.length === 0 ? (
        <Empty description="暂无已授权用户" image={Empty.PRESENTED_IMAGE_SIMPLE} style={{ margin: '8px 0' }} />
      ) : (
        <List
          size="small"
          bordered
          dataSource={users}
          renderItem={(u) => (
            <List.Item
              actions={[
                <Popconfirm
                  key="revoke"
                  title="确认撤销该用户的渠道访问权限？"
                  okText="撤销"
                  cancelText="取消"
                  okButtonProps={{ danger: true }}
                  onConfirm={() => handleRevoke(u.id)}
                >
                  <Button
                    danger
                    size="small"
                    icon={<DeleteOutlined />}
                    loading={revokingId === u.id}
                  >
                    撤销
                  </Button>
                </Popconfirm>,
              ]}
            >
              <Space size={8} wrap>
                <Text strong>{u.platform_username || u.platform_user_id}</Text>
                <Tag color="green">已授权</Tag>
                <Text type="secondary" style={{ fontSize: 11 }}>
                  {new Date(u.authorized_at).toLocaleDateString('zh-CN')}
                </Text>
              </Space>
            </List.Item>
          )}
        />
      )}
    </div>
  )
}
