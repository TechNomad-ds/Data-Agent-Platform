import { useState } from 'react'
import { Typography, message as antMessage, Tooltip, Input, Button } from 'antd'
import {
  CopyOutlined,
  CheckOutlined,
  UserOutlined,
  LikeOutlined,
  LikeFilled,
  DislikeOutlined,
  DislikeFilled,
  ReloadOutlined,
  EditOutlined,
} from '@ant-design/icons'
import { Message } from '@/api/chat'
import ThinkingBlock from './ThinkingBlock'
import PlanCard from './PlanCard'
import MarkdownRenderer from './MarkdownRenderer'
import { copyText } from '@/utils/clipboard'
import { colors } from '@/styles/tokens'

const { Text } = Typography
const { TextArea } = Input

interface MessageContentProps {
  message: Message
  onRegenerate?: () => void
  onFeedback?: (messageId: string, rating: number) => void
  onEditResend?: (messageId: string, newContent: string) => void
  conversationId?: string
}

function formatTime(dateStr: string): string {
  try {
    const d = new Date(dateStr)
    return `${d.getHours().toString().padStart(2, '0')}:${d
      .getMinutes()
      .toString()
      .padStart(2, '0')}`
  } catch {
    return ''
  }
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = async () => {
    if (await copyText(text)) {
      setCopied(true)
      antMessage.success('已复制')
      setTimeout(() => setCopied(false), 1800)
    } else {
      antMessage.error('复制失败')
    }
  }
  return (
    <Tooltip title={copied ? '已复制' : '复制'} placement="top">
      <span
        onClick={handleCopy}
        style={{
          cursor: 'pointer',
          color: colors.textMuted,
          fontSize: 13,
          padding: 4,
          borderRadius: 4,
          transition: 'background 0.12s, color 0.12s',
          display: 'inline-flex',
          alignItems: 'center',
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = colors.bgSubtle
          e.currentTarget.style.color = colors.textPrimary
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = 'transparent'
          e.currentTarget.style.color = colors.textMuted
        }}
      >
        {copied ? <CheckOutlined /> : <CopyOutlined />}
      </span>
    </Tooltip>
  )
}

// AI 头像 — 用极简圆形 + 内嵌点
function AIAvatar() {
  return (
    <div
      style={{
        width: 30,
        height: 30,
        borderRadius: 8,
        background: colors.aiAvatar,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
        boxShadow: '0 1px 2px rgba(15, 23, 42, 0.06)',
      }}
    >
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" aria-hidden>
        <path
          d="M12 2.5L13.5 9L20 10.5L13.5 12L12 18.5L10.5 12L4 10.5L10.5 9L12 2.5Z"
          fill="#ffffff"
        />
        <circle cx="12" cy="20.5" r="1.5" fill="#ffffff" opacity="0.7" />
      </svg>
    </div>
  )
}

function UserAvatar() {
  return (
    <div
      style={{
        width: 30,
        height: 30,
        borderRadius: 8,
        background: colors.userAvatar,
        color: '#fff',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        fontSize: 13,
        flexShrink: 0,
      }}
    >
      <UserOutlined />
    </div>
  )
}

function hasSegments(toolCalls: any[] | null): boolean {
  if (!toolCalls || toolCalls.length === 0) return false
  const t = toolCalls[0]?.type
  return t === 'text' || t === 'tools' || t === 'thinking'
}

function FeedbackButtons({
  messageId,
  onFeedback,
  onRegenerate,
}: {
  messageId: string
  onFeedback?: (id: string, rating: number) => void
  onRegenerate?: () => void
}) {
  const [voted, setVoted] = useState<'up' | 'down' | null>(null)

  const handleVote = (type: 'up' | 'down') => {
    if (voted === type) return
    setVoted(type)
    onFeedback?.(messageId, type === 'up' ? 5 : 1)
  }

  return (
    <>
      <Tooltip title="有帮助" placement="top">
        <span
          onClick={() => handleVote('up')}
          style={{
            cursor: 'pointer',
            color: voted === 'up' ? colors.success : colors.textMuted,
            fontSize: 13,
            padding: 4,
            borderRadius: 4,
            display: 'inline-flex',
            alignItems: 'center',
            transition: 'color 0.12s',
          }}
          onMouseEnter={(e) => {
            if (voted !== 'up') e.currentTarget.style.color = colors.textPrimary
          }}
          onMouseLeave={(e) => {
            if (voted !== 'up') e.currentTarget.style.color = colors.textMuted
          }}
        >
          {voted === 'up' ? <LikeFilled /> : <LikeOutlined />}
        </span>
      </Tooltip>
      <Tooltip title="需要改进" placement="top">
        <span
          onClick={() => handleVote('down')}
          style={{
            cursor: 'pointer',
            color: voted === 'down' ? colors.error : colors.textMuted,
            fontSize: 13,
            padding: 4,
            borderRadius: 4,
            display: 'inline-flex',
            alignItems: 'center',
            transition: 'color 0.12s',
          }}
          onMouseEnter={(e) => {
            if (voted !== 'down') e.currentTarget.style.color = colors.textPrimary
          }}
          onMouseLeave={(e) => {
            if (voted !== 'down') e.currentTarget.style.color = colors.textMuted
          }}
        >
          {voted === 'down' ? <DislikeFilled /> : <DislikeOutlined />}
        </span>
      </Tooltip>
      {onRegenerate && (
        <Tooltip title="重新生成" placement="top">
          <span
            onClick={onRegenerate}
            style={{
              cursor: 'pointer',
              color: colors.textMuted,
              fontSize: 13,
              padding: 4,
              borderRadius: 4,
              display: 'inline-flex',
              alignItems: 'center',
              transition: 'color 0.12s',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = colors.textPrimary
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = colors.textMuted
            }}
          >
            <ReloadOutlined />
          </span>
        </Tooltip>
      )}
    </>
  )
}

// 用户消息：右对齐胶囊；hover 显示编辑/复制（类似 ChatGPT/DeepSeek）。
// 编辑进入内联文本框，确认后回调 onEditResend 截断该消息之后的对话并重新发送。
function UserMessage({
  message,
  onEditResend,
}: {
  message: Message
  onEditResend?: (messageId: string, newContent: string) => void
}) {
  const [hover, setHover] = useState(false)
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(message.content || '')
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    if (await copyText(message.content || '')) {
      setCopied(true)
      antMessage.success('已复制')
      setTimeout(() => setCopied(false), 1800)
    } else {
      antMessage.error('复制失败')
    }
  }

  const startEdit = () => {
    setDraft(message.content || '')
    setEditing(true)
  }

  const submitEdit = () => {
    const next = draft.trim()
    if (!next) return
    setEditing(false)
    if (next !== (message.content || '')) {
      onEditResend?.(message.id, next)
    }
  }

  return (
    <div
      style={{ display: 'flex', gap: 12, flexDirection: 'row-reverse', alignItems: 'flex-start' }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <UserAvatar />
      <div style={{ maxWidth: '78%', minWidth: 0, width: editing ? '100%' : undefined }}>
        {editing ? (
          <div
            style={{
              background: colors.surface,
              border: `1px solid ${colors.borderStrong}`,
              borderRadius: 14,
              padding: 10,
            }}
          >
            <TextArea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              autoSize={{ minRows: 1, maxRows: 8 }}
              variant="borderless"
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey && !(e.nativeEvent as any).isComposing) {
                  e.preventDefault()
                  submitEdit()
                }
                if (e.key === 'Escape') setEditing(false)
              }}
              style={{ fontSize: 15, padding: 0, lineHeight: 1.6 }}
            />
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 8 }}>
              <Button size="small" onClick={() => setEditing(false)}>取消</Button>
              <Button size="small" type="primary" onClick={submitEdit} disabled={!draft.trim()}>
                发送
              </Button>
            </div>
          </div>
        ) : (
          <>
            <div
              style={{
                padding: '11px 15px',
                borderRadius: 14,
                background: colors.userBubble,
                color: colors.userBubbleText,
                fontSize: 15.5,
                lineHeight: 1.7,
                whiteSpace: 'pre-wrap',
                wordBreak: 'break-word',
              }}
            >
              {message.content}
            </div>
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'flex-end',
                gap: 6,
                marginTop: 4,
                paddingRight: 4,
                minHeight: 18,
              }}
            >
              <span
                style={{
                  display: 'flex',
                  gap: 4,
                  opacity: hover ? 1 : 0,
                  transition: 'opacity 0.15s',
                }}
              >
                {onEditResend && (
                  <Tooltip title="编辑" placement="top">
                    <span onClick={startEdit} style={iconBtnStyle}>
                      <EditOutlined />
                    </span>
                  </Tooltip>
                )}
                <Tooltip title={copied ? '已复制' : '复制'} placement="top">
                  <span onClick={handleCopy} style={iconBtnStyle}>
                    {copied ? <CheckOutlined /> : <CopyOutlined />}
                  </span>
                </Tooltip>
              </span>
              <Text style={{ fontSize: 11, color: colors.textMuted }}>
                {formatTime(message.created_at)}
              </Text>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

const iconBtnStyle: React.CSSProperties = {
  cursor: 'pointer',
  color: colors.textMuted,
  fontSize: 12.5,
  padding: 4,
  borderRadius: 4,
  display: 'inline-flex',
  alignItems: 'center',
}

export default function MessageContent({ message, onRegenerate, onFeedback, onEditResend, conversationId }: MessageContentProps) {
  const isUser = message.role === 'user'
  const segments = hasSegments(message.tool_calls) ? message.tool_calls! : null
  const textContent = segments
    ? segments
        .filter((s: any) => s.type === 'text')
        .map((s: any) => s.content || '')
        .join('')
    : message.content || ''

  if (isUser) {
    return <UserMessage message={message} onEditResend={onEditResend} />
  }

  // 助手消息：ChatGPT 风 — 不加卡片/边框，直接展示
  return (
    <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
      <AIAvatar />
      <div style={{ flex: 1, minWidth: 0 }}>
        {segments ? (
          <div>
            {segments.map((seg: any, i: number) =>
              seg.type === 'text' ? (
                <div key={i} style={{ marginBottom: 8 }}>
                  <MarkdownRenderer content={seg.content || ''} conversationId={conversationId} />
                </div>
              ) : seg.type === 'thinking' ? (
                <div key={i} style={{ marginBottom: 8 }}>
                  <Text
                    style={{
                      fontSize: 13,
                      color: colors.textMuted,
                      fontStyle: 'italic',
                      whiteSpace: 'pre-wrap',
                    }}
                  >
                    {seg.content || ''}
                  </Text>
                </div>
              ) : seg.type === 'plan' ? (
                <div key={i} style={{ marginBottom: 10 }}>
                  <PlanCard steps={seg.steps || []} />
                </div>
              ) : (
                <div key={i} style={{ marginBottom: 10 }}>
                  <ThinkingBlock
                    toolEvents={seg.events || []}
                    defaultExpanded={false}
                  />
                </div>
              )
            )}
          </div>
        ) : (
          <MarkdownRenderer content={message.content || ''} conversationId={conversationId} />
        )}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            marginTop: 6,
            paddingLeft: 0,
          }}
        >
          <Text style={{ fontSize: 11, color: colors.textMuted }}>
            {formatTime(message.created_at)}
          </Text>
          {message.credits_used != null && message.credits_used > 0 && (
            <Text style={{ fontSize: 10, color: colors.textMuted }}>
              {message.credits_used} 额度
            </Text>
          )}
          {textContent && <CopyButton text={textContent} />}
          <FeedbackButtons
            messageId={message.id}
            onFeedback={onFeedback}
            onRegenerate={onRegenerate}
          />
        </div>
      </div>
    </div>
  )
}
