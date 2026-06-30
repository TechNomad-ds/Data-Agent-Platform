import api from './client'
import { getValidToken } from './client'

// ── types ──────────────────────────────────────────────────────────────────

export type ChannelId = 'lark' | 'weixin'

export interface ChannelStatus {
  id: ChannelId
  enabled: boolean
  connected: boolean
  has_credentials: boolean
}

export interface PairingRequest {
  code: string
  platform: ChannelId
  platform_user_id: string
  platform_username: string
  expires_at: string // ISO datetime
}

export interface AuthorizedUser {
  id: string
  platform: ChannelId
  platform_user_id: string
  platform_username: string
  authorized_at: string
}

export interface ChannelSettings {
  default_data_space_id?: string
  default_model?: string
}

// ── API ────────────────────────────────────────────────────────────────────

export const channelsApi = {
  list: () => api.get<ChannelStatus[]>('/channels'),

  // 省略 credentials → 用已存凭据重新启用（开关快捷重启）
  enable: (ch: ChannelId, credentials?: Record<string, string>) =>
    api.post(`/channels/${ch}/enable`, { credentials }),
  disable: (ch: ChannelId) =>
    api.post(`/channels/${ch}/disable`),
  test: (ch: ChannelId, credentials: Record<string, string>) =>
    api.post<{ ok: boolean; detail?: string }>(`/channels/${ch}/test`, { credentials }),

  getPairings: () => api.get<PairingRequest[]>('/channels/pairings'),
  approvePairing: (code: string) => api.post('/channels/pairings/approve', { code }),
  rejectPairing: (code: string) => api.post('/channels/pairings/reject', { code }),

  getAuthorizedUsers: () => api.get<AuthorizedUser[]>('/channels/authorized-users'),
  revokeUser: (user_id: string) => api.post('/channels/authorized-users/revoke', { user_id }),

  getSettings: (ch: ChannelId) => api.get<ChannelSettings>(`/channels/${ch}/settings`),
  putSettings: (ch: ChannelId, s: ChannelSettings) =>
    api.put<ChannelSettings>(`/channels/${ch}/settings`, s),
}

// ── SSE helper (fetch-based, supports auth header) ────────────────────────

export type WeixinSSEEvent =
  | { type: 'qr';      qr_data_url: string }
  | { type: 'scanned' }
  | { type: 'done';    account_id: string; bot_token: string }
  | { type: 'error';   message: string }

/**
 * Opens the WeChat login SSE stream and calls `onEvent` for each parsed event.
 * Returns a cleanup function that aborts the request.
 *
 * Backend (ilink) sends the QR as a scan-target URL string in `qrcodeData`;
 * the frontend encodes it into a QR image (see WeixinForm). 旧实现假设 base64 PNG，已纠正。
 * SSE format:
 *   event: qr\ndata: {"qrcodeData":"https://liteapp.weixin.qq.com/q/..."}\n\n
 *   event: scanned\ndata: {}\n\n
 *   event: done\ndata: {"accountId":"...","botToken":"...","baseUrl":"..."}\n\n
 *   event: error\ndata: {"message":"..."}\n\n
 */
export async function startWeixinLoginSSE(
  onEvent: (e: WeixinSSEEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const token = await getValidToken()
  const response = await fetch('/api/channels/weixin/login', {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    signal,
  })

  if (!response.ok || !response.body) {
    throw new Error(`SSE request failed: ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let currentEvent = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''

      for (const line of lines) {
        if (line.startsWith('event: ')) {
          currentEvent = line.slice(7).trim()
        } else if (line.startsWith('data: ')) {
          const raw = line.slice(6).trim()
          try {
            const parsed = JSON.parse(raw)
            if (currentEvent === 'qr') {
              // 后端字段 qrcodeData = ilink 扫码 URL（需前端编码成二维码）；兼容旧 qr_data_url
              onEvent({ type: 'qr', qr_data_url: parsed.qrcodeData ?? parsed.qr_data_url ?? '' })
            } else if (currentEvent === 'scanned') {
              onEvent({ type: 'scanned' })
            } else if (currentEvent === 'done') {
              onEvent({
                type: 'done',
                account_id: parsed.accountId ?? parsed.account_id ?? '',
                bot_token: parsed.botToken ?? parsed.bot_token ?? '',
              })
            } else if (currentEvent === 'error') {
              onEvent({ type: 'error', message: parsed.message ?? 'Unknown error' })
            }
          } catch {
            // skip malformed SSE data
          }
          currentEvent = ''
        }
      }
    }
  } finally {
    reader.releaseLock()
  }
}
