import { useEffect, useState } from 'react'
import { Card, Row, Col, Button, Modal, Form, Input, Tag, Space, Typography, Empty, Popconfirm, message } from 'antd'
import { PlusOutlined, DatabaseOutlined, DeleteOutlined, FileOutlined, EditOutlined } from '@ant-design/icons'
import { dataSpacesApi, DataSpace } from '@/api/dataSpaces'
import SpaceDetail from './SpaceDetail'

const { Title, Text } = Typography

export default function DataSpaces() {
  const [spaces, setSpaces] = useState<DataSpace[]>([])
  const [modalOpen, setModalOpen] = useState(false)
  const [editingSpace, setEditingSpace] = useState<DataSpace | null>(null)
  const [selectedSpace, setSelectedSpace] = useState<DataSpace | null>(null)
  const [form] = Form.useForm()

  useEffect(() => {
    loadSpaces()
  }, [])

  const loadSpaces = async () => {
    try {
      const res = await dataSpacesApi.list()
      setSpaces(res.data)
    } catch {}
  }

  const handleCreate = async (values: { name: string; description?: string }) => {
    try {
      await dataSpacesApi.create(values)
      message.success('项目创建成功')
      setModalOpen(false)
      form.resetFields()
      loadSpaces()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '创建失败')
    }
  }

  const openCreateModal = () => {
    setEditingSpace(null)
    form.resetFields()
    setModalOpen(true)
  }

  const openEditModal = (space: DataSpace) => {
    setEditingSpace(space)
    form.setFieldsValue({ name: space.name, description: space.description || '' })
    setModalOpen(true)
  }

  const handleSubmit = async (values: { name: string; description?: string }) => {
    if (!editingSpace) {
      await handleCreate(values)
      return
    }

    try {
      await dataSpacesApi.update(editingSpace.id, values)
      message.success('项目已更新')
      setModalOpen(false)
      setEditingSpace(null)
      form.resetFields()
      loadSpaces()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '更新失败')
    }
  }

  const handleDelete = async (id: string) => {
    try {
      await dataSpacesApi.delete(id)
      message.success('已删除')
      loadSpaces()
    } catch {
      message.error('删除失败')
    }
  }

  if (selectedSpace) {
    return <SpaceDetail space={selectedSpace} onBack={() => { setSelectedSpace(null); loadSpaces() }} />
  }

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <div>
          <Title level={4} style={{ marginBottom: 4 }}>项目</Title>
          <Text type="secondary">将文件组织到项目中，Agent 将基于选定的项目进行分析</Text>
        </div>
        <Button type="primary" icon={<PlusOutlined />} onClick={openCreateModal}>
          创建项目
        </Button>
      </div>

      {spaces.length === 0 ? (
        <Card>
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="还没有项目"
          >
            <Button type="primary" onClick={openCreateModal}>
              创建第一个项目
            </Button>
          </Empty>
        </Card>
      ) : (
        <Row gutter={[16, 16]}>
          {spaces.map((space) => (
            <Col xs={24} sm={12} lg={8} key={space.id}>
              <Card
                hoverable
                onClick={() => setSelectedSpace(space)}
                actions={[
                  <EditOutlined key="edit" onClick={(e) => { e.stopPropagation(); openEditModal(space) }} />,
                  <Popconfirm title="确定删除？" onConfirm={(e) => { e?.stopPropagation(); handleDelete(space.id) }}>
                    <DeleteOutlined key="delete" onClick={(e) => e.stopPropagation()} />
                  </Popconfirm>,
                ]}
              >
                <Card.Meta
                  avatar={<DatabaseOutlined style={{ fontSize: 24, color: '#1677ff' }} />}
                  title={space.name}
                  description={space.description || '暂无描述'}
                />
                <div style={{ marginTop: 16 }}>
                  <Space>
                    <Tag icon={<FileOutlined />}>{space.file_count} 个文件</Tag>
                  </Space>
                </div>
              </Card>
            </Col>
          ))}
        </Row>
      )}

      <Modal
        title={editingSpace ? '编辑项目' : '创建项目'}
        open={modalOpen}
        onCancel={() => { setModalOpen(false); setEditingSpace(null); form.resetFields() }}
        onOk={() => form.submit()}
      >
        <Form form={form} layout="vertical" onFinish={handleSubmit}>
          <Form.Item name="name" label="名称" rules={[{ required: true, message: '请输入名称' }]}>
            <Input placeholder="例如：销售数据分析" />
          </Form.Item>
          <Form.Item name="description" label="描述">
            <Input.TextArea placeholder="简要描述这个项目的用途" rows={3} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
