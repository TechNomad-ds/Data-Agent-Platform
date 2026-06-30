/**
 * 微信渠道配置表单
 * 登录：SSE 扫码状态机 idle → loading_qr → showing_qr → scanned → connected
 * 后端（ilink）通过 SSE 下发的是扫码 URL 字符串（qrcodeData），前端用 qrcode.react 编码成二维码。
 * 若未来后端改为下发 base64 PNG（data: 开头），则直接用 <img> 渲染。
 */
import { useEffect, useRef, useState } from 'react'
import {
  Button, Divider, Spin, Typography, message,
} from 'antd'
import {
  CheckCircleOutlined, DisconnectOutlined, QrcodeOutlined, ReloadOutlined,
} from '@ant-design/icons'
import { QRCodeSVG } from 'qrcode.react'
import { channelsApi, startWeixinLoginSSE, type ChannelStatus } from '@/api/channels'
import ChannelSettingsRow from './ChannelSettingsRow'
import PairingsPanel from './PairingsPanel'

const { Text } = Typography

type LoginState = 'idle' | 'loading_qr' | 'showing_qr' | 'scanned' | 'connected'

interface Props {
  status: ChannelStatus | null
  onStatusChange: (s: ChannelStatus) => void
}

export default function WeixinForm({ status, onStatusChange }: Props) {
  const [loginState, setLoginState] = useState<LoginState>(
    status?.connected && status?.enabled ? 'connected' : 'idle'
  )
  const [qrDataUrl, setQrDataUrl] = useState<string | null>(null)
  const [disableLoading, setDisableLoading] = useState(false)
  const abortRef = useRef<AbortController | null>(null)

  // sync when parent status changes
  useEffect(() => {
    if (status?.connected && status?.enabled && loginState === 'idle') {
      setLoginState('connected')
    }
  }, [status, loginState])

  // cancel SSE on unmount
  useEffect(() => {
    return () => {
      abortRef.current?.abort()
    }
  }, [])

  const handleLogin = () => {
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl

    setLoginState('loading_qr')
    setQrDataUrl(null)

    startWeixinLoginSSE((evt) => {
      switch (evt.type) {
        case 'qr':
          setQrDataUrl(evt.qr_data_url)
          setLoginState('showing_qr')
          break
        case 'scanned':
          setLoginState('scanned')
          break
        case 'done':
          // backend has saved credentials; reload status
          channelsApi.list().then((res) => {
            const next = res.data.find((s) => s.id === 'weixin')
            if (next) {
              onStatusChange(next)
              setLoginState('connected')
              message.success('微信登录成功，渠道已启用')
            }
          }).catch(() => {
            setLoginState('idle')
          })
          break
        case 'error':
          message.error(`微信登录失败：${evt.message}`)
          setLoginState('idle')
          setQrDataUrl(null)
          break
      }
    }, ctrl.signal).catch((err) => {
      if ((err as Error).name !== 'AbortError') {
        message.error('SSE 连接失败，请重试')
        setLoginState('idle')
        setQrDataUrl(null)
      }
    })
  }

  const handleDisconnect = async () => {
    abortRef.current?.abort()
    setDisableLoading(true)
    try {
      await channelsApi.disable('weixin')
      message.success('微信渠道已停用')
      const res = await channelsApi.list()
      const next = res.data.find((s) => s.id === 'weixin')
      if (next) onStatusChange(next)
      setLoginState('idle')
      setQrDataUrl(null)
    } catch (err: any) {
      message.error(err.response?.data?.detail ?? '停用失败')
    } finally {
      setDisableLoading(false)
    }
  }

  const renderLoginArea = () => {
    if (loginState === 'connected') {
      return (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <CheckCircleOutlined style={{ color: '#10a37f', fontSize: 16 }} />
          <Text style={{ color: '#10a37f' }}>已连接微信</Text>
          <Button
            size="small"
            danger
            icon={<DisconnectOutlined />}
            loading={disableLoading}
            onClick={handleDisconnect}
          >
            断开登录
          </Button>
        </div>
      )
    }

    if (loginState === 'showing_qr' || loginState === 'scanned') {
      return (
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 8 }}>
          {qrDataUrl ? (
            qrDataUrl.startsWith('data:') ? (
              <img
                src={qrDataUrl}
                alt="微信登录二维码"
                style={{ width: 160, height: 160, border: '1px solid #ececf1', borderRadius: 8 }}
              />
            ) : (
              <div style={{ padding: 8, border: '1px solid #ececf1', borderRadius: 8, background: '#fff' }}>
                <QRCodeSVG value={qrDataUrl} size={144} level="M" />
              </div>
            )
          ) : (
            <div style={{ width: 160, height: 160, display: 'flex', alignItems: 'center', justifyContent: 'center', border: '1px solid #ececf1', borderRadius: 8 }}>
              <Spin size="small" />
            </div>
          )}
          {loginState === 'scanned' ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <Spin size="small" />
              <Text type="secondary" style={{ fontSize: 13 }}>已扫码，等待确认...</Text>
            </div>
          ) : (
            <Text type="secondary" style={{ fontSize: 13 }}>
              用微信扫描二维码登录
            </Text>
          )}
          <Button
            size="small"
            icon={<ReloadOutlined />}
            onClick={handleLogin}
          >
            刷新二维码
          </Button>
        </div>
      )
    }

    if (loginState === 'loading_qr') {
      return (
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Spin size="small" />
          <Text type="secondary" style={{ fontSize: 13 }}>正在获取二维码...</Text>
        </div>
      )
    }

    // idle
    return (
      <Button
        icon={<QrcodeOutlined />}
        onClick={handleLogin}
      >
        扫码登录微信
      </Button>
    )
  }

  return (
    <div style={{ padding: '4px 0' }}>
      <div style={{ marginBottom: 4 }}>
        <Text type="secondary" style={{ fontSize: 12 }}>
          使用官方 iLink 协议，通过个人微信二维码登录。无需企业主体，凭据由平台安全持久化。
        </Text>
      </div>

      <div style={{ margin: '12px 0' }}>
        {renderLoginArea()}
      </div>

      <Divider style={{ margin: '16px 0 8px' }} />

      <Text strong style={{ fontSize: 12, display: 'block', marginBottom: 8 }}>渠道设置</Text>
      <ChannelSettingsRow channelId="weixin" />

      <PairingsPanel channelId="weixin" />
    </div>
  )
}
