import { useState, useEffect, useRef } from 'react'
import { Typography, Select, Button, Upload, Table, Tabs, Card, Statistic, Tag, Empty, message, Popconfirm, Spin, Progress, Input, Popover } from 'antd'
import { UploadOutlined, DeleteOutlined, FileTextOutlined, BarChartOutlined, DatabaseOutlined, NodeIndexOutlined, CheckCircleOutlined, LoadingOutlined, SyncOutlined, PlusOutlined } from '@ant-design/icons'
import { dataSpacesApi, DataSpace, FileInSpace } from '@/api/dataSpaces'
import api from '@/api/client'
import GraphViewer from '@/components/Graph/GraphViewer'

const { Text, Title } = Typography

interface Props {
  selectedSpaceId: string | undefined
  onSpaceChange: (id: string | undefined) => void
  onStartChat?: () => void
}

export default function DataManager({ selectedSpaceId, onSpaceChange }: Props) {
  const [spaces, setSpaces] = useState<DataSpace[]>([])
  const [files, setFiles] = useState<FileInSpace[]>([])
  const [selectedFileId, setSelectedFileId] = useState<string | undefined>()
  const [preview, setPreview] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [newSpaceName, setNewSpaceName] = useState('')
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [processingFiles, setProcessingFiles] = useState<Set<string>>(new Set())
  const pollTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => { loadSpaces() }, [])
  useEffect(() => { if (selectedSpaceId) { loadFiles(); setSelectedFileId(undefined); setPreview(null) } }, [selectedSpaceId])
  useEffect(() => { if (selectedFileId && selectedSpaceId) { loadPreview() } }, [selectedFileId])

  const loadSpaces = async () => { try { setSpaces((await dataSpacesApi.list()).data) } catch {} }
  const loadFiles = async () => {
    if (!selectedSpaceId) return
    try { setFiles((await dataSpacesApi.get(selectedSpaceId)).data.files || []) } catch {}
  }
  const loadPreview = async () => {
    if (!selectedSpaceId || !selectedFileId) return
    setLoading(true)
    try { setPreview((await api.get(`/data-spaces/${selectedSpaceId}/files/${selectedFileId}/preview?page=1&page_size=50`)).data) }
    catch { setPreview(null) }
    finally { setLoading(false) }
  }

  const handleUpload = async (file: File) => {
    if (!selectedSpaceId) { message.warning('请先选择数据空间'); return false }

    // 文件大小检查 (100MB)
    if (file.size > 100 * 1024 * 1024) {
      message.error(`文件 ${file.name} 超过 100MB 限制`)
      return false
    }

    setUploading(true)
    setUploadProgress(0)
    const formData = new FormData()
    formData.append('files', file)

    try {
      // 模拟上传进度（实际进度需要 XMLHttpRequest）
      const progressInterval = setInterval(() => {
        setUploadProgress(prev => Math.min(prev + 15, 90))
      }, 300)

      await dataSpacesApi.uploadFiles(selectedSpaceId, formData)
      clearInterval(progressInterval)
      setUploadProgress(100)

      message.success(`${file.name} 上传成功`)

      // 标记为处理中，开始轮询状态
      setProcessingFiles(prev => new Set([...prev, file.name]))
      loadFiles()

      // 3秒后检查处理状态
      setTimeout(() => {
        checkProcessingStatus()
      }, 3000)
    } catch (err: any) {
      const detail = err?.response?.data?.detail || '上传失败，请检查文件格式和大小'
      message.error(detail)
    } finally {
      setTimeout(() => {
        setUploading(false)
        setUploadProgress(0)
      }, 1000)
    }
    return false
  }

  const checkProcessingStatus = async () => {
    if (!selectedSpaceId || processingFiles.size === 0) return
    try {
      const res = await dataSpacesApi.get(selectedSpaceId)
      const currentFiles = res.data.files || []
      setFiles(currentFiles)

      // 检查是否所有文件都有 profile 了
      const stillProcessing = new Set<string>()
      for (const name of processingFiles) {
        const f = currentFiles.find((cf: FileInSpace) => cf.filename === name)
        if (f) {
          try {
            const profileRes = await api.get(`/data-spaces/${selectedSpaceId}/files/${f.file_id}/profile`)
            if (profileRes.data?.status === 'processing' || profileRes.data?.status === 'pending') {
              stillProcessing.add(name)
            }
          } catch {
            stillProcessing.add(name)
          }
        }
      }

      setProcessingFiles(stillProcessing)
      if (stillProcessing.size > 0) {
        // 继续轮询
        pollTimerRef.current = setTimeout(checkProcessingStatus, 5000)
      } else {
        message.success('所有文件处理完成，数据已就绪')
      }
    } catch {}
  }

  // 清理轮询
  useEffect(() => {
    return () => { if (pollTimerRef.current) clearTimeout(pollTimerRef.current) }
  }, [])

  const handleDeleteFile = async (fileId: string) => {
    if (!selectedSpaceId) return
    try {
      await dataSpacesApi.removeFile(selectedSpaceId, fileId)
      message.success('已移除')
      loadFiles()
      if (fileId === selectedFileId) { setSelectedFileId(undefined); setPreview(null) }
    } catch { message.error('移除失败') }
  }

  const handleCreateSpace = async () => {
    if (!newSpaceName.trim()) return
    setCreating(true)
    try {
      const res = await dataSpacesApi.create({ name: newSpaceName.trim() })
      onSpaceChange(res.data.id)
      setNewSpaceName('')
      loadSpaces()
      message.success('分析项目已创建')
    } catch { message.error('创建失败') }
    finally { setCreating(false) }
  }

  // 空间概览数据
  const totalRows = files.reduce((sum, f) => sum + (f.file_size || 0), 0)
  const fileTypes = files.reduce((acc, f) => { acc[f.file_type] = (acc[f.file_type] || 0) + 1; return acc }, {} as Record<string, number>)

  if (!selectedSpaceId) {
    return (
      <div style={{ height: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f8fafc' }}>
        <Card style={{ width: 420, textAlign: 'center' }}>
          <DatabaseOutlined style={{ fontSize: 40, color: '#94a3b8', marginBottom: 16 }} />
          <Title level={5}>创建或选择分析项目</Title>
          <Text style={{ color: '#64748b', display: 'block', marginBottom: 16 }}>每个项目对应一组相关数据，比如"销售分析"、"客户调研"等</Text>
          <Select
            value={selectedSpaceId}
            onChange={onSpaceChange}
            placeholder="选择已有项目"
            style={{ width: '100%', marginBottom: 12 }}
            options={spaces.map(s => ({ label: `${s.name} (${s.file_count}文件)`, value: s.id }))}
          />
          <div style={{ display: 'flex', gap: 8 }}>
            <input
              placeholder="或输入名称创建新项目"
              value={newSpaceName}
              onChange={e => setNewSpaceName(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && handleCreateSpace()}
              style={{ flex: 1, padding: '6px 12px', border: '1px solid #e2e8f0', borderRadius: 8, outline: 'none' }}
            />
            <Button type="primary" onClick={handleCreateSpace} loading={creating}>创建</Button>
          </div>
        </Card>
      </div>
    )
  }

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', background: '#f8fafc' }}>
      {/* Header */}
      <div style={{ padding: '12px 20px', borderBottom: '1px solid #e2e8f0', background: '#fff', display: 'flex', alignItems: 'center', gap: 12 }}>
        <Select
          value={selectedSpaceId}
          onChange={onSpaceChange}
          style={{ width: 200 }}
          options={spaces.map(s => ({ label: s.name, value: s.id }))}
          placeholder="选择数据空间"
        />
        <Popover
          trigger="click"
          placement="bottomLeft"
          content={
            <div style={{ display: 'flex', gap: 8, width: 240 }}>
              <Input
                placeholder="输入空间名称"
                value={newSpaceName}
                onChange={e => setNewSpaceName(e.target.value)}
                onPressEnter={handleCreateSpace}
                size="small"
              />
              <Button type="primary" size="small" onClick={handleCreateSpace} loading={creating}>创建</Button>
            </div>
          }
        >
          <Button icon={<PlusOutlined />} size="small" title="创建新空间" />
        </Popover>
        <Upload showUploadList={false} multiple beforeUpload={handleUpload} accept=".csv,.xlsx,.xls,.json,.jsonl,.txt,.md,.pdf,.docx,.py,.sql,.zip,.parquet,.feather,.sqlite,.db,.png,.jpg,.tsv">
          <Button icon={<UploadOutlined />} type="primary">上传文件</Button>
        </Upload>
        <div style={{ flex: 1 }} />
        <Tag color="green" icon={<CheckCircleOutlined />}>{files.length} 个文件</Tag>
      </div>

      {/* Main: left file list + right content */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', position: 'relative' }}>
        {/* Floating upload/processing overlay */}
        {(uploading || (processingFiles.size > 0 && !uploading)) && (
          <div style={{
            position: 'absolute',
            top: 12,
            left: '50%',
            transform: 'translateX(-50%)',
            zIndex: 10,
            minWidth: 320,
            maxWidth: 420,
            background: '#fff',
            borderRadius: 10,
            boxShadow: '0 4px 24px rgba(0,0,0,0.10), 0 1px 4px rgba(0,0,0,0.06)',
            padding: '12px 16px',
            animation: 'fadeSlideDown 0.25s ease-out',
          }}>
            {uploading ? (
              <>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                  <LoadingOutlined style={{ color: '#1677ff' }} />
                  <Text style={{ fontSize: 12, color: '#1677ff', fontWeight: 500 }}>正在上传文件...</Text>
                </div>
                <Progress percent={uploadProgress} size="small" strokeColor="#1677ff" showInfo={false} />
              </>
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <SyncOutlined spin style={{ color: '#1677ff' }} />
                <Text style={{ fontSize: 12, color: '#475569' }}>
                  {processingFiles.size} 个文件正在处理中（建立索引...）
                </Text>
              </div>
            )}
          </div>
        )}
        {/* Left: file list */}
        <div style={{ width: 240, borderRight: '1px solid #e2e8f0', background: '#fff', overflow: 'auto', flexShrink: 0 }}>
          <div style={{ padding: '12px 12px 8px', fontSize: 11, fontWeight: 600, color: '#94a3b8', textTransform: 'uppercase' }}>
            文件列表
          </div>
          {files.length === 0 ? (
            <div style={{ padding: 16, textAlign: 'center', color: '#94a3b8', fontSize: 12 }}>
              暂无文件，点击上方上传
            </div>
          ) : (
            files.map(f => (
              <div
                key={f.file_id}
                onClick={() => setSelectedFileId(f.file_id === selectedFileId ? undefined : f.file_id)}
                style={{
                  padding: '10px 12px',
                  cursor: 'pointer',
                  background: selectedFileId === f.file_id ? '#f1f5f9' : 'transparent',
                  borderLeft: selectedFileId === f.file_id ? '3px solid #4f46e5' : '3px solid transparent',
                  display: 'flex', alignItems: 'center', gap: 8,
                  transition: 'all 0.15s',
                }}
              >
                <FileTextOutlined style={{ color: processingFiles.has(f.filename) ? '#faad14' : '#64748b', fontSize: 13 }} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <Text ellipsis style={{ fontSize: 12, display: 'block' }}>{f.filename}</Text>
                  <Text style={{ fontSize: 10, color: '#94a3b8' }}>
                    {processingFiles.has(f.filename) ? (
                      <span style={{ color: '#faad14' }}><SyncOutlined spin style={{ marginRight: 3 }} />处理中...</span>
                    ) : (
                      <>{f.file_type} · {f.file_size > 1024*1024 ? `${(f.file_size/1024/1024).toFixed(1)}MB` : `${(f.file_size/1024).toFixed(0)}KB`}</>
                    )}
                  </Text>
                </div>
                <Popconfirm title="移除？" onConfirm={(e) => { e?.stopPropagation(); handleDeleteFile(f.file_id) }} okText="移除" cancelText="取消">
                  <Button type="text" size="small" danger icon={<DeleteOutlined />} onClick={e => e.stopPropagation()} style={{ opacity: 0.5 }} />
                </Popconfirm>
              </div>
            ))
          )}
        </div>

        {/* Right: overview or file detail */}
        <div style={{ flex: 1, overflow: 'auto', padding: 20 }}>
          {!selectedFileId ? (
            /* Space Overview */
            <div>
              <Title level={5} style={{ marginBottom: 16 }}>项目概览</Title>
              <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
                <Card size="small" style={{ minWidth: 120 }}><Statistic title="文件数" value={files.length} /></Card>
                <Card size="small" style={{ minWidth: 120 }}><Statistic title="总大小" value={`${(totalRows / 1024 / 1024).toFixed(1)} MB`} /></Card>
                <Card size="small" style={{ minWidth: 120 }}>
                  <Statistic title="文件类型" value={Object.keys(fileTypes).length} suffix="种" />
                </Card>
              </div>

              {Object.keys(fileTypes).length > 0 && (
                <Card size="small" title="文件类型分布" style={{ marginBottom: 16 }}>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    {Object.entries(fileTypes).map(([type, count]) => (
                      <Tag key={type} color="blue">{type}: {count}</Tag>
                    ))}
                  </div>
                </Card>
              )}

              <Card size="small" title="知识图谱" style={{ marginBottom: 16 }}>
                <div style={{ height: 250 }}>
                  <GraphViewer spaceId={selectedSpaceId} />
                </div>
              </Card>
            </div>
          ) : (
            /* File Detail */
            <div>
              <div style={{ marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
                <Button type="link" size="small" onClick={() => { setSelectedFileId(undefined); setPreview(null) }} style={{ padding: 0, fontSize: 12, color: '#64748b' }}>← 总览</Button>
                <span style={{ color: '#e2e8f0' }}>|</span>
                <FileTextOutlined style={{ color: '#4f46e5' }} />
                <Title level={5} style={{ margin: 0 }}>{files.find(f => f.file_id === selectedFileId)?.filename}</Title>
              </div>
              {(() => {
                const selectedFile = files.find(f => f.file_id === selectedFileId)
                const graphEligibleTypes = ['txt', 'md', 'pdf', 'docx', 'py', 'sql', 'html', 'xml', 'yaml', 'yml']
                const showGraphTab = selectedFile && graphEligibleTypes.includes(selectedFile.file_type?.toLowerCase())

                const tabItems = [
                {
                  key: 'preview',
                  label: <span><BarChartOutlined /> 预览</span>,
                  children: loading ? (
                    <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
                  ) : preview?.type === 'table' ? (
                    <Table
                      dataSource={preview.rows?.map((row: string[], i: number) => {
                        const obj: Record<string, string> = { _key: String(i) }
                        preview.columns?.forEach((col: any, j: number) => { obj[col.name] = row[j] })
                        return obj
                      })}
                      columns={preview.columns?.map((col: any) => ({ title: col.name, dataIndex: col.name, key: col.name, width: 120, ellipsis: true, render: (v: string) => <span style={{ fontSize: 12 }}>{v}</span> }))}
                      rowKey="_key" size="small" scroll={{ x: (preview.columns?.length || 1) * 120 }}
                      pagination={{ pageSize: 50, size: 'small' }}
                    />
                  ) : preview?.type === 'text' ? (
                    <pre style={{ padding: 16, fontSize: 12, background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, maxHeight: 400, overflow: 'auto' }}>{preview.content}</pre>
                  ) : (
                    <Empty description="不支持预览" />
                  ),
                },
                {
                  key: 'graph',
                  label: <span><NodeIndexOutlined /> 图谱</span>,
                  children: <div style={{ height: 300 }}><GraphViewer spaceId={selectedSpaceId} /></div>,
                },
              ].filter(item => item.key !== 'graph' || showGraphTab)

              return <Tabs defaultActiveKey="preview" size="small" items={tabItems} />
              })()}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
