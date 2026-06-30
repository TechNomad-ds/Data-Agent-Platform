/**
 * 每渠道公共设置行：默认数据空间 + 默认模型
 */
import { useEffect, useState } from 'react'
import { Select, Space, Typography, message } from 'antd'
import { dataSpacesApi, type DataSpace } from '@/api/dataSpaces'
import { modelsApi, type ModelInfo } from '@/api/models'
import { channelsApi, type ChannelId, type ChannelSettings } from '@/api/channels'

const { Text } = Typography

interface Props {
  channelId: ChannelId
}

export default function ChannelSettingsRow({ channelId }: Props) {
  const [spaces, setSpaces] = useState<DataSpace[]>([])
  const [models, setModels] = useState<ModelInfo[]>([])
  const [settings, setSettings] = useState<ChannelSettings>({})
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    void Promise.all([
      dataSpacesApi.list().then((r) => setSpaces(r.data)),
      modelsApi.listAvailable().then((r) => setModels(r.data)),
      channelsApi.getSettings(channelId).then((r) => setSettings(r.data)),
    ]).catch(() => {/* non-critical, ignore */})
  }, [channelId])

  const save = async (patch: Partial<ChannelSettings>) => {
    const next = { ...settings, ...patch }
    setSettings(next)
    setSaving(true)
    try {
      await channelsApi.putSettings(channelId, next)
    } catch {
      message.error('设置保存失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Space direction="vertical" size={6} style={{ width: '100%' }}>
      <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ flex: 1, minWidth: 160 }}>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
            默认数据空间
          </Text>
          <Select
            size="small"
            style={{ width: '100%' }}
            placeholder="选择默认数据空间"
            value={settings.default_data_space_id ?? null}
            allowClear
            loading={saving}
            onChange={(val: string | null) => save({ default_data_space_id: val ?? undefined })}
            options={spaces.map((s) => ({ label: s.name, value: s.id }))}
          />
        </div>
        <div style={{ flex: 1, minWidth: 160 }}>
          <Text type="secondary" style={{ fontSize: 12, display: 'block', marginBottom: 4 }}>
            默认模型
          </Text>
          <Select
            size="small"
            style={{ width: '100%' }}
            placeholder="选择默认模型"
            value={settings.default_model ?? null}
            allowClear
            loading={saving}
            onChange={(val: string | null) => save({ default_model: val ?? undefined })}
            options={models.map((m) => ({ label: m.display_name, value: m.id }))}
          />
        </div>
      </div>
    </Space>
  )
}
