import { Typography } from 'antd'
import { UserOutlined, RobotOutlined } from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { Message } from '@/api/chat'

const { Text } = Typography

interface MessageContentProps {
  message: Message
}

export default function MessageContent({ message }: MessageContentProps) {
  const isUser = message.role === 'user'

  return (
    <div
      style={{
        display: 'flex',
        gap: 12,
        flexDirection: isUser ? 'row-reverse' : 'row',
      }}
    >
      <div
        style={{
          width: 34,
          height: 34,
          borderRadius: '50%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: isUser
            ? 'linear-gradient(135deg, #1677ff 0%, #0958d9 100%)'
            : 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
          color: '#fff',
          flexShrink: 0,
          fontSize: 14,
        }}
      >
        {isUser ? <UserOutlined /> : <RobotOutlined />}
      </div>
      <div
        style={{
          maxWidth: '78%',
          padding: '12px 16px',
          borderRadius: isUser ? '16px 16px 4px 16px' : '16px 16px 16px 4px',
          background: isUser
            ? 'linear-gradient(135deg, #1677ff 0%, #0958d9 100%)'
            : '#f8f9fa',
          color: isUser ? '#fff' : '#1f2937',
          boxShadow: '0 1px 3px rgba(0,0,0,0.06)',
        }}
      >
        {isUser ? (
          <Text style={{ color: '#fff', whiteSpace: 'pre-wrap', fontSize: 14 }}>{message.content}</Text>
        ) : (
          <div className="markdown-body" style={{ fontSize: 14, lineHeight: 1.7 }}>
            <ReactMarkdown
              components={{
                code({ className, children, ...props }) {
                  const match = /language-(\w+)/.exec(className || '')
                  const codeString = String(children).replace(/\n$/, '')
                  if (match) {
                    return (
                      <SyntaxHighlighter
                        style={oneLight}
                        language={match[1]}
                        PreTag="div"
                        customStyle={{
                          borderRadius: 8,
                          fontSize: 13,
                          margin: '8px 0',
                        }}
                      >
                        {codeString}
                      </SyntaxHighlighter>
                    )
                  }
                  return (
                    <code
                      style={{
                        background: '#e8eaed',
                        padding: '2px 6px',
                        borderRadius: 4,
                        fontSize: 13,
                      }}
                      {...props}
                    >
                      {children}
                    </code>
                  )
                },
              }}
            >
              {message.content || ''}
            </ReactMarkdown>
          </div>
        )}
        {message.credits_used && (
          <div style={{ marginTop: 6, textAlign: 'right' }}>
            <Text style={{
              fontSize: 11,
              color: isUser ? 'rgba(255,255,255,0.7)' : '#999',
            }}>
              消耗 {message.credits_used} 点
            </Text>
          </div>
        )}
      </div>
    </div>
  )
}
