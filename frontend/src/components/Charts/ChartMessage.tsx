import { useState } from 'react'
import ChartRenderer from './ChartRenderer'

interface Props {
  chartJson: string
}

function ChartErrorFallback({ chartJson, error }: { chartJson: string; error: string }) {
  const [showRaw, setShowRaw] = useState(false)
  return (
    <div style={{
      padding: '12px 14px',
      background: '#fafafa',
      borderRadius: 10,
      border: '1px solid #e5e7eb',
      fontSize: 12,
    }}>
      <div style={{ color: '#6b7280', marginBottom: 6 }}>图表渲染失败: {error}</div>
      <span
        onClick={() => setShowRaw(!showRaw)}
        style={{ color: '#4f46e5', cursor: 'pointer', fontSize: 11 }}
      >
        {showRaw ? '收起' : '查看原始数据'}
      </span>
      {showRaw && (
        <pre style={{
          marginTop: 8, padding: 10, background: '#f3f4f6', borderRadius: 6,
          fontSize: 11, overflow: 'auto', maxHeight: 200, whiteSpace: 'pre-wrap',
        }}>
          {chartJson}
        </pre>
      )}
    </div>
  )
}

export default function ChartMessage({ chartJson }: Props) {
  try {
    const spec = JSON.parse(chartJson)
    if (!spec || !spec.chart_type) throw new Error('缺少 chart_type')
    return <ChartRenderer spec={spec} />
  } catch (e: any) {
    return <ChartErrorFallback chartJson={chartJson} error={e?.message || '解析失败'} />
  }
}
