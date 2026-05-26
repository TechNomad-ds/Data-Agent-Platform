import { Typography, Button, Empty } from 'antd'
import { DeleteOutlined } from '@ant-design/icons'
import { Conversation } from '@/api/chat'
import dayjs from 'dayjs'

const { Text } = Typography

interface Props {
  conversations: Conversation[]
  currentId: string | undefined
  onSelect: (id: string) => void
  onDelete: (id: string) => void
}

export default function ConversationList({ conversations, currentId, onSelect, onDelete }: Props) {
  if (conversations.length === 0) {
    return (
      <div style={{ padding: '40px 16px', textAlign: 'center' }}>
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={<Text style={{ color: '#94a3b8', fontSize: 13 }}>暂无对话</Text>}
        />
      </div>
    )
  }

  return (
    <div style={{ flex: 1, overflow: 'auto' }}>
      {conversations.map(item => (
        <div
          key={item.id}
          onClick={() => onSelect(item.id)}
          style={{
            padding: '10px 14px',
            margin: '2px 8px',
            borderRadius: 8,
            cursor: 'pointer',
            background: currentId === item.id ? '#f1f5f9' : 'transparent',
            transition: 'background 0.15s',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
          }}
          onMouseEnter={e => {
            if (currentId !== item.id) e.currentTarget.style.background = '#f8fafc'
          }}
          onMouseLeave={e => {
            if (currentId !== item.id) e.currentTarget.style.background = 'transparent'
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            <Text
              ellipsis
              style={{
                display: 'block',
                fontSize: 13,
                color: currentId === item.id ? '#1e293b' : '#475569',
                fontWeight: currentId === item.id ? 500 : 400,
              }}
            >
              {item.title || '新对话'}
            </Text>
            <Text style={{ fontSize: 11, color: '#94a3b8' }}>
              {dayjs(item.updated_at).format('MM/DD HH:mm')}
            </Text>
          </div>
          <Button
            type="text"
            size="small"
            icon={<DeleteOutlined style={{ fontSize: 12 }} />}
            onClick={e => { e.stopPropagation(); onDelete(item.id) }}
            style={{ color: '#94a3b8', opacity: 0, transition: 'opacity 0.15s' }}
            className="conv-delete-btn"
          />
        </div>
      ))}
    </div>
  )
}
