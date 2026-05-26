import { useState, useEffect } from 'react'
import { Typography, Select, Button, Upload, Table, Tabs, Card, Statistic, Tag, Empty, message, Popconfirm, Space, Spin } from 'antd'
import { UploadOutlined, DeleteOutlined, FileTextOutlined, BarChartOutlined, DatabaseOutlined } from '@ant-design/icons'
import { dataSpacesApi, DataSpace, FileInSpace } from '@/api/dataSpaces'
import api from '@/api/client'

const { Text, Title } = Typography

interface Props {
  selectedSpaceId: string | undefined
  onSpaceChange: (id: string | undefined) => void
}

export default function DataManager({ selectedSpaceId, onSpaceChange }: Props) {
  const [spaces, setSpaces] = useState<DataSpace[]>([])
  const [files, setFiles] = useState<FileInSpace[]>([])
  const [selectedFileId, setSelectedFileId] = useState<string | undefined>()
  const [preview, setPreview] = useState<any>(null)
  const [profile, setProfile] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [newSpaceName, setNewSpaceName] = useState('')

  useEffect(() => { loadSpaces() }, [])
  useEffect(() => { if (selectedSpaceId) loadFiles() }, [selectedSpaceId])
  useEffect(() => { if (selectedFileId && selectedSpaceId) { loadPreview(); loadProfile() } }, [selectedFileId])

  const loadSpaces = async () => { try { setSpaces((await dataSpacesApi.list()).data) } catch {} }
  const loadFiles = async () => {
    if (!selectedSpaceId) return
    try {
      const res = await dataSpacesApi.get(selectedSpaceId)
      setFiles(res.data.files || [])
    } catch {}
  }
  const loadPreview = async () => {
    if (!selectedSpaceId || !selectedFileId) return
    setLoading(true)
    try { setPreview((await api.get(`/data-spaces/${selectedSpaceId}/files/${selectedFileId}/preview?page=1&page_size=50`)).data) }
    catch { setPreview(null) }
    finally { setLoading(false) }
  }
  const loadProfile = async () => {
    if (!selectedSpaceId || !selectedFileId) return
    try { setProfile((await api.get(`/data-spaces/${selectedSpaceId}/files/${selectedFileId}/profile`)).data?.profile_data) }
    catch { setProfile(null) }
  }

  const handleUpload = async (file: File) => {
    if (!selectedSpaceId) { message.warning('请先选择数据空间'); return false }
    const formData = new FormData()
    formData.append('files', file)
    try {
      await dataSpacesApi.uploadFiles(selectedSpaceId, formData)
      message.success(`${file.name} 上传成功，正在预处理...`)
      loadFiles()
    } catch { message.error('上传失败') }
    return false
  }

  const handleDeleteFile = async (fileId: string) => {
    if (!selectedSpaceId) return
    try {
      await dataSpacesApi.removeFile(selectedSpaceId, fileId)
      message.success('已移除')
      loadFiles()
      if (fileId === selectedFileId) { setSelectedFileId(undefined); setPreview(null); setProfile(null) }
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
      message.success('数据空间已创建')
    } catch { message.error('创建失败') }
    finally { setCreating(false) }
  }

  return (
    <div style={{ height: '100vh', display: 'flex', flexDirection: 'column', background: '#f8fafc' }}>
      {/* Header */}
      <div style={{ padding: '16px 24px', borderBottom: '1px solid #e2e8f0', background: '#fff' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Title level={4} style={{ margin: 0 }}>数据管理</Title>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <Select
              value={selectedSpaceId}
              onChange={onSpaceChange}
              placeholder="选择数据空间"
              style={{ width: 200 }}
              options={spaces.map(s => ({ label: `${s.name} (${s.file_count}文件)`, value: s.id }))}
            />
            <Upload showUploadList={false} multiple beforeUpload={handleUpload} accept=".csv,.xlsx,.xls,.json,.jsonl,.txt,.md,.pdf,.docx,.py,.sql,.zip,.parquet,.feather,.sqlite,.db,.png,.jpg,.tsv">
              <Button icon={<UploadOutlined />} type="primary" disabled={!selectedSpaceId}>上传文件</Button>
            </Upload>
          </div>
        </div>
      </div>

      {!selectedSpaceId ? (
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <Card style={{ width: 400, textAlign: 'center' }}>
            <DatabaseOutlined style={{ fontSize: 40, color: '#94a3b8', marginBottom: 16 }} />
            <Title level={5}>创建或选择数据空间</Title>
            <Text style={{ color: '#64748b', display: 'block', marginBottom: 16 }}>数据空间用于组织你的数据文件</Text>
            <Space.Compact style={{ width: '100%' }}>
              <input
                placeholder="输入名称创建新空间"
                value={newSpaceName}
                onChange={e => setNewSpaceName(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && handleCreateSpace()}
                style={{ flex: 1, padding: '6px 12px', border: '1px solid #e2e8f0', borderRadius: '8px 0 0 8px', outline: 'none' }}
              />
              <Button type="primary" onClick={handleCreateSpace} loading={creating} style={{ borderRadius: '0 8px 8px 0' }}>创建</Button>
            </Space.Compact>
          </Card>
        </div>
      ) : (
        <div style={{ flex: 1, overflow: 'auto', padding: 24 }}>
          <Tabs defaultActiveKey="files" items={[
            {
              key: 'files',
              label: <span><FileTextOutlined /> 文件列表</span>,
              children: (
                <div>
                  {files.length === 0 ? (
                    <Empty description="暂无文件，点击上方上传" />
                  ) : (
                    <Table
                      dataSource={files}
                      rowKey="file_id"
                      size="small"
                      onRow={(record) => ({ onClick: () => setSelectedFileId(record.file_id), style: { cursor: 'pointer', background: selectedFileId === record.file_id ? '#f1f5f9' : undefined } })}
                      columns={[
                        { title: '文件名', dataIndex: 'filename', key: 'filename', render: (v: string) => <Text style={{ fontSize: 13 }}>{v}</Text> },
                        { title: '类型', dataIndex: 'file_type', key: 'type', width: 80, render: (v: string) => <Tag>{v}</Tag> },
                        { title: '大小', dataIndex: 'file_size', key: 'size', width: 100, render: (v: number) => <Text style={{ fontSize: 12 }}>{v > 1024*1024 ? `${(v/1024/1024).toFixed(1)}MB` : `${(v/1024).toFixed(0)}KB`}</Text> },
                        { title: '', key: 'action', width: 50, render: (_: any, record: FileInSpace) => (
                          <Popconfirm title="确定移除？" onConfirm={() => handleDeleteFile(record.file_id)} okText="移除" cancelText="取消">
                            <Button type="text" size="small" danger icon={<DeleteOutlined />} onClick={e => e.stopPropagation()} />
                          </Popconfirm>
                        )},
                      ]}
                      pagination={false}
                    />
                  )}
                </div>
              ),
            },
            {
              key: 'preview',
              label: <span><BarChartOutlined /> 数据预览</span>,
              children: (
                <div>
                  {!selectedFileId ? (
                    <Empty description="在文件列表中点击文件查看预览" />
                  ) : loading ? (
                    <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>
                  ) : preview?.type === 'table' ? (
                    <Table
                      dataSource={preview.rows?.map((row: string[], i: number) => {
                        const obj: Record<string, string> = { _key: String(i) }
                        preview.columns?.forEach((col: any, j: number) => { obj[col.name] = row[j] })
                        return obj
                      })}
                      columns={preview.columns?.map((col: any) => ({ title: col.name, dataIndex: col.name, key: col.name, width: 120, ellipsis: true, render: (v: string) => <span style={{ fontSize: 12 }}>{v}</span> }))}
                      rowKey="_key"
                      size="small"
                      scroll={{ x: (preview.columns?.length || 1) * 120 }}
                      pagination={{ pageSize: 50, size: 'small' }}
                    />
                  ) : preview?.type === 'database' ? (
                    <div>
                      <Text style={{ fontSize: 13, color: '#64748b', marginBottom: 8, display: 'block' }}>SQLite 数据库 · 表: {preview.tables?.join(', ')}</Text>
                      <Table
                        dataSource={preview.rows?.map((row: string[], i: number) => {
                          const obj: Record<string, string> = { _key: String(i) }
                          preview.columns?.forEach((col: any, j: number) => { obj[col.name] = row[j] })
                          return obj
                        })}
                        columns={preview.columns?.map((col: any) => ({ title: col.name, dataIndex: col.name, key: col.name, width: 120, ellipsis: true }))}
                        rowKey="_key" size="small" scroll={{ x: (preview.columns?.length || 1) * 120 }}
                      />
                    </div>
                  ) : preview?.type === 'text' ? (
                    <pre style={{ padding: 16, fontSize: 12, background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, maxHeight: 500, overflow: 'auto' }}>{preview.content}</pre>
                  ) : (
                    <Empty description="不支持预览此文件类型" />
                  )}
                </div>
              ),
            },
            {
              key: 'quality',
              label: <span><DatabaseOutlined /> 数据质量</span>,
              children: (
                <div>
                  {!profile ? (
                    <Empty description="选择文件查看数据质量报告" />
                  ) : (
                    <div>
                      {profile.quality && (
                        <div style={{ display: 'flex', gap: 16, marginBottom: 16, flexWrap: 'wrap' }}>
                          <Card size="small"><Statistic title="总行数" value={profile.row_count || 0} /></Card>
                          <Card size="small"><Statistic title="完整行" value={`${profile.quality.complete_pct || 0}%`} /></Card>
                          <Card size="small"><Statistic title="重复行" value={`${profile.quality.duplicate_pct || 0}%`} valueStyle={{ color: (profile.quality.duplicate_pct || 0) > 5 ? '#ef4444' : '#10b981' }} /></Card>
                        </div>
                      )}
                      {profile.quality?.outlier_columns?.length > 0 && (
                        <Card size="small" title="异常值检测" style={{ marginBottom: 16 }}>
                          {profile.quality.outlier_columns.map((o: any) => (
                            <div key={o.column} style={{ fontSize: 13, marginBottom: 4 }}>
                              <Tag color="orange">{o.column}</Tag> {o.outlier_count} 个异常值 ({o.outlier_pct}%)
                            </div>
                          ))}
                        </Card>
                      )}
                      {profile.quality?.type_suggestions?.length > 0 && (
                        <Card size="small" title="类型建议">
                          {profile.quality.type_suggestions.map((s: any) => (
                            <div key={s.column} style={{ fontSize: 13, marginBottom: 4 }}>
                              <Tag color="blue">{s.column}</Tag> {s.suggestion}
                            </div>
                          ))}
                        </Card>
                      )}
                      {profile.columns && (
                        <Card size="small" title="列详情" style={{ marginTop: 16 }}>
                          <Table
                            dataSource={profile.columns}
                            rowKey="name"
                            size="small"
                            pagination={false}
                            columns={[
                              { title: '列名', dataIndex: 'name', key: 'name' },
                              { title: '类型', dataIndex: 'dtype', key: 'dtype', width: 80 },
                              { title: '缺失率', dataIndex: 'null_pct', key: 'null', width: 80, render: (v: number) => <span style={{ color: v > 20 ? '#ef4444' : '#475569' }}>{v}%</span> },
                              { title: '唯一值', dataIndex: 'unique_count', key: 'unique', width: 80 },
                            ]}
                          />
                        </Card>
                      )}
                    </div>
                  )}
                </div>
              ),
            },
          ]} />
        </div>
      )}
    </div>
  )
}
