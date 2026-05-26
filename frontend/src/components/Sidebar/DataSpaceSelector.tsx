import { useState } from 'react'
import { Select, Button, Modal, Input, Space, message } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import { DataSpace, dataSpacesApi } from '@/api/dataSpaces'

interface Props {
  spaces: DataSpace[]
  selectedSpaceId: string | undefined
  onSelect: (id: string | undefined) => void
  onRefresh: () => void
}

export default function DataSpaceSelector({ spaces, selectedSpaceId, onSelect, onRefresh }: Props) {
  const [createOpen, setCreateOpen] = useState(false)
  const [newName, setNewName] = useState('')
  const [newDesc, setNewDesc] = useState('')
  const [creating, setCreating] = useState(false)

  const handleCreate = async () => {
    if (!newName.trim()) return
    setCreating(true)
    try {
      const res = await dataSpacesApi.create({ name: newName.trim(), description: newDesc.trim() || undefined })
      onRefresh()
      onSelect(res.data.id)
      setCreateOpen(false)
      setNewName('')
      setNewDesc('')
      message.success('数据空间已创建')
    } catch {
      message.error('创建失败')
    } finally {
      setCreating(false)
    }
  }

  return (
    <>
      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <Select
          value={selectedSpaceId}
          onChange={onSelect}
          placeholder="选择数据空间"
          allowClear
          style={{ flex: 1 }}
          popupMatchSelectWidth={false}
          options={spaces.map(s => ({
            label: (
              <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ fontSize: 12, opacity: 0.5 }}>{s.file_count} 文件</span>
                <span>{s.name}</span>
              </span>
            ),
            value: s.id,
          }))}
        />
        <Button
          type="text"
          icon={<PlusOutlined />}
          onClick={() => setCreateOpen(true)}
          style={{ color: '#8888a0' }}
        />
      </div>

      <Modal
        title="新建数据空间"
        open={createOpen}
        onCancel={() => setCreateOpen(false)}
        onOk={handleCreate}
        confirmLoading={creating}
        okText="创建"
        cancelText="取消"
      >
        <Space direction="vertical" style={{ width: '100%' }}>
          <Input
            placeholder="数据空间名称"
            value={newName}
            onChange={e => setNewName(e.target.value)}
            onPressEnter={handleCreate}
          />
          <Input.TextArea
            placeholder="描述（可选）"
            value={newDesc}
            onChange={e => setNewDesc(e.target.value)}
            rows={2}
          />
        </Space>
      </Modal>
    </>
  )
}
