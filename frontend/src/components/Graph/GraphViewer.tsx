import { useState, useEffect, useRef } from 'react'
import ReactECharts from 'echarts-for-react'
import { Spin, Tag, Button, Progress } from 'antd'
import { DeploymentUnitOutlined, SyncOutlined } from '@ant-design/icons'
import { graphApi, GraphExport } from '@/api/graph'

interface Props {
  spaceId: string | undefined
}

export default function GraphViewer({ spaceId }: Props) {
  const [data, setData] = useState<GraphExport | null>(null)
  const [loading, setLoading] = useState(false)
  const [building, setBuilding] = useState(false)
  const [buildProgress, setBuildProgress] = useState(0)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const [buildFailed, setBuildFailed] = useState(false)

  useEffect(() => {
    if (spaceId) loadGraph()
    else setData(null)
    return () => { if (pollRef.current) clearInterval(pollRef.current) }
  }, [spaceId])

  const loadGraph = async () => {
    if (!spaceId) return
    setLoading(true)
    try {
      const res = await graphApi.getExport(spaceId)
      setData(res.data)
      if (res.data.building) {
        setBuilding(true)
        startPolling()
      }
    } catch {
      setData(null)
    } finally {
      setLoading(false)
    }
  }

  const handleBuild = async () => {
    if (!spaceId) return
    setBuilding(true)
    setBuildProgress(10)
    try {
      const res = await graphApi.buildGraph(spaceId)
      if (res.data.status === 'ready') {
        setBuilding(false)
        loadGraph()
        return
      }
      startPolling()
    } catch {
      setBuilding(false)
    }
  }

  const startPolling = () => {
    if (pollRef.current) clearInterval(pollRef.current)
    let progress = 15
    let pollCount = 0
    pollRef.current = setInterval(async () => {
      if (!spaceId) return
      progress = Math.min(progress + 8, 90)
      pollCount++
      setBuildProgress(progress)
      try {
        const res = await graphApi.getExport(spaceId)
        if (!res.data.building) {
          if (pollRef.current) clearInterval(pollRef.current)
          if (res.data.nodes.length > 0) {
            setBuildProgress(100)
            setTimeout(() => {
              setBuilding(false)
              setData(res.data)
            }, 500)
          } else {
            setBuilding(false)
            setBuildFailed(true)
          }
        }
      } catch {
        if (pollCount > 10) {
          if (pollRef.current) clearInterval(pollRef.current)
          setBuilding(false)
          setBuildFailed(true)
        }
      }
    }, 3000)
  }

  if (loading) {
    return (
      <div style={{ textAlign: 'center', paddingTop: 60 }}>
        <Spin />
        <div style={{ marginTop: 8, color: '#94a3b8', fontSize: 13 }}>加载图谱...</div>
      </div>
    )
  }

  if (building) {
    return (
      <div style={{ textAlign: 'center', paddingTop: 80, maxWidth: 360, margin: '0 auto' }}>
        <SyncOutlined spin style={{ fontSize: 36, color: '#4f46e5', marginBottom: 16 }} />
        <div style={{ fontSize: 15, fontWeight: 500, color: '#1e293b', marginBottom: 8 }}>
          正在构建知识图谱
        </div>
        <div style={{ fontSize: 12, color: '#64748b', marginBottom: 16 }}>
          正在从文档中提取实体和关系，这可能需要一些时间...
        </div>
        <Progress
          percent={buildProgress}
          strokeColor={{ from: '#4f46e5', to: '#7c3aed' }}
          size="small"
          showInfo={false}
          style={{ marginBottom: 8 }}
        />
        <div style={{ fontSize: 11, color: '#94a3b8' }}>
          {buildProgress < 30 ? '解析文档内容...' :
           buildProgress < 60 ? '提取实体关系...' :
           buildProgress < 90 ? '构建图谱结构...' : '即将完成...'}
        </div>
      </div>
    )
  }

  if (!data || data.nodes.length === 0) {
    return (
      <div style={{ textAlign: 'center', paddingTop: 80 }}>
        <DeploymentUnitOutlined style={{ fontSize: 40, color: '#cbd5e1', marginBottom: 16 }} />
        <div style={{ fontSize: 14, color: '#64748b', marginBottom: 8 }}>
          {buildFailed ? '未能从文档中提取到实体关系' : '暂无知识图谱数据'}
        </div>
        {buildFailed && (
          <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 16 }}>
            可能是文档内容过短或 LLM 服务暂时不可用
          </div>
        )}
        <Button
          type="primary"
          icon={<DeploymentUnitOutlined />}
          onClick={() => { setBuildFailed(false); handleBuild() }}
          style={{ borderRadius: 8 }}
        >
          {buildFailed ? '重新构建图谱' : '从文档构建图谱'}
        </Button>
        <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 8 }}>
          将从 .txt、.md、.pdf、.docx 等文件中自动提取实体关系
        </div>
      </div>
    )
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
