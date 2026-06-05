import { useState } from 'react'
import { Typography, Button, Upload, Input, message } from 'antd'
import { CloudUploadOutlined, FileTextOutlined, CheckCircleOutlined, BarChartOutlined, TeamOutlined, WalletOutlined, LineChartOutlined } from '@ant-design/icons'
import { dataSpacesApi } from '@/api/dataSpaces'
import { uploadErrorMessage } from '@/utils/uploadError'
import { colors, radius, shadow } from '@/styles/tokens'
import Logo from '@/components/Layout/Logo'

const { Title, Text } = Typography

interface Props {
  onComplete: (spaceId: string) => void
}

const TEMPLATES = [
  { label: '销售分析', icon: <BarChartOutlined /> },
  { label: '客户数据', icon: <TeamOutlined /> },
  { label: '财务报表', icon: <WalletOutlined /> },
  { label: '运营监控', icon: <LineChartOutlined /> },
]

export default function Onboarding({ onComplete }: Props) {
  const [step, setStep] = useState(0)
  const [spaceName, setSpaceName] = useState('')
  const [spaceId, setSpaceId] = useState('')
  const [creating, setCreating] = useState(false)
  const [uploadedFiles, setUploadedFiles] = useState<string[]>([])

  const handleCreateSpace = async () => {
    if (!spaceName.trim()) { message.warning('请输入项目名称'); return }
    setCreating(true)
    try {
      const res = await dataSpacesApi.create({ name: spaceName.trim() })
      setSpaceId(res.data.id)
      setStep(1)
    } catch {
      message.error('创建失败')
    } finally {
      setCreating(false)
    }
  }

  const handleUpload = async (file: File) => {
    if (!spaceId) return false
    if (file.size > 200 * 1024 * 1024) {
      message.error(`${file.name} 超过 200MB 限制`)
      return false
    }
    const formData = new FormData()
    formData.append('files', file)
    try {
      await dataSpacesApi.uploadFiles(spaceId, formData)
      setUploadedFiles(prev => [...prev, file.name])
    } catch (err: any) {
      message.error(uploadErrorMessage(err, file.name))
    }
    return false
  }

  return (
    <div className="auth-page" style={{ padding: 32 }}>
      <div style={{
        maxWidth: 480, width: '100%', borderRadius: radius.xl,
        background: colors.surface, boxShadow: shadow.lg, padding: '40px 36px',
        border: `1px solid ${colors.border}`,
      }}>
        {/* Header */}
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <div style={{ display: 'flex', justifyContent: 'center', marginBottom: 14 }}>
            <Logo size={36} withText={false} />
          </div>
          <Title level={4} style={{ marginBottom: 4 }}>
            {step === 0 ? '创建你的数据空间' : '上传数据文件'}
          </Title>
          <Text style={{ color: colors.textMuted, fontSize: 13 }}>
            {step === 0 ? '给你的数据分析起个名字，方便管理' : '上传后即可开始和 AI 对话分析'}
          </Text>
        </div>

        {/* Step indicator */}
        <div style={{ display: 'flex', justifyContent: 'center', gap: 8, marginBottom: 28 }}>
          {[0, 1].map(i => (
            <div key={i} style={{
              width: i <= step ? 32 : 20, height: 4, borderRadius: 2,
              background: i <= step ? colors.primary : colors.border,
              transition: 'all 0.3s',
            }} />
          ))}
        </div>

        {step === 0 && (
          <div>
            {/* Template buttons */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 10, marginBottom: 20 }}>
              {TEMPLATES.map(t => (
                <div
                  key={t.label}
                  onClick={() => setSpaceName(t.label)}
                  style={{
                    padding: '12px 14px', borderRadius: radius.md,
                    border: `1px solid ${spaceName === t.label ? colors.primary : colors.border}`,
                    background: spaceName === t.label ? colors.primaryLight : colors.surface,
                    cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 10,
                    transition: 'all 0.15s',
                  }}
                >
                  <span style={{ fontSize: 16, color: spaceName === t.label ? colors.primary : colors.textMuted }}>{t.icon}</span>
                  <span style={{ fontSize: 13, color: colors.textPrimary }}>{t.label}</span>
                </div>
              ))}
            </div>

            <Input
              size="large"
              placeholder="或输入自定义名称..."
              value={spaceName}
              onChange={e => setSpaceName(e.target.value)}
              onPressEnter={handleCreateSpace}
              style={{ marginBottom: 16, borderRadius: radius.md }}
            />
            <Button
              type="primary" block size="large"
              onClick={handleCreateSpace} loading={creating}
              style={{ borderRadius: radius.md, height: 44 }}
            >
              创建数据空间
            </Button>
          </div>
        )}

        {step === 1 && (
          <div>
            <Upload.Dragger
              multiple
              showUploadList={false}
              beforeUpload={handleUpload}
              accept=".csv,.tsv,.xlsx,.xls,.json,.jsonl,.txt,.md,.pdf,.docx,.py,.sql,.zip,.parquet,.feather,.sqlite,.db,.sqlite3,.png,.jpg,.jpeg,.gif,.bmp,.webp,.html,.xml,.yaml,.yml,.log,.r,.ipynb,.dta,.sav,.sas7bdat"
              style={{ marginBottom: 16, borderRadius: radius.lg, border: `1px dashed ${colors.border}` }}
            >
              <p style={{ fontSize: 28, color: colors.primary, marginBottom: 6 }}>
                <CloudUploadOutlined />
              </p>
              <p style={{ fontSize: 13, color: colors.textSecondary, margin: 0 }}>点击或拖拽文件到这里</p>
              <p style={{ fontSize: 11, color: colors.textMuted, margin: '4px 0 0' }}>支持 CSV、Excel、PDF、Word、JSON 等格式</p>
            </Upload.Dragger>

            {/* Uploaded file list */}
            {uploadedFiles.length > 0 && (
              <div style={{ marginBottom: 16, maxHeight: 120, overflow: 'auto' }}>
                {uploadedFiles.map(name => (
                  <div key={name} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 0', borderBottom: `1px solid ${colors.borderLight}` }}>
                    <FileTextOutlined style={{ color: colors.primary, fontSize: 12 }} />
                    <Text style={{ fontSize: 12, flex: 1 }} ellipsis>{name}</Text>
                    <CheckCircleOutlined style={{ color: colors.success, fontSize: 12 }} />
                  </div>
                ))}
              </div>
            )}

            <Button
              type="primary" block size="large"
              onClick={() => onComplete(spaceId)}
              style={{ borderRadius: radius.md, height: 44 }}
            >
              {uploadedFiles.length > 0 ? `开始分析（${uploadedFiles.length} 个文件）` : '跳过，稍后上传'}
            </Button>
          </div>
        )}
      </div>
    </div>
  )
}