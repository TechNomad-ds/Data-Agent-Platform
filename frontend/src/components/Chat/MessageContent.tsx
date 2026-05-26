import { Typography } from 'antd'
import { UserOutlined, RobotOutlined } from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { Message } from '@/api/chat'
import ThinkingBlock from './ThinkingBlock'
import ChartMessage from '@/components/Charts/ChartMessage'

const { Text } = Typography

interface MessageContentProps {
  message: Message
}

function MarkdownBlock({ content }: { content: string }) {
  const parts = content.split(/```chart\n([\s\S]*?)```/)

  if (parts.length === 1) {
    return <MarkdownRaw content={content} />
  }

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
                <SyntaxHighlighter
                  style={oneDark}
                  language={match?.[1] || 'text'}
                  PreTag="div"
                  customStyle={{ borderRadius: 8, fontSize: 13, margin: '8px 0' }}
                >
                  {codeString}
                </SyntaxHighlighter>
              )
            }
            return (
              <code style={{ background: '#f1f5f9', padding: '2px 6px', borderRadius: 4, fontSize: 13, color: '#7c3aed' }} {...props}>
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

function hasSegmentsStructure(toolCalls: any[] | null): boolean {
  if (!toolCalls || toolCalls.length === 0) return false
  return toolCalls[0]?.type === 'text' || toolCalls[0]?.type === 'tools'
}

export default function MessageContent({ message }: MessageContentProps) {
  const isUser = message.role === 'user'
  const segments = hasSegmentsStructure(message.tool_calls) ? message.tool_calls! : null

  return (
    <div style={{ display: 'flex', gap: 12, flexDirection: isUser ? 'row-reverse' : 'row' }}>
      <div style={{
        width: 32, height: 32, borderRadius: 8,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: isUser
          ? 'linear-gradient(135deg, #3b82f6, #1d4ed8)'
          : 'linear-gradient(135deg, #6366f1, #8b5cf6)',
        color: '#fff', flexShrink: 0, fontSize: 13,
      }}>
        {isUser ? <UserOutlined /> : <RobotOutlined />}
      </div>
      <div style={{ maxWidth: '100%', minWidth: 0 }}>
        {isUser ? (
          <div style={{
            padding: '10px 14px', borderRadius: '12px 12px 4px 12px',
            background: '#e2e8f0', color: '#1e293b',
          }}>
            <Text style={{ color: '#1e293b', whiteSpace: 'pre-wrap', fontSize: 14 }}>{message.content}</Text>
          </div>
        ) : segments ? (
          <div>
            {segments.map((seg: any, i: number) => (
              seg.type === 'text' ? (
                <div key={i} style={{
                  padding: '10px 14px', borderRadius: 10, marginBottom: 8,
                  background: '#ffffff', border: '1px solid #e2e8f0',
                }}>
                  <MarkdownBlock content={seg.content || ''} />
                </div>
              ) : (
                <div key={i} style={{ marginBottom: 8 }}>
                  <ThinkingBlock toolEvents={seg.events || []} defaultExpanded={false} />
                </div>
              )
            ))}
            {message.credits_used && (
              <div style={{ textAlign: 'right', marginTop: 2 }}>
                <Text style={{ fontSize: 11, color: '#94a3b8' }}>消耗 {message.credits_used} 点</Text>
              </div>
            )}
          </div>
        ) : (
          <div style={{
            padding: '10px 14px', borderRadius: '12px 12px 12px 4px',
            background: '#ffffff', border: '1px solid #e2e8f0',
          }}>
            <MarkdownBlock content={message.content || ''} />
            {message.credits_used && (
              <div style={{ marginTop: 6, textAlign: 'right' }}>
                <Text style={{ fontSize: 11, color: '#94a3b8' }}>消耗 {message.credits_used} 点</Text>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
