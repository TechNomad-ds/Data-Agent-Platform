import { useState } from 'react'
import { Typography } from 'antd'
import {
  ThunderboltOutlined, DownOutlined, RightOutlined,
  CheckCircleOutlined, LoadingOutlined,
  SearchOutlined, FileTextOutlined, CodeOutlined,
  BarChartOutlined, DatabaseOutlined,
} from '@ant-design/icons'
import { SSEEvent } from '@/api/chat'

const { Text } = Typography

interface ThinkingBlockProps {
  thinkingText?: string
  toolEvents: SSEEvent[]
  defaultExpanded?: boolean
}

const toolMeta: Record<string, { label: string; icon: React.ReactNode }> = {
  search_data_space: { label: '搜索数据空间', icon: <SearchOutlined /> },
  read_file: { label: '读取文件', icon: <FileTextOutlined /> },
  inspect_data: { label: '查看数据结构', icon: <DatabaseOutlined /> },
  pandas_query: { label: '数据查询', icon: <BarChartOutlined /> },
  execute_python: { label: '执行代码', icon: <CodeOutlined /> },
}

export default function ThinkingBlock({ thinkingText, toolEvents, defaultExpanded = false }: ThinkingBlockProps) {
  const [expanded, setExpanded] = useState(defaultExpanded)

  if (!thinkingText && toolEvents.length === 0) return null

  const toolUseCount = toolEvents.filter(e => e.type === 'tool_use').length
  const toolResultCount = toolEvents.filter(e => e.type === 'tool_result').length
  const allDone = toolUseCount > 0 && toolUseCount === toolResultCount

  return (
    <div style={{
      borderRadius: 10,
      border: '1px solid #e8e8e8',
      background: '#fafbfc',
      overflow: 'hidden',
    }}>
      <div
        onClick={() => setExpanded(!expanded)}
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          padding: '8px 12px',
          cursor: 'pointer',
          userSelect: 'none',
        }}
      >
        {expanded
          ? <DownOutlined style={{ fontSize: 10, color: '#8c8c8c' }} />
          : <RightOutlined style={{ fontSize: 10, color: '#8c8c8c' }} />
        }
        <ThunderboltOutlined style={{ color: '#faad14', fontSize: 13 }} />
        <Text style={{ fontSize: 12, color: '#595959', fontWeight: 500 }}>
          {allDone ? '已完成' : '执行中'}
        </Text>
        {toolUseCount > 0 && (
          <Text style={{ fontSize: 11, color: '#8c8c8c' }}>
            · {toolUseCount} 次工具调用
          </Text>
        )}
        {allDone && <CheckCircleOutlined style={{ fontSize: 11, color: '#52c41a', marginLeft: 'auto' }} />}
        {!allDone && toolUseCount > 0 && <LoadingOutlined style={{ fontSize: 11, color: '#1677ff', marginLeft: 'auto' }} />}
      </div>
      {expanded && (
        <div style={{ padding: '0 12px 10px', borderTop: '1px solid #f0f0f0' }}>
          {thinkingText && (
            <div style={{ padding: '8px 0' }}>
              <Text type="secondary" style={{ fontSize: 12, fontStyle: 'italic' }}>
                {thinkingText}
              </Text>
            </div>
          )}
          {toolEvents.map((event, i) => {
            const name = event.name || 'unknown'
            const meta = toolMeta[name] || { label: name, icon: <CodeOutlined /> }

            if (event.type === 'tool_use') {
              const hasResult = toolEvents.slice(i + 1).some(e => e.type === 'tool_result' && e.name === name)
              return (
                <div key={i} style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  padding: '6px 0',
                  borderBottom: '1px solid #f5f5f5',
                }}>
                  {hasResult
                    ? <CheckCircleOutlined style={{ fontSize: 11, color: '#52c41a' }} />
                    : <LoadingOutlined style={{ fontSize: 11, color: '#1677ff' }} />
                  }
                  <span style={{ fontSize: 12, color: hasResult ? '#52c41a' : '#1677ff' }}>{meta.icon}</span>
                  <Text style={{ fontSize: 12, fontWeight: 500 }}>{meta.label}</Text>
                  {event.input && (
                    <Text type="secondary" style={{ fontSize: 11, marginLeft: 'auto' }} ellipsis>
                      {Object.entries(event.input).map(([k, v]) =>
                        `${k}: ${String(v).slice(0, 25)}`
                      ).join(', ')}
                    </Text>
                  )}
                </div>
              )
            }

            if (event.type === 'tool_result') {
              return (
                <div key={i} style={{ padding: '4px 0 6px 17px', borderBottom: '1px solid #f5f5f5' }}>
                  {event.content && (
                    <Text type="secondary" style={{ fontSize: 11, whiteSpace: 'pre-wrap', display: 'block', maxHeight: 60, overflow: 'hidden' }}>
                      {event.content.slice(0, 150)}{event.content.length > 150 ? '...' : ''}
                    </Text>
                  )}
                </div>
              )
            }

            return null
          })}
        </div>
      )}
    </div>
  )
}
