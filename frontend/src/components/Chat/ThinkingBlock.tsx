import { useState } from 'react'
import { Typography } from 'antd'
import {
  ThunderboltOutlined,
  DownOutlined,
  RightOutlined,
  SearchOutlined,
  FileTextOutlined,
  CodeOutlined,
  BarChartOutlined,
  DatabaseOutlined,
} from '@ant-design/icons'
import { SSEEvent } from '@/api/chat'
import { colors } from '@/styles/tokens'
import ChartMessage from '@/components/Charts/ChartMessage'

const { Text } = Typography

interface ThinkingBlockProps {
  thinkingText?: string
  toolEvents: SSEEvent[]
  defaultExpanded?: boolean
}

const toolMeta: Record<string, { label: string; icon: React.ReactNode; userHint: (input?: Record<string, unknown>) => string }> = {
  search_data_space: { label: '搜索相关内容', icon: <SearchOutlined />, userHint: (i) => i?.query ? `搜索: ${String(i.query).slice(0, 30)}` : '' },
  read_file: { label: '读取文件', icon: <FileTextOutlined />, userHint: (i) => i?.filename ? `${i.filename}` : '' },
  inspect_data: { label: '分析数据结构', icon: <DatabaseOutlined />, userHint: (i) => i?.filename ? `${i.filename}` : '所有文件' },
  pandas_query: { label: '查询数据', icon: <BarChartOutlined />, userHint: (i) => i?.filename ? `${i.filename}` : '' },
  execute_python: { label: '计算分析', icon: <CodeOutlined />, userHint: () => '' },
  sqlite_query: { label: '查询数据', icon: <DatabaseOutlined />, userHint: () => '' },
  generate_chart: { label: '生成图表', icon: <BarChartOutlined />, userHint: (i) => i?.title ? `${i.title}` : '' },
  generate_report: { label: '生成报告', icon: <FileTextOutlined />, userHint: () => '' },
  save_memory: { label: '记住要点', icon: <FileTextOutlined />, userHint: () => '' },
  nl2sql: { label: '查询数据', icon: <DatabaseOutlined />, userHint: (i) => i?.question ? `${String(i.question).slice(0, 30)}` : '' },
  kb_reindex_file: { label: '更新文件', icon: <DatabaseOutlined />, userHint: (i) => i?.filename ? `${i.filename}` : '' },
  db_import_csv: { label: '导入数据', icon: <DatabaseOutlined />, userHint: (i) => i?.filename ? `${i.filename}` : '' },
  graph_search: { label: '搜索图谱', icon: <DatabaseOutlined />, userHint: (i) => i?.query ? `${String(i.query).slice(0, 30)}` : '' },
  graph_traverse: { label: '遍历关系', icon: <DatabaseOutlined />, userHint: (i) => i?.entity ? `${i.entity}` : '' },
  graph_extract_from_text: { label: '抽取知识', icon: <FileTextOutlined />, userHint: () => '' },
}

function ToolResultBlock({ content, isError }: { content?: string; isError?: boolean }) {
  const [resultExpanded, setResultExpanded] = useState(false)
  if (!content) return null

  if (isError) {
    return (
      <div style={{ padding: '2px 0 4px 17px', borderBottom: `1px solid ${colors.borderLight}` }}>
        <Text style={{ fontSize: 11, color: colors.warning }}>
          正在换一种方式尝试...
        </Text>
      </div>
    )
  }

  return (
    <div style={{ padding: '2px 0 4px 17px', borderBottom: `1px solid ${colors.borderLight}` }}>
      {!resultExpanded ? (
        <span
          onClick={() => setResultExpanded(true)}
          style={{ fontSize: 10, color: colors.textMuted, cursor: 'pointer', userSelect: 'none' }}
        >
          查看详情
        </span>
      ) : (
        <>
          <Text
            style={{
              fontSize: 11,
              whiteSpace: 'pre-wrap',
              display: 'block',
              maxHeight: 300,
              overflow: 'auto',
              color: colors.textMuted,
              fontFamily: "'SF Mono', SFMono-Regular, Menlo, Consolas, monospace",
              lineHeight: 1.5,
            }}
          >
            {content}
          </Text>
          <span
            onClick={() => setResultExpanded(false)}
            style={{ fontSize: 10, color: colors.primary, cursor: 'pointer', userSelect: 'none', marginTop: 2, display: 'inline-block' }}
          >
            收起
          </span>
        </>
      )}
    </div>
  )
}

export default function ThinkingBlock({
  thinkingText,
  toolEvents,
  defaultExpanded = false,
}: ThinkingBlockProps) {
  const [expanded, setExpanded] = useState(defaultExpanded)

  if (!thinkingText && toolEvents.length === 0) return null

  const toolUseCount = toolEvents.filter((e) => e.type === 'tool_use').length
  const toolResultCount = toolEvents.filter(
    (e) => e.type === 'tool_result'
  ).length
  const allDone = toolUseCount > 0 && toolUseCount === toolResultCount

  // 从工具结果中提取图表规格，始终在折叠块外渲染（不受展开/收起影响）
  const charts: string[] = []
  for (const e of toolEvents) {
    if (e.type === 'tool_result' && e.content) {
      const m = e.content.match(/```chart\n([\s\S]*?)```/)
      if (m) charts.push(m[1].trim())
    }
  }

  return (
    <>
    <div
      style={{
        borderRadius: 10,
        border: `1px solid ${colors.border}`,
        background: colors.bgSubtle,
        overflow: 'hidden',
      }}
    >
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
        {expanded ? (
          <DownOutlined style={{ fontSize: 10, color: colors.textMuted }} />
        ) : (
          <RightOutlined style={{ fontSize: 10, color: colors.textMuted }} />
        )}
        <ThunderboltOutlined
          style={{
            color: allDone ? colors.success : colors.warning,
            fontSize: 13,
          }}
        />
        <Text style={{ fontSize: 12, color: colors.textSecondary, fontWeight: 500 }}>
          {allDone ? '已完成' : '执行中'}
        </Text>
        {toolUseCount > 0 && (
          <Text style={{ fontSize: 11, color: colors.textMuted }}>
            · {toolUseCount} 次工具调用
          </Text>
        )}
      </div>
      {expanded && (
        <div
          style={{
            padding: '0 12px 10px',
            borderTop: `1px solid ${colors.border}`,
          }}
        >
          {thinkingText && (
            <div style={{ padding: '8px 0' }}>
              <Text
                style={{
                  fontSize: 12,
                  fontStyle: 'italic',
                  color: colors.textMuted,
                }}
              >
                {thinkingText}
              </Text>
            </div>
          )}
          {toolEvents.map((event, i) => {
            const name = event.name || 'unknown'
            const meta = toolMeta[name] || {
              label: name,
              icon: <CodeOutlined />,
            }

            if (event.type === 'tool_use') {
              const useId = event.id
              const hasResult = toolEvents
                .slice(i + 1)
                .some(
                  (e) =>
                    e.type === 'tool_result' &&
                    (useId ? e.id === useId : e.name === name)
                )
              const hint = meta.userHint?.(event.input as Record<string, unknown>) || ''
              return (
                <div
                  key={i}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: 6,
                    padding: '6px 0',
                    borderBottom: `1px solid ${colors.borderLight}`,
                  }}
                >
                  <span
                    style={{
                      fontSize: 12,
                      color: hasResult ? colors.success : colors.primary,
                    }}
                  >
                    {meta.icon}
                  </span>
                  <Text
                    style={{
                      fontSize: 12,
                      fontWeight: 500,
                      color: colors.textSecondary,
                    }}
                  >
                    {meta.label}
                  </Text>
                  {hint && (
                    <Text
                      style={{
                        fontSize: 11,
                        color: colors.textMuted,
                        marginLeft: 'auto',
                        maxWidth: '60%',
                      }}
                      ellipsis
                    >
                      {hint}
                    </Text>
                  )}
                </div>
              )
            }

            if (event.type === 'tool_result') {
              // 图表规格已在折叠块外单独渲染，这里跳过，避免重复
              if (event.content && /```chart\n[\s\S]*?```/.test(event.content)) {
                return null
              }
              return (
                <ToolResultBlock key={i} content={event.content} isError={event.is_error} />
              )
            }

            return null
          })}
        </div>
      )}
    </div>
    {charts.length > 0 && (
      <div style={{ marginTop: 10, display: 'flex', flexDirection: 'column', gap: 12 }}>
        {charts.map((c, i) => (
          <ChartMessage key={i} chartJson={c} />
        ))}
      </div>
    )}
    </>
  )
}
