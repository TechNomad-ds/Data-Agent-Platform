import { useState } from 'react'
import { Typography, Button, Steps, Upload, Input, message, Card } from 'antd'
import { CloudUploadOutlined, MessageOutlined, RocketOutlined } from '@ant-design/icons'
import { dataSpacesApi } from '@/api/dataSpaces'

const { Title, Text, Paragraph } = Typography

interface Props {
  onComplete: (spaceId: string) => void
}

export default function Onboarding({ onComplete }: Props) {
  const [step, setStep] = useState(0)
  const [spaceName, setSpaceName] = useState('')
  const [spaceId, setSpaceId] = useState<string>('')
  const [creating, setCreating] = useState(false)
  const [uploadedCount, setUploadedCount] = useState(0)

  const handleCreateSpace = async () => {
    if (!spaceName.trim()) { message.warning('请输入名称'); return }
    setCreating(true)
    try {
      const res = await dataSpacesApi.create({ name: spaceName.trim() })
      setSpaceId(res.data.id)
      setStep(2)
    } catch {
      message.error('创建失败')
    } finally {
      setCreating(false)
    }
  }

  const handleUpload = async (file: File) => {
    if (!spaceId) return false
    const formData = new FormData()
    formData.append('files', file)
    try {
      await dataSpacesApi.uploadFiles(spaceId, formData)
      setUploadedCount(prev => prev + 1)
      message.success(`${file.name} 已上传`)
    } catch {
      message.error('上传失败')
    }
    return false
  }

  return (
    <div style={{
      height: '100vh',
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      background: 'linear-gradient(135deg, #f8fafc 0%, #eef2ff 100%)',
      padding: 32,
    }}>
      <Card style={{ maxWidth: 560, width: '100%', borderRadius: 16, boxShadow: '0 4px 24px rgba(0,0,0,0.06)' }}>
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <div style={{
            width: 56, height: 56, borderRadius: 16, margin: '0 auto 16px',
            background: 'linear-gradient(135deg, #4f46e5, #7c3aed)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 24, color: '#fff', fontWeight: 700,
          }}>D</div>
          <Title level={3} style={{ marginBottom: 4 }}>欢迎使用 Data Agent</Title>
          <Text type="secondary">上传你的数据，AI 帮你分析和理解</Text>
        </div>

        <Steps
          current={step}
          size="small"
          style={{ marginBottom: 32 }}
          items={[
            { title: '了解' },
            { title: '创建项目' },
            { title: '上传数据' },
            { title: '开始分析' },
          ]}
        />

        {step === 0 && (
          <div style={{ textAlign: 'center' }}>
            <div style={{ display: 'flex', gap: 16, marginBottom: 24, justifyContent: 'center', flexWrap: 'wrap' }}>
              <FeatureCard icon={<CloudUploadOutlined />} title="上传数据" desc="支持 CSV、Excel、PDF、文本等 20+ 格式" />
              <FeatureCard icon={<RocketOutlined />} title="自动分析" desc="AI 自动理解数据结构、发现问题" />
              <FeatureCard icon={<MessageOutlined />} title="对话分析" desc="用自然语言提问，获得数据洞察" />
            </div>
            <Paragraph style={{ color: '#64748b', fontSize: 13, marginBottom: 24 }}>
              只需三步：创建一个分析项目 → 上传你的数据文件 → 开始和 AI 对话
            </Paragraph>
            <Button type="primary" size="large" onClick={() => setStep(1)}>
              开始使用
            </Button>
          </div>
        )}

        {step === 1 && (
          <div>
            <Title level={5}>创建你的第一个分析项目</Title>
            <Paragraph style={{ color: '#64748b', fontSize: 13 }}>
              一个项目对应一组相关的数据。比如"销售数据分析"、"客户调研"、"财务报表"等。
            </Paragraph>
            <Input
              size="large"
              placeholder="输入项目名称，如：销售数据分析"
              value={spaceName}
              onChange={e => setSpaceName(e.target.value)}
              onPressEnter={handleCreateSpace}
              style={{ marginBottom: 16 }}
            />
            <Button type="primary" block size="large" onClick={handleCreateSpace} loading={creating}>
              创建项目
            </Button>
          </div>
        )}

        {step === 2 && (
          <div>
            <Title level={5}>上传你的数据文件</Title>
            <Paragraph style={{ color: '#64748b', fontSize: 13 }}>
              支持 CSV、Excel、JSON、PDF、Word、文本文件，也可以直接上传 ZIP 压缩包。
            </Paragraph>
            <Upload.Dragger
              multiple
              showUploadList={false}
              beforeUpload={handleUpload}
              accept=".csv,.xlsx,.xls,.json,.jsonl,.txt,.md,.pdf,.docx,.py,.sql,.zip,.parquet,.feather,.sqlite,.db,.tsv"
              style={{ marginBottom: 16 }}
            >
              <p style={{ fontSize: 32, color: '#4f46e5', marginBottom: 8 }}>
                <CloudUploadOutlined />
              </p>
              <p style={{ fontSize: 14, color: '#475569' }}>点击或拖拽文件到这里上传</p>
              <p style={{ fontSize: 12, color: '#94a3b8' }}>支持 CSV、Excel、PDF、Word、JSON 等格式</p>
            </Upload.Dragger>
            {uploadedCount > 0 && (
              <Text style={{ display: 'block', textAlign: 'center', marginBottom: 12, color: '#10b981' }}>
                已上传 {uploadedCount} 个文件
              </Text>
            )}
            <Button
              type="primary"
              block
              size="large"
              onClick={() => setStep(3)}
              disabled={uploadedCount === 0}
            >
              {uploadedCount > 0 ? '继续' : '请先上传至少一个文件'}
            </Button>
            <Button type="link" block onClick={() => setStep(3)} style={{ marginTop: 4 }}>
              稍后再上传
            </Button>
          </div>
        )}

        {step === 3 && (
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 48, marginBottom: 16 }}>🎉</div>
            <Title level={4}>一切就绪！</Title>
            <Paragraph style={{ color: '#64748b' }}>
              {uploadedCount > 0
                ? `已上传 ${uploadedCount} 个文件，AI 正在处理中。你现在可以开始对话分析了。`
                : '项目已创建，你可以随时上传数据并开始分析。'}
            </Paragraph>
            <Button type="primary" size="large" onClick={() => onComplete(spaceId)}>
              开始对话分析
            </Button>
          </div>
        )}
      </Card>
    </div>
  )
}

function FeatureCard({ icon, title, desc }: { icon: React.ReactNode; title: string; desc: string }) {
  return (
    <div style={{ width: 140, padding: 12, borderRadius: 10, background: '#f8fafc', textAlign: 'center' }}>
      <div style={{ fontSize: 20, color: '#4f46e5', marginBottom: 6 }}>{icon}</div>
      <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 2 }}>{title}</div>
      <div style={{ fontSize: 11, color: '#94a3b8' }}>{desc}</div>
    </div>
  )
}
