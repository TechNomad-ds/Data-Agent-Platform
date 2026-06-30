import { useState, useMemo } from 'react'
import { Table, Tooltip, message as antMessage } from 'antd'
import { CopyOutlined, CheckOutlined, TableOutlined } from '@ant-design/icons'
import { copyText } from '@/utils/clipboard'
import { colors, radius, shadow } from '@/styles/tokens'

interface AnswerCardProps {
  raw: string
}

/** 轻量 CSV 解析：逗号分隔，首行列名 */
function parseCSV(raw: string): { headers: string[]; rows: string[][] } | null {
  const lines = raw
    .trim()
    .split('\n')
    .map((l) => l.trim())
    .filter((l) => l.length > 0)
  if (lines.length === 0) return null

  const headers = lines[0].split(',').map((h) => h.trim())
  const rows = lines.slice(1).map((line) => line.split(',').map((c) => c.trim()))
  return { headers, rows }
}

/** 判断是否为数值 */
function isNumeric(val: string): boolean {
  if (!val) return false
  return !isNaN(Number(val)) && val !== ''
}

/** 单值答案展示 */
function SingleValueDisplay({ value, label }: { value: string; label?: string }) {
  return (
    <div style={{ textAlign: 'center', padding: '20px 16px 12px' }}>
      <div
        style={{
          fontSize: 28,
          fontWeight: 600,
          color: colors.textPrimary,
          lineHeight: 1.3,
          wordBreak: 'break-word',
        }}
      >
        {value}
      </div>
      {label && (
        <div style={{ fontSize: 12, color: colors.textMuted, marginTop: 6 }}>
          {label}
        </div>
      )}
    </div>
  )
}

/** 表格答案展示 */
function TableDisplay({
  headers,
  rows,
}: {
  headers: string[]
  rows: string[][]
}) {
  const columns = useMemo(
    () =>
      headers.map((h, idx) => {
        // 判断该列是否全为数值
        const allNumeric = rows.length > 0 && rows.every((r) => !r[idx] || isNumeric(r[idx]))
        return {
          title: h,
          dataIndex: `col_${idx}`,
          key: `col_${idx}`,
          sorter: allNumeric
            ? (a: any, b: any) => Number(a[`col_${idx}`] || 0) - Number(b[`col_${idx}`] || 0)
            : (a: any, b: any) =>
                (a[`col_${idx}`] || '').localeCompare(b[`col_${idx}`] || ''),
          align: allNumeric ? ('right' as const) : ('left' as const),
          render: (text: string) => (
            <span style={{ fontVariantNumeric: allNumeric ? 'tabular-nums' : undefined }}>
              {text || '-'}
            </span>
          ),
        }
      }),
    [headers, rows],
  )

  const dataSource = useMemo(
    () =>
      rows.map((row, rowIdx) => {
        const record: any = { key: rowIdx }
        headers.forEach((_, colIdx) => {
          record[`col_${colIdx}`] = row[colIdx] || ''
        })
        return record
      }),
    [headers, rows],
  )

  return (
    <Table
      columns={columns}
      dataSource={dataSource}
      size="small"
      pagination={rows.length > 10 ? { pageSize: 10, size: 'small' } : false}
      scroll={{ x: 'max-content' }}
      style={{ marginTop: 8 }}
      rowClassName={(_, index) => (index % 2 === 0 ? 'answer-row-even' : 'answer-row-odd')}
    />
  )
}

export default function AnswerCard({ raw }: AnswerCardProps) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    if (await copyText(raw)) {
      setCopied(true)
      antMessage.success('已复制')
      setTimeout(() => setCopied(false), 1800)
    } else {
      antMessage.error('复制失败')
    }
  }

  const parsed = useMemo(() => parseCSV(raw), [raw])

  // 判断展示模式
  const isSingleValue = parsed && parsed.rows.length === 1 && parsed.headers.length === 1

  return (
    <div
      style={{
        background: colors.bg,
        border: `1px solid ${colors.border}`,
        borderLeft: `4px solid ${colors.success}`,
        borderRadius: radius.md,
        padding: '12px 16px',
        margin: '12px 0',
        boxShadow: shadow.sm,
      }}
    >
      {/* 标题栏 */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: isSingleValue ? 0 : 8,
          paddingBottom: isSingleValue ? 0 : 8,
          borderBottom: isSingleValue ? 'none' : `1px solid ${colors.borderLight}`,
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            fontSize: 13,
            color: colors.textSecondary,
            fontWeight: 500,
          }}
        >
          <TableOutlined style={{ color: colors.success }} />
          <span>查询结果</span>
          {parsed && parsed.rows.length > 1 && (
            <span style={{ fontSize: 11, color: colors.textMuted, fontWeight: 400 }}>
              共 {parsed.rows.length} 条记录
            </span>
          )}
        </div>
        <Tooltip title={copied ? '已复制' : '复制数据'} placement="top">
          <span
            onClick={handleCopy}
            style={{
              cursor: 'pointer',
              color: colors.textMuted,
              fontSize: 13,
              padding: 4,
              borderRadius: 4,
              display: 'inline-flex',
              alignItems: 'center',
              transition: 'color 0.12s',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.color = colors.textPrimary
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.color = colors.textMuted
            }}
          >
            {copied ? <CheckOutlined /> : <CopyOutlined />}
          </span>
        </Tooltip>
      </div>

      {/* 内容区 */}
      {!parsed ? (
        // 解析失败，降级为原始文本
        <pre
          style={{
            margin: 0,
            padding: 10,
            background: colors.bgSubtle,
            borderRadius: radius.sm,
            fontSize: 12,
            overflow: 'auto',
            maxHeight: 300,
            whiteSpace: 'pre-wrap',
            color: colors.textPrimary,
          }}
        >
          {raw}
        </pre>
      ) : isSingleValue ? (
        <SingleValueDisplay
          value={parsed.rows[0][0]}
          label={parsed.headers[0]}
        />
      ) : (
        <TableDisplay headers={parsed.headers} rows={parsed.rows} />
      )}
    </div>
  )
}
