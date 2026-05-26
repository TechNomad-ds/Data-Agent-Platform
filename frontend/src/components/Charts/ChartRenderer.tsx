import ReactECharts from 'echarts-for-react'

interface ChartSpec {
  chart_type: string
  title?: string
  x_label?: string
  y_label?: string
  data: any
  options?: Record<string, any>
}

interface Props {
  spec: ChartSpec
}

export default function ChartRenderer({ spec }: Props) {
  const option = buildOption(spec)

  return (
    <div style={{
      background: '#ffffff',
      borderRadius: 10,
      padding: '16px',
      border: '1px solid #e2e8f0',
    }}>
      {spec.title && (
        <div style={{ fontSize: 13, fontWeight: 500, color: '#475569', marginBottom: 8 }}>
          {spec.title}
        </div>
      )}
      <ReactECharts
        option={option}
        style={{ height: 300 }}
        opts={{ renderer: 'canvas' }}
      />
    </div>
  )
}

function buildOption(spec: ChartSpec): any {
  const baseOption = {
    backgroundColor: 'transparent',
    textStyle: { color: '#475569' },
    grid: { left: '8%', right: '5%', top: '12%', bottom: '15%' },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#f1f5f9',
      borderColor: '#e2e8f0',
      textStyle: { color: '#1e293b' },
    },
  }

  switch (spec.chart_type) {
    case 'bar':
      return {
        ...baseOption,
        xAxis: {
          type: 'category',
          data: spec.data.x || spec.data.categories || [],
          name: spec.x_label,
          axisLine: { lineStyle: { color: '#e2e8f0' } },
          axisLabel: { color: '#64748b', rotate: spec.data.x?.length > 8 ? 30 : 0 },
        },
        yAxis: {
          type: 'value',
          name: spec.y_label,
          axisLine: { lineStyle: { color: '#e2e8f0' } },
          splitLine: { lineStyle: { color: '#e2e8f0' } },
        },
        series: [{
          type: 'bar',
          data: spec.data.y || spec.data.values || [],
          itemStyle: { color: '#6366f1', borderRadius: [4, 4, 0, 0] },
        }],
      }

    case 'line':
      return {
        ...baseOption,
        xAxis: {
          type: 'category',
          data: spec.data.x || [],
          name: spec.x_label,
          axisLine: { lineStyle: { color: '#e2e8f0' } },
          axisLabel: { color: '#64748b' },
        },
        yAxis: {
          type: 'value',
          name: spec.y_label,
          splitLine: { lineStyle: { color: '#e2e8f0' } },
        },
        series: [{
          type: 'line',
          data: spec.data.y || [],
          smooth: true,
          lineStyle: { color: '#4f46e5' },
          areaStyle: { color: 'rgba(129,140,248,0.1)' },
          itemStyle: { color: '#4f46e5' },
        }],
      }

    case 'pie':
      return {
        ...baseOption,
        series: [{
          type: 'pie',
          radius: ['35%', '65%'],
          data: (spec.data.items || []).map((item: any) => ({
            name: item.name,
            value: item.value,
          })),
          label: { color: '#475569' },
          itemStyle: { borderColor: '#ffffff', borderWidth: 2 },
        }],
      }

    case 'scatter':
      return {
        ...baseOption,
        xAxis: {
          type: 'value',
          name: spec.x_label,
          splitLine: { lineStyle: { color: '#e2e8f0' } },
        },
        yAxis: {
          type: 'value',
          name: spec.y_label,
          splitLine: { lineStyle: { color: '#e2e8f0' } },
        },
        series: [{
          type: 'scatter',
          data: spec.data.points || [],
          itemStyle: { color: '#6366f1', opacity: 0.7 },
        }],
      }

    case 'heatmap':
      return {
        ...baseOption,
        xAxis: {
          type: 'category',
          data: spec.data.x_labels || [],
          axisLabel: { color: '#64748b', rotate: 30, fontSize: 10 },
        },
        yAxis: {
          type: 'category',
          data: spec.data.y_labels || [],
          axisLabel: { color: '#64748b', fontSize: 10 },
        },
        visualMap: {
          min: spec.data.min ?? -1,
          max: spec.data.max ?? 1,
          calculable: true,
          orient: 'horizontal',
          left: 'center',
          bottom: 0,
          inRange: { color: ['#312e81', '#4338ca', '#6366f1', '#4f46e5', '#7c3aed'] },
          textStyle: { color: '#64748b' },
        },
        series: [{
          type: 'heatmap',
          data: spec.data.values || [],
          label: { show: true, color: '#1e293b', fontSize: 10 },
        }],
      }

    default:
      return {
        ...baseOption,
        xAxis: { type: 'category', data: spec.data.x || [] },
        yAxis: { type: 'value' },
        series: [{ type: 'bar', data: spec.data.y || [] }],
      }
  }
}
