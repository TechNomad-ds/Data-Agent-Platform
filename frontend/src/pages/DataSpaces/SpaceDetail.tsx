import { useEffect, useState } from 'react'
import {
  Button, Table, Tag, Space, Typography, Upload, message, Popconfirm, Card, Progress,
} from 'antd'
import {
  ArrowLeftOutlined, InboxOutlined, DeleteOutlined, LoadingOutlined,
} from '@ant-design/icons'
import type { UploadProps } from 'antd'
import { dataSpacesApi, DataSpace, FileInSpace } from '@/api/dataSpaces'
import { useAuthStore } from '@/stores/authStore'

const { Title, Text } = Typography
const { Dragger } = Upload

interface Props {
  space: DataSpace
  onBack: () => void
}

export default function SpaceDetail({ space, onBack }: Props) {
  const [files, setFiles] = useState<FileInSpace[]>([])
  const [loading, setLoading] = useState(false)
  const [processing, setProcessing] = useState<{ ready: number; total: number } | null>(null)

  useEffect(() => {
    loadDetail()
  }, [space.id])

  const loadDetail = async () => {
    setLoading(true)
    try {
      const res = await dataSpacesApi.get(space.id)
      setFiles(res.data.files)
      // index_status removed
    } catch {
      message.error('加载数据空间详情失败')
    } finally {
      setLoading(false)
    }
  }

  const handleRemoveFile = async (fileId: string) => {
    try {
      await dataSpacesApi.removeFile(space.id, fileId)
      message.success('文件已移除')
      loadDetail()
    } catch {
      message.error('移除失败')
    }
  }

  // 轮询后台解析进度
  const pollProcessing = () => {
    let tries = 0
    const tick = async () => {
      tries += 1
      try {
        const { data } = await dataSpacesApi.processingStatus(space.id)
        setProcessing({ ready: data.ready, total: data.total_files })
        const settled = data.ready + data.error >= data.total_files
        if (data.all_ready || data.total_files === 0 || settled) {
          setProcessing(null)
          loadDetail()
          if (data.error > 0) {
            message.warning(`数据已就绪，但有 ${data.error} 个文件解析失败`)
          } else {
            message.success('数据已就绪')
          }
          return
        }
      } catch { /* 忽略单次失败 */ }
      if (tries < 150) setTimeout(tick, 2000)
      else setProcessing(null)
    }
    setTimeout(tick, 1500)
  }

  const uploadProps: UploadProps = {
    name: 'files',
    multiple: true,
    action: `/api/data-spaces/${space.id}/upload`,
    headers: { Authorization: `Bearer ${useAuthStore.getState().token}` },
    beforeUpload: () => {
      uploadProps.headers = { Authorization: `Bearer ${useAuthStore.getState().token}` }
      return true
    },
    onChange(info) {
      if (info.file.status === 'done') {
        message.success(`${info.file.name} 上传成功，正在后台解析...`)
        loadDetail()
        pollProcessing()
      } else if (info.file.status === 'error') {
        message.error(`${info.file.name} 上传失败`)
      }
    },
    showUploadList: false,
  }

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  }

  const columns = [
    { title: '文件名', dataIndex: 'filename', key: 'filename' },
    {
      title: '类型',
      dataIndex: 'file_type',
      key: 'file_type',
      width: 100,
      render: (t: string) => <Tag>{t}</Tag>,
    },
    {
      title: '大小',
      dataIndex: 'file_size',
      key: 'file_size',
      width: 120,
      render: (s: number) => formatSize(s),
    },
    {
      title: '添加时间',
      dataIndex: 'added_at',
      key: 'added_at',
      width: 180,
      render: (t: string) => new Date(t).toLocaleString('zh-CN'),
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
      render: (_: unknown, record: FileInSpace) => (
        <Popconfirm title="确定移除该文件？" onConfirm={() => handleRemoveFile(record.file_id)}>
          <Button type="text" danger icon={<DeleteOutlined />} size="small" />
        </Popconfirm>
      ),
    },
  ]

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <Space>
          <Button icon={<ArrowLeftOutlined />} onClick={onBack}>返回</Button>
          <Title level={4} style={{ margin: 0 }}>{space.name}</Title>
          <Tag color="success">就绪</Tag>
        </Space>
      </div>

      {space.description && (
        <Text type="secondary" style={{ display: 'block', marginBottom: 16 }}>
          {space.description}
        </Text>
      )}

      <Card style={{ marginBottom: 16 }}>
        <Dragger {...uploadProps}>
          <p className="ant-upload-drag-icon"><InboxOutlined /></p>
          <p className="ant-upload-text">点击或拖拽文件到此处上传</p>
          <p className="ant-upload-hint">
            支持 PDF、CSV、Excel、JSON、Markdown、Python、TXT 等格式，单文件最大 50MB
          </p>
        </Dragger>
      </Card>

      {processing && (
        <Card style={{ marginBottom: 16, background: '#fffbe6', borderColor: '#ffe58f' }} bodyStyle={{ padding: '12px 16px' }}>
          <Space style={{ width: '100%' }}>
            <LoadingOutlined style={{ color: '#d48806' }} />
            <Text style={{ color: '#d48806' }}>
              正在后台解析数据 {processing.ready}/{processing.total}，可继续操作
            </Text>
            <Progress
              percent={processing.total ? Math.round((processing.ready / processing.total) * 100) : 0}
              size="small" strokeColor="#d48806" showInfo={false}
              style={{ width: 160 }}
            />
          </Space>
        </Card>
      )}

      <Table
        columns={columns}
        dataSource={files}
        rowKey="file_id"
        loading={loading}
        pagination={false}
        locale={{ emptyText: '暂无文件，请上传' }}
      />
    </div>
  )
}
