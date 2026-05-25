import { Typography } from 'antd'
import { UserOutlined, RobotOutlined } from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { Message } from '@/api/chat'
import ThinkingBlock from './ThinkingBlock'

const { Text } = Typography

interface MessageContentProps {
  message: Message
}

function MarkdownBlock({ content }: { content: string }) {
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
                  style={oneLight}
                  language={match?.[1] || 'text'}
                  PreTag="div"
                  customStyle={{ borderRadius: 8, fontSize: 13, margin: '8px 0' }}
                >
                  {codeString}
                </SyntaxHighlighter>
              )
            }
            return (
              <code style={{ background: '#e8eaed', padding: '2px 6px', borderRadius: 4, fontSize: 13 }} {...props}>
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
        width: 34, height: 34, borderRadius: '50%',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: isUser
          ? 'linear-gradient(135deg, #1677ff 0%, #0958d9 100%)'
          : 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
        color: '#fff', flexShrink: 0, fontSize: 14,
      }}>
        {isUser ? <UserOutlined /> : <RobotOutlined />}
      </div>
      <div style={{ maxWidth: '78%', minWidth: 0 }}>
        {isUser ? (
          <div style={{
            padding: '12px 16px', borderRadius: '16px 16px 4px 16px',
            background: 'linear-gradient(135deg, #1677ff 0%, #0958d9 100%)',
            color: '#fff', boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
          }}>
            <Text style={{ color: '#fff', whiteSpace: 'pre-wrap', fontSize: 14 }}>{message.content}</Text>
          </div>
        ) : segments ? (
          // Render with interleaved segments
          <div>
            {segments.map((seg: any, i: number) => (
              seg.type === 'text' ? (
                <div key={i} style={{
                  padding: '12px 16px', borderRadius: 12, marginBottom: 8,
                  background: '#f8f9fa', color: '#1f2937',
                  boxShadow: '0 1px 3px rgba(0,0,0,0.04)',
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
                <Text style={{ fontSize: 11, color: '#999' }}>消耗 {message.credits_used} 点</Text>
              </div>
            )}
          </div>
        ) : (
          // Fallback: plain message without segments
          <div style={{
            padding: '12px 16px', borderRadius: '16px 16px 16px 4px',
            background: '#f8f9fa', color: '#1f2937',
            boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
          }}>
            <MarkdownBlock content={message.content || ''} />
            {message.credits_used && (
              <div style={{ marginTop: 6, textAlign: 'right' }}>
                <Text style={{ fontSize: 11, color: '#999' }}>消耗 {message.credits_used} 点</Text>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
