import { useEffect, useState } from 'react'
import { Card, Table, Button, Upload, Space, Typography, Tag, message, Popconfirm } from 'antd'
import { InboxOutlined, DeleteOutlined, FileOutlined } from '@ant-design/icons'
import type { UploadProps } from 'antd'
import { filesApi, FileInfo } from '@/api/files'
import { useAuthStore } from '@/stores/authStore'

const { Title, Text } = Typography
const { Dragger } = Upload

export default function Files() {
  const [files, setFiles] = useState<FileInfo[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(false)
  const token = useAuthStore((s) => s.token)

  useEffect(() => {
    loadFiles()
  }, [page])

  const loadFiles = async () => {
    setLoading(true)
    try {
      const res = await filesApi.list(page, 20)
      setFiles(res.data.files)
      setTotal(res.data.total)
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await filesApi.delete(id)
      message.success('文件已删除')
      loadFiles()
    } catch {
      message.error('删除失败')
    }
  }

  const uploadProps: UploadProps = {
    name: 'files',
    multiple: true,
    action: '/api/files/upload',
    headers: { Authorization: `Bearer ${token}` },
    onChange(info) {
      if (info.file.status === 'done') {
        message.success(`${info.file.name} 上传成功`)
        loadFiles()
      } else if (info.file.status === 'error') {
        message.error(`${info.file.name} 上传失败`)
      }
    },
  }

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  }

  const typeColors: Record<string, string> = {
    pdf: 'red', csv: 'green', xlsx: 'green', json: 'orange',
    py: 'blue', md: 'purple', txt: 'default', docx: 'cyan', pptx: 'volcano', ppt: 'volcano',
  }

  const columns = [
    {
      title: '文件名',
      dataIndex: 'filename',
      key: 'filename',
      render: (name: string) => (
        <Space>
          <FileOutlined />
          <Text>{name}</Text>
        </Space>
      ),
    },
    {
      title: '类型',
      dataIndex: 'file_type',
      key: 'file_type',
      width: 100,
      render: (type: string) => <Tag color={typeColors[type] || 'default'}>{type.toUpperCase()}</Tag>,
    },
    {
      title: '大小',
      dataIndex: 'file_size',
      key: 'file_size',
      width: 100,
      render: (size: number) => formatSize(size),
    },
    {
      title: '状态',
      dataIndex: 'parse_status',
      key: 'parse_status',
      width: 100,
      render: (status: string) => {
        const map: Record<string, { color: string; text: string }> = {
          pending: { color: 'default', text: '待解析' },
          processing: { color: 'processing', text: '解析中' },
          done: { color: 'success', text: '已完成' },
          error: { color: 'error', text: '失败' },
        }
        const s = map[status] || { color: 'default', text: status }
        return <Tag color={s.color}>{s.text}</Tag>
      },
    },
    {
      title: '上传时间',
      dataIndex: 'created_at',
      key: 'created_at',
      width: 180,
      render: (t: string) => new Date(t).toLocaleString('zh-CN'),
    },
    {
      title: '操作',
      key: 'action',
      width: 80,
      render: (_: unknown, record: FileInfo) => (
        <Popconfirm title="确定删除？" onConfirm={() => handleDelete(record.id)}>
          <Button type="text" danger icon={<DeleteOutlined />} size="small" />
        </Popconfirm>
      ),
    },
  ]

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <Title level={4} style={{ marginBottom: 4 }}>文件管理</Title>
        <Text type="secondary">上传和管理你的数据文件</Text>
      </div>

      <Card style={{ marginBottom: 16 }}>
        <Dragger {...uploadProps}>
          <p className="ant-upload-drag-icon">
            <InboxOutlined />
          </p>
          <p className="ant-upload-text">点击或拖拽文件到此区域上传</p>
          <p className="ant-upload-hint">
            支持 PDF、CSV、Excel、JSON、Markdown、Python、TXT、ZIP 等格式，单文件最大 50MB。上传 ZIP 会自动解压
          </p>
        </Dragger>
      </Card>

      <Card>
        <Table
          columns={columns}
          dataSource={files}
          rowKey="id"
          loading={loading}
          pagination={{
            current: page,
            total,
            pageSize: 20,
            onChange: setPage,
            showTotal: (t) => `共 ${t} 个文件`,
          }}
        />
      </Card>
    </div>
  )
}
