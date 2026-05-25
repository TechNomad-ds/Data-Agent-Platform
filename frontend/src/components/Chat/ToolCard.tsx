import { Card, Tag, Typography } from 'antd'
import { CheckCircleOutlined, LoadingOutlined } from '@ant-design/icons'
import { SSEEvent } from '@/api/chat'

const { Text } = Typography

interface ToolCardProps {
  event: SSEEvent
}

const toolNameMap: Record<string, string> = {
  search_data_space: '搜索数据空间',
  read_file: '读取文件',
  inspect_data: '查看数据结构',
  pandas_query: '数据查询',
  execute_python: '执行代码',
}

export default function ToolCard({ event }: ToolCardProps) {
  const isResult = event.type === 'tool_result'
  const name = event.name || '工具调用'

  return (
    <Card
      size="small"
      style={{
        marginBottom: 8,
        borderRadius: 8,
        background: '#fafafa',
        border: '1px solid #f0f0f0',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        {isResult ? (
          <CheckCircleOutlined style={{ color: '#52c41a' }} />
        ) : (
          <LoadingOutlined style={{ color: '#1677ff' }} />
        )}
        <Tag color={isResult ? 'success' : 'processing'}>
          {toolNameMap[name] || name}
        </Tag>
        {event.type === 'tool_use' && event.input && (
          <Text type="secondary" style={{ fontSize: 12 }} ellipsis>
            {JSON.stringify(event.input).slice(0, 80)}
          </Text>
        )}
        {isResult && event.content && (
          <Text type="secondary" style={{ fontSize: 12 }} ellipsis>
            {event.content.slice(0, 100)}
          </Text>
        )}
      </div>
    </Card>
  )
}
