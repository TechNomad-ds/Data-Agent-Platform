import { useState, useEffect } from 'react'
import { Select, Table, Typography, Spin, Empty, Tag, Statistic, Button, Tooltip, Upload, Popconfirm, message, Tabs } from 'antd'
import { FileTextOutlined, CloseOutlined, DatabaseOutlined, UploadOutlined, DeleteOutlined, SafetyOutlined } from '@ant-design/icons'
import { dataSpacesApi, FileInSpace } from '@/api/dataSpaces'
import api from '@/api/client'

const { Text } = Typography

interface Props {
  spaceId: string | undefined
  visible: boolean
  onClose: () => void
}

interface PreviewData {
  type: 'table' | 'text' | 'unsupported'
  columns?: { name: string; dtype: string }[]
  rows?: string[][]
  total_rows?: number
  content?: string
  total_lines?: number
  page?: number
  page_size?: number
  filename?: string
  message?: string
}

interface ProfileData {
  row_count?: number
  column_count?: number
  columns?: Array<{
    name: string
    dtype: string
    null_pct: number
    unique_count: number
    stats?: Record<string, number | null>
    top_values?: Record<string, number>
  }>
}

export default function DataPanel({ spaceId, visible, onClose }: Props) {
  const [files, setFiles] = useState<FileInSpace[]>([])
  const [selectedFileId, setSelectedFileId] = useState<string | undefined>()
  const [preview, setPreview] = useState<PreviewData | null>(null)
  const [profile, setProfile] = useState<ProfileData | null>(null)
  const [loading, setLoading] = useState(false)
  const [page, setPage] = useState(1)

  useEffect(() => {
    if (spaceId && visible) loadFiles()
    else { setFiles([]); setSelectedFileId(undefined); setPreview(null) }
  }, [spaceId, visible])

  useEffect(() => {
    if (selectedFileId && spaceId) {
      loadPreview(1)
      loadProfile()
    }
  }, [selectedFileId])

  const loadFiles = async () => {
    if (!spaceId) return
    try {
      const res = await dataSpacesApi.get(spaceId)
      setFiles(res.data.files || [])
      if (res.data.files?.length > 0 && !selectedFileId) {
        setSelectedFileId(res.data.files[0].file_id)
      }
    } catch {}
  }

  const loadPreview = async (p: number) => {
    if (!spaceId || !selectedFileId) return
    setLoading(true)
    try {
      const res = await api.get(`/data-spaces/${spaceId}/files/${selectedFileId}/preview?page=${p}&page_size=50`)
      setPreview(res.data)
      setPage(p)
    } catch {
      setPreview(null)
    } finally {
      setLoading(false)
    }
  }

  const loadProfile = async () => {
    if (!spaceId || !selectedFileId) return
    try {
      const res = await api.get(`/data-spaces/${spaceId}/files/${selectedFileId}/profile`)
      if (res.data.profile_data) setProfile(res.data.profile_data)
    } catch {
      setProfile(null)
    }
  }

  if (!visible) return null

  const handleDeleteFile = async (fileId: string) => {
    if (!spaceId) return
    try {
      await dataSpacesApi.removeFile(spaceId, fileId)
      message.success('文件已移除')
      loadFiles()
      if (fileId === selectedFileId) {
        setSelectedFileId(undefined)
        setPreview(null)
        setProfile(null)
      }
    } catch {
      message.error('移除失败')
    }
  }

  const handleUpload = async (file: File) => {
    if (!spaceId) return false
    const formData = new FormData()
    formData.append('files', file)
    try {
      await dataSpacesApi.uploadFiles(spaceId, formData)
      message.success(`${file.name} 上传成功`)
      loadFiles()
    } catch {
      message.error('上传失败')
    }
    return false
  }

  return (
    <div style={{
      width: 420,
      height: '100vh',
      borderLeft: '1px solid #e2e8f0',
      background: '#ffffff',
      display: 'flex',
      flexDirection: 'column',
      flexShrink: 0,
      overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{
        padding: '12px 16px',
        borderBottom: '1px solid #e2e8f0',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <DatabaseOutlined style={{ color: '#4f46e5' }} />
          <Text style={{ fontWeight: 600, fontSize: 14 }}>数据预览</Text>
        </div>
        <Button type="text" size="small" icon={<CloseOutlined />} onClick={onClose} />
      </div>

      {/* File selector + management */}
      <div style={{ padding: '12px 16px', borderBottom: '1px solid #f1f5f9' }}>
        <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
          <Select
            value={selectedFileId}
            onChange={setSelectedFileId}
            placeholder="选择文件预览"
            style={{ flex: 1 }}
            options={files.map(f => ({
              label: (
                <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <FileTextOutlined style={{ color: '#64748b' }} />
                  <span>{f.filename}</span>
                  <Tag style={{ marginLeft: 'auto', fontSize: 10 }}>{f.file_type}</Tag>
                </span>
              ),
              value: f.file_id,
            }))}
          />
          {selectedFileId && (
            <Popconfirm title="确定移除此文件？" onConfirm={() => handleDeleteFile(selectedFileId)} okText="移除" cancelText="取消">
              <Button size="small" icon={<DeleteOutlined />} danger style={{ height: 32 }} />
            </Popconfirm>
          )}
        </div>
        <Upload
          showUploadList={false}
          multiple
          beforeUpload={handleUpload}
          accept=".csv,.xlsx,.xls,.json,.txt,.md,.pdf,.docx,.py,.sql,.zip"
        >
          <Button size="small" icon={<UploadOutlined />} block style={{ fontSize: 12 }}>
            上传文件到此数据空间
          </Button>
        </Upload>
      </div>

      {/* Profile summary */}
      {profile && (
        <div style={{
          padding: '10px 16px',
          borderBottom: '1px solid #f1f5f9',
          display: 'flex',
          gap: 16,
        }}>
          {profile.row_count !== undefined && (
            <Statistic title="行数" value={profile.row_count} valueStyle={{ fontSize: 16 }} />
          )}
          {profile.column_count !== undefined && (
            <Statistic title="列数" value={profile.column_count} valueStyle={{ fontSize: 16 }} />
          )}
          {profile.columns && (
            <Statistic
              title="缺失率"
              value={Math.max(...profile.columns.map(c => c.null_pct || 0))}
              suffix="%"
              valueStyle={{ fontSize: 16, color: profile.columns.some(c => (c.null_pct || 0) > 20) ? '#ef4444' : '#10b981' }}
            />
          )}
        </div>
      )}

      {/* Tabbed content */}
      <Tabs
        defaultActiveKey="preview"
        size="small"
        style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}
        tabBarStyle={{ padding: '0 16px', marginBottom: 0 }}
        items={[
          {
            key: 'preview',
            label: '数据预览',
            children: (
              <div style={{ flex: 1, overflow: 'auto', padding: '0' }}>
                {loading ? (
                  <div style={{ textAlign: 'center', paddingTop: 60 }}>
                    <Spin />
                    <div style={{ marginTop: 8, color: '#94a3b8', fontSize: 13 }}>加载中...</div>
                  </div>
                ) : !preview ? (
                  <Empty description="选择文件查看数据" style={{ paddingTop: 60 }} />
                ) : preview.type === 'table' ? (
                  <div style={{ fontSize: 12 }}>
                    <Table
                      dataSource={preview.rows?.map((row, i) => {
                        const obj: Record<string, string> = { _key: String(i + (page - 1) * 50) }
                        preview.columns?.forEach((col, j) => { obj[col.name] = row[j] })
                        return obj
                      })}
                      columns={preview.columns?.map(col => ({
                        title: (
                          <Tooltip title={col.dtype}>
                            <span style={{ fontSize: 11 }}>{col.name}</span>
                          </Tooltip>
                        ),
                        dataIndex: col.name,
                        key: col.name,
                        width: 120,
                        ellipsis: true,
                        render: (v: string) => <span style={{ fontSize: 11 }}>{v}</span>,
                      }))}
                      rowKey="_key"
                      size="small"
                      scroll={{ x: (preview.columns?.length || 1) * 120, y: 400 }}
                      pagination={{
                        current: page,
                        pageSize: 50,
                        total: preview.total_rows,
                        size: 'small',
                        showSizeChanger: false,
                        onChange: (p) => loadPreview(p),
                      }}
                      style={{ fontSize: 11 }}
                    />
                  </div>
                ) : preview.type === 'text' ? (
                  <pre style={{
                    padding: 16,
                    fontSize: 12,
                    lineHeight: 1.6,
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-all',
                    color: '#475569',
                    margin: 0,
                  }}>
                    {preview.content}
                  </pre>
                ) : (
                  <Empty description={preview.message || '不支持预览'} style={{ paddingTop: 60 }} />
                )}
              </div>
            ),
          },
          {
            key: 'quality',
            label: <span><SafetyOutlined /> 数据质量</span>,
            children: (
              <div style={{ padding: 16, overflow: 'auto' }}>
                {profile?.columns ? (
                  <div>
                    <div style={{ marginBottom: 12 }}>
                      <Tag color="green">完整行: {((profile as any)?.quality?.complete_pct || 0).toFixed(1)}%</Tag>
                      <Tag color="orange">重复行: {((profile as any)?.quality?.duplicate_pct || 0).toFixed(1)}%</Tag>
                    </div>
                    <Table
                      dataSource={profile.columns.map(c => ({ ...c, key: c.name }))}
                      columns={[
                        { title: '列名', dataIndex: 'name', width: 100, ellipsis: true },
                        { title: '类型', dataIndex: 'dtype', width: 70 },
                        { title: '缺失%', dataIndex: 'null_pct', width: 60, render: (v: number) => <span style={{ color: v > 20 ? '#ef4444' : '#10b981' }}>{v}%</span> },
                        { title: '唯一值', dataIndex: 'unique_count', width: 60 },
                      ]}
                      size="small"
                      pagination={false}
                      scroll={{ y: 300 }}
                      style={{ fontSize: 11 }}
                    />
                  </div>
                ) : (
                  <Empty description="选择表格文件查看质量指标" image={Empty.PRESENTED_IMAGE_SIMPLE} />
                )}
              </div>
            ),
          },
        ]}
      />
    </div>
  )
}
