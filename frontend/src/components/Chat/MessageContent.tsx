import { useState } from 'react'
import { Typography, message as antMessage } from 'antd'
import { UserOutlined, RobotOutlined, CopyOutlined, CheckOutlined } from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { Message } from '@/api/chat'
import ThinkingBlock from './ThinkingBlock'
import ChartMessage from '@/components/Charts/ChartMessage'
import { colors, radius } from '@/styles/tokens'

const { Text } = Typography

interface MessageContentProps {
  message: Message
}

function formatTime(dateStr: string): string {
  try {
    const d = new Date(dateStr)
    return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
  } catch { return '' }
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = () => {
    navigator.clipboard.writeText(text)
    setCopied(true)
    antMessage.success('已复制')
    setTimeout(() => setCopied(false), 2000)
  }
  return (
    <span
      onClick={handleCopy}
      style={{ cursor: 'pointer', color: colors.textMuted, fontSize: 12, display: 'inline-flex', alignItems: 'center', gap: 3 }}
      onMouseEnter={e => (e.currentTarget.style.color = colors.primary)}
      onMouseLeave={e => (e.currentTarget.style.color = colors.textMuted)}
    >
      {copied ? <CheckOutlined /> : <CopyOutlined />}
    </span>
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
    <div className="markdown-body" style={{ fontSize: 14, lineHeight: 1.7 }}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ className, children, ...props }) {
            const match = /language-(\w+)/.exec(className || '')
            const codeString = String(children).replace(/\n$/, '')
            if (match || codeString.includes('\n')) {
              return (
                <SyntaxHighlighter style={oneDark} language={match?.[1] || 'text'} PreTag="div" customStyle={{ borderRadius: 8, fontSize: 13, margin: '8px 0' }}>
                  {codeString}
                </SyntaxHighlighter>
              )
            }
            return <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: 4, fontSize: 13, color: '#7c3aed' }} {...props}>{children}</code>
          },
        }}
      >{content}</ReactMarkdown>
    </div>
  )
}

function hasSegments(toolCalls: any[] | null): boolean {
  if (!toolCalls || toolCalls.length === 0) return false
  return toolCalls[0]?.type === 'text' || toolCalls[0]?.type === 'tools'
}

export default function MessageContent({ message }: MessageContentProps) {
  const isUser = message.role === 'user'
  const segments = hasSegments(message.tool_calls) ? message.tool_calls! : null
  const textContent = segments
    ? segments.filter((s: any) => s.type === 'text').map((s: any) => s.content || '').join('')
    : (message.content || '')

  return (
    <div style={{ display: 'flex', gap: 12, flexDirection: isUser ? 'row-reverse' : 'row', alignItems: 'flex-start' }}>
      <div style={{
        width: 30, height: 30, borderRadius: radius.md,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: isUser ? 'linear-gradient(135deg, #3b82f6, #1d4ed8)' : `linear-gradient(135deg, ${colors.primary}, #7c3aed)`,
        color: '#fff', flexShrink: 0, fontSize: 12,
      }}>
        {isUser ? <UserOutlined /> : <RobotOutlined />}
      </div>
      <div style={{ maxWidth: '80%', minWidth: 0 }}>
        {isUser ? (
          <div style={{ padding: '10px 14px', borderRadius: '14px 14px 4px 14px', background: colors.userBubble, border: `1px solid ${colors.aiBorder}` }}>
            <Text style={{ color: colors.textPrimary, whiteSpace: 'pre-wrap', fontSize: 14 }}>{message.content}</Text>
          </div>
        ) : segments ? (
          <div>
            {segments.map((seg: any, i: number) => seg.type === 'text' ? (
              <div key={i} style={{ padding: '12px 16px', borderRadius: radius.lg, marginBottom: 8, background: colors.surface, borderLeft: `3px solid ${colors.primary}`, boxShadow: '0 1px 3px rgba(0,0,0,0.04)' }}>
                <MarkdownBlock content={seg.content || ''} />
              </div>
            ) : (
              <div key={i} style={{ marginBottom: 8 }}><ThinkingBlock toolEvents={seg.events || []} defaultExpanded={false} /></div>
            ))}
          </div>
        ) : (
          <div style={{ padding: '12px 16px', borderRadius: '4px 14px 14px 14px', background: colors.surface, borderLeft: `3px solid ${colors.primary}`, boxShadow: '0 1px 3px rgba(0,0,0,0.04)' }}>
            <MarkdownBlock content={message.content || ''} />
          </div>
        )}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 4, justifyContent: isUser ? 'flex-end' : 'flex-start', padding: '0 4px' }}>
          <Text style={{ fontSize: 11, color: colors.textMuted }}>{formatTime(message.created_at)}</Text>
          {!isUser && textContent && <CopyButton text={textContent} />}
        </div>
      </div>
    </div>
  )
}
