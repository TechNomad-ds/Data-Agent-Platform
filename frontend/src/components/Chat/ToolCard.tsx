import { Typography } from 'antd'
import {
  CheckCircleOutlined, LoadingOutlined,
  SearchOutlined, FileTextOutlined, CodeOutlined,
  BarChartOutlined, DatabaseOutlined,
  NodeIndexOutlined, ApartmentOutlined, QuestionCircleOutlined,
  CloudUploadOutlined, ImportOutlined, BranchesOutlined,
} from '@ant-design/icons'
import { SSEEvent } from '@/api/chat'

const { Text } = Typography

interface ToolCardProps {
  event: SSEEvent
}

const toolConfig: Record<string, { label: string; icon: React.ReactNode; color: string }> = {
  search_data_space: { label: '搜索数据空间', icon: <SearchOutlined />, color: '#1677ff' },
  read_file: { label: '读取文件', icon: <FileTextOutlined />, color: '#52c41a' },
  inspect_data: { label: '查看数据结构', icon: <DatabaseOutlined />, color: '#722ed1' },
  pandas_query: { label: '数据查询', icon: <BarChartOutlined />, color: '#fa8c16' },
  sqlite_query: { label: 'SQL 查询', icon: <DatabaseOutlined />, color: '#13c2c2' },
  execute_python: { label: '执行代码', icon: <CodeOutlined />, color: '#eb2f96' },
  generate_chart: { label: '生成图表', icon: <BarChartOutlined />, color: '#2f54eb' },
  save_memory: { label: '保存记忆', icon: <FileTextOutlined />, color: '#8c8c8c' },
  graph_search: { label: '图谱搜索', icon: <NodeIndexOutlined />, color: '#9254de' },
  graph_traverse: { label: '图谱遍历', icon: <ApartmentOutlined />, color: '#9254de' },
  nl2sql: { label: '自然语言查询', icon: <QuestionCircleOutlined />, color: '#13c2c2' },
  kb_reindex_file: { label: '重建索引', icon: <CloudUploadOutlined />, color: '#faad14' },
  db_import_csv: { label: '导入数据表', icon: <ImportOutlined />, color: '#52c41a' },
  graph_extract_from_text: { label: '提取知识图谱', icon: <BranchesOutlined />, color: '#9254de' },
}

export default function ToolCard({ event }: ToolCardProps) {
  const isResult = event.type === 'tool_result'
  const name = event.name || 'unknown'
  const config = toolConfig[name] || { label: name, icon: <CodeOutlined />, color: '#666' }

  return (
    <div
      style={{
        marginBottom: 8,
        padding: '10px 14px',
        borderRadius: 10,
        background: isResult ? '#f6ffed' : '#f0f5ff',
        border: `1px solid ${isResult ? '#b7eb8f' : '#adc6ff'}`,
        transition: 'all 0.2s',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        {isResult ? (
          <CheckCircleOutlined style={{ color: '#52c41a', fontSize: 14 }} />
        ) : (
          <LoadingOutlined style={{ color: '#1677ff', fontSize: 14 }} />
        )}
        <span style={{ color: config.color, fontSize: 13 }}>{config.icon}</span>
        <Text strong style={{ fontSize: 13 }}>{config.label}</Text>
        {event.type === 'tool_use' && event.input && (
          <Text type="secondary" style={{ fontSize: 11, marginLeft: 'auto' }} ellipsis>
            {Object.entries(event.input).map(([k, v]) =>
              `${k}: ${String(v).slice(0, 30)}`
            ).join(', ')}
          </Text>
        )}
      </div>
      {isResult && event.content && (
        <div style={{ marginTop: 6, paddingLeft: 22 }}>
          <Text type="secondary" style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}>
            {event.content.slice(0, 200)}{event.content.length > 200 ? '...' : ''}
          </Text>
        </div>
      )}
    </div>
  )
}
