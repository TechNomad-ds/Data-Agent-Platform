import { useState, useEffect } from 'react'
import ReactECharts from 'echarts-for-react'
import { Spin, Empty, Tag } from 'antd'
import { graphApi, GraphExport } from '@/api/graph'

interface Props {
  spaceId: string | undefined
}

export default function GraphViewer({ spaceId }: Props) {
  const [data, setData] = useState<GraphExport | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (spaceId) loadGraph()
    else setData(null)
  }, [spaceId])

  const loadGraph = async () => {
    if (!spaceId) return
    setLoading(true)
    try {
      const res = await graphApi.getExport(spaceId)
      setData(res.data)
    } catch {
      setData(null)
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return <div style={{ textAlign: 'center', paddingTop: 60 }}><Spin /><div style={{ marginTop: 8, color: '#94a3b8', fontSize: 13 }}>加载图谱...</div></div>
  }

  if (!data || data.nodes.length === 0) {
    return <Empty description="暂无知识图谱数据" style={{ paddingTop: 60 }} image={Empty.PRESENTED_IMAGE_SIMPLE} />
  }

  const categories = [...new Set(data.nodes.map(n => n.category))].map(c => ({ name: c }))

  const option = {
    tooltip: {
      trigger: 'item',
      formatter: (params: any) => {
        if (params.dataType === 'node') {
          return `<b>${params.data.name}</b><br/>类型: ${params.data.category}<br/>关系数: ${params.data.symbolSize}`
        }
        if (params.dataType === 'edge') {
          return `${params.data.source} → ${params.data.target}<br/>关系: ${params.data.name}`
        }
        return ''
      },
    },
    legend: {
      data: categories.map(c => c.name),
      orient: 'vertical',
      right: 10,
      top: 20,
      textStyle: { fontSize: 11 },
    },
    series: [{
      type: 'graph',
      layout: 'force',
      data: data.nodes.map((n) => ({
        ...n,
        category: categories.findIndex(c => c.name === n.category),
        label: { show: n.symbolSize > 15, fontSize: 10 },
      })),
      edges: data.edges,
      categories,
      roam: true,
      draggable: true,
      force: {
        repulsion: 200,
        edgeLength: [80, 200],
        gravity: 0.1,
      },
      emphasis: {
        focus: 'adjacency',
        lineStyle: { width: 3 },
      },
      lineStyle: {
        color: 'source',
        curveness: 0.1,
        opacity: 0.6,
      },
      edgeLabel: {
        show: true,
        formatter: (params: any) => params.data.name,
        fontSize: 9,
        color: '#8c8c8c',
      },
    }],
  }

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ padding: '8px 12px', borderBottom: '1px solid #f0f0f0', display: 'flex', alignItems: 'center', gap: 8 }}>
        <Tag color="purple">{data.stats.nodes} 节点</Tag>
        <Tag color="blue">{data.stats.edges} 关系</Tag>
        <Tag>{data.stats.connected_components} 连通分量</Tag>
      </div>
      <div style={{ flex: 1, minHeight: 300 }}>
        <ReactECharts
          option={option}
          style={{ height: '100%', width: '100%' }}
          opts={{ renderer: 'canvas' }}
        />
      </div>
    </div>
  )
}
