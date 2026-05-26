import ChartRenderer from './ChartRenderer'

interface Props {
  chartJson: string
}

export default function ChartMessage({ chartJson }: Props) {
  try {
    const spec = JSON.parse(chartJson)
    return <ChartRenderer spec={spec} />
  } catch {
    return (
      <div style={{
        padding: '10px 14px',
        background: '#1e1e2e',
        borderRadius: 10,
        border: '1px solid #2e2e3e',
        color: '#5c5c72',
        fontSize: 12,
      }}>
        图表数据解析失败
      </div>
    )
  }
}
