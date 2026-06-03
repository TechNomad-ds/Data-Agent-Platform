import { useState } from 'react'
import { Typography, message as antMessage, Tooltip } from 'antd'
import {
  CopyOutlined,
  CheckOutlined,
  UserOutlined,
  LikeOutlined,
  LikeFilled,
  DislikeOutlined,
  DislikeFilled,
  ReloadOutlined,
} from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { Message } from '@/api/chat'
import ThinkingBlock from './ThinkingBlock'
import ChartMessage from '@/components/Charts/ChartMessage'
import { colors } from '@/styles/tokens'

const { Text } = Typography

interface MessageContentProps {
  message: Message
  onRegenerate?: () => void
  onFeedback?: (messageId: string, rating: number) => void
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
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      antMessage.success('已复制')
      setTimeout(() => setCopied(false), 1800)
    } catch {
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

function MarkdownBlock({ content }: { content: string }) {
  const parts = content.split(/```chart\n([\s\S]*?)```/)
  if (parts.length === 1) return <MarkdownRaw content={content} />
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 0
          ? part.trim() && <MarkdownRaw key={i} content={part} />
          : <ChartMessage key={i} chartJson={part} />
      )}
    </>
  )
}

function MarkdownRaw({ content }: { content: string }) {
  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          table({ children, ...props }) {
            return (
              <div className="table-wrapper">
                <table {...props}>{children}</table>
              </div>
            )
          },
          code({ className, children, ...props }) {
            const match = /language-(\w+)/.exec(className || '')
            const codeString = String(children).replace(/\n$/, '')
            if (match || codeString.includes('\n')) {
              return (
                <SyntaxHighlighter
                  style={oneDark}
                  language={match?.[1] || 'text'}
                  PreTag="div"
                  customStyle={{
                    borderRadius: 10,
                    fontSize: 13,
                    margin: '12px 0',
                    padding: '14px 16px',
                  }}
                >
                  {codeString}
                </SyntaxHighlighter>
              )
            }
            return (
              <code
                style={{
                  background: colors.bgSubtle,
                  padding: '2px 6px',
                  borderRadius: 4,
                  fontSize: '0.875em',
                  color: colors.textPrimary,
                  fontFamily:
                    "'SF Mono', SFMono-Regular, Menlo, Consolas, monospace",
                }}
                {...props}
              >
                {children}
              </code>
            )
          },
        }}
      >
        {content}
      </ReactMarkdown>
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

export default function MessageContent({ message, onRegenerate, onFeedback }: MessageContentProps) {
  const isUser = message.role === 'user'
  const segments = hasSegments(message.tool_calls) ? message.tool_calls! : null
  const textContent = segments
    ? segments
        .filter((s: any) => s.type === 'text')
        .map((s: any) => s.content || '')
        .join('')
    : message.content || ''

  if (isUser) {
    // 用户消息：右对齐淡灰胶囊，不再使用花哨的渐变头像
    return (
      <div
        style={{
          display: 'flex',
          gap: 12,
          flexDirection: 'row-reverse',
          alignItems: 'flex-start',
        }}
      >
        <UserAvatar />
        <div style={{ maxWidth: '78%', minWidth: 0 }}>
          <div
            style={{
              padding: '10px 14px',
              borderRadius: 14,
              background: colors.userBubble,
              color: colors.userBubbleText,
              fontSize: 14.5,
              lineHeight: 1.65,
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}
          >
            {message.content}
          </div>
          <div
            style={{
              fontSize: 11,
              color: colors.textMuted,
              marginTop: 4,
              textAlign: 'right',
              paddingRight: 4,
            }}
          >
            {formatTime(message.created_at)}
          </div>
        </div>
      </div>
    )
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
                  <MarkdownBlock content={seg.content || ''} />
                </div>
              ) : seg.type === 'thinking' ? (
                <div
                  key={i}
                  style={{
                    marginBottom: 10,
                    paddingLeft: 10,
                    borderLeft: `2px solid ${colors.border}`,
                    fontSize: 12.5,
                    color: colors.textMuted,
                    fontStyle: 'italic',
                    whiteSpace: 'pre-wrap',
                    lineHeight: 1.6,
                  }}
                >
                  {seg.content || ''}
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
          <MarkdownBlock content={message.content || ''} />
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
