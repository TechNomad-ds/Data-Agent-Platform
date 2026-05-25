import { Typography } from 'antd'
import { UserOutlined, RobotOutlined } from '@ant-design/icons'
import ReactMarkdown from 'react-markdown'
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
          width: 32,
          height: 32,
          borderRadius: '50%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: isUser ? '#1677ff' : '#f0f0f0',
          color: isUser ? '#fff' : '#666',
          flexShrink: 0,
        }}
      >
        {isUser ? <UserOutlined /> : <RobotOutlined />}
      </div>
      <div
        style={{
          maxWidth: '75%',
          padding: '10px 16px',
          borderRadius: isUser ? '12px 12px 0 12px' : '12px 12px 12px 0',
          background: isUser ? '#1677ff' : '#f5f5f5',
          color: isUser ? '#fff' : '#333',
        }}
      >
        {isUser ? (
          <Text style={{ color: '#fff', whiteSpace: 'pre-wrap' }}>{message.content}</Text>
        ) : (
          <div className="markdown-body" style={{ fontSize: 14, lineHeight: 1.6 }}>
            <ReactMarkdown>{message.content || ''}</ReactMarkdown>
          </div>
        )}
        {message.credits_used && (
          <div style={{ marginTop: 4, textAlign: 'right' }}>
            <Text type="secondary" style={{ fontSize: 11, color: isUser ? 'rgba(255,255,255,0.7)' : undefined }}>
              消耗 {message.credits_used} 点
            </Text>
          </div>
        )}
      </div>
    </div>
  )
}
