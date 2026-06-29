import { useState, useEffect } from 'react'
import {
  Typography, Button, Upload, Table, Tag, message,
  Popconfirm, Spin, Progress, Input, Modal, Tooltip,
  Tabs,
} from 'antd'
import {
  DeleteOutlined, FileTextOutlined,
  DatabaseOutlined, LoadingOutlined,
  PlusOutlined, ExclamationCircleOutlined,
  CloudUploadOutlined, MessageOutlined, ArrowLeftOutlined,
  FolderOutlined, FileExcelOutlined, FilePdfOutlined,
  FileImageOutlined, CodeOutlined, SearchOutlined,
  ClockCircleOutlined, AppstoreOutlined, DownloadOutlined,
  InboxOutlined,
} from '@ant-design/icons'
import { dataSpacesApi, DataSpace, FileInSpace } from '@/api/dataSpaces'
import { uploadErrorMessage } from '@/utils/uploadError'
import { useIsMobile } from '@/hooks/useIsMobile'
import api from '@/api/client'
import { colors, shadow, gradient, fileTypePalette } from '@/styles/tokens'

const { Text, Title } = Typography

interface Props {
  selectedSpaceId: string | undefined
  onSpaceChange: (id: string | undefined) => void
  onStartChat?: () => void
}

const FILE_TYPE_CONFIG: Record<string, { color: string; icon: React.ReactNode }> = {
  csv: { color: '#3b82f6', icon: <FileTextOutlined /> },
  tsv: { color: '#3b82f6', icon: <FileTextOutlined /> },
  xlsx: { color: '#10b981', icon: <FileExcelOutlined /> },
  xls: { color: '#10b981', icon: <FileExcelOutlined /> },
  json: { color: '#f59e0b', icon: <CodeOutlined /> },
  jsonl: { color: '#f59e0b', icon: <CodeOutlined /> },
  pdf: { color: '#ef4444', icon: <FilePdfOutlined /> },
  docx: { color: '#3b82f6', icon: <FileTextOutlined /> },
  pptx: { color: '#f97316', icon: <FileTextOutlined /> },
  ppt: { color: '#f97316', icon: <FileTextOutlined /> },
  png: { color: '#8b5cf6', icon: <FileImageOutlined /> },
  jpg: { color: '#8b5cf6', icon: <FileImageOutlined /> },
  jpeg: { color: '#8b5cf6', icon: <FileImageOutlined /> },
  py: { color: '#10b981', icon: <CodeOutlined /> },
  sql: { color: '#f59e0b', icon: <CodeOutlined /> },
  md: { color: '#6366f1', icon: <FileTextOutlined /> },
  txt: { color: '#64748b', icon: <FileTextOutlined /> },
  parquet: { color: '#ec4899', icon: <DatabaseOutlined /> },
  sqlite: { color: '#0ea5e9', icon: <DatabaseOutlined /> },
  db: { color: '#0ea5e9', icon: <DatabaseOutlined /> },
}

function getFileConfig(type: string) {
  return FILE_TYPE_CONFIG[type] || { color: '#94a3b8', icon: <FileTextOutlined /> }
}

function formatSize(bytes: number): string {
  if (bytes > 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  if (bytes > 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${bytes} B`
}

function formatDate(dateStr: string): string {
  const d = new Date(dateStr)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  if (diff < 60000) return '刚刚'
  if (diff < 3600000) return `${Math.floor(diff / 60000)} 分钟前`
  if (diff < 86400000) return `${Math.floor(diff / 3600000)} 小时前`
  if (diff < 604800000) return `${Math.floor(diff / 86400000)} 天前`
  return d.toLocaleDateString('zh-CN')
}

function ImagePreview({ fileId, filename, sizeKb }: { fileId: string; filename: string; sizeKb: number }) {
  const [src, setSrc] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let revoke: string | null = null
    setLoading(true)
    api.get(`/files/${fileId}/download`, { responseType: 'blob' })
      .then(res => {
        const url = URL.createObjectURL(res.data)
        revoke = url
        setSrc(url)
      })
      .catch(() => setSrc(null))
      .finally(() => setLoading(false))
    return () => { if (revoke) URL.revokeObjectURL(revoke) }
  }, [fileId])

  return (
    <div style={{ textAlign: 'center', paddingTop: 20 }}>
      <div style={{ marginBottom: 12 }}>
        <Text style={{ fontSize: 14, fontWeight: 600 }}>{filename}</Text>
        <Tag style={{ marginLeft: 8 }}>{sizeKb} KB</Tag>
      </div>
      {loading ? (
        <Spin style={{ marginTop: 40 }} />
      ) : src ? (
        <img src={src} alt={filename} style={{ maxWidth: '100%', maxHeight: 400, borderRadius: 8, border: `1px solid ${colors.border}` }} />
      ) : (
        <Text type="secondary">图片加载失败</Text>
      )}
    </div>
  )
}

export default function DataManager({ selectedSpaceId, onSpaceChange, onStartChat }: Props) {
  const [spaces, setSpaces] = useState<DataSpace[]>([])
  const [files, setFiles] = useState<FileInSpace[]>([])
  const [selectedFileId, setSelectedFileId] = useState<string | undefined>()
  const [preview, setPreview] = useState<any>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const [creating, setCreating] = useState(false)
  const [newSpaceName, setNewSpaceName] = useState('')
  const [newSpaceDesc, setNewSpaceDesc] = useState('')
  const [createModalOpen, setCreateModalOpen] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [uploadProgress, setUploadProgress] = useState(0)
  const [processing, setProcessing] = useState<{ ready: number; total: number } | null>(null)
  const [searchText, setSearchText] = useState('')
  const [spacesLoading, setSpacesLoading] = useState(true)
  const isMobile = useIsMobile()

  useEffect(() => { loadSpaces() }, [])
  useEffect(() => {
    if (selectedSpaceId) {
      setFiles([])
      setSelectedFileId(undefined)
      setPreview(null)
      loadFiles()
    }
  }, [selectedSpaceId])
  useEffect(() => {
    if (selectedFileId && selectedSpaceId) loadPreview()
  }, [selectedFileId])

  const loadSpaces = async () => {
    setSpacesLoading(true)
    try { setSpaces((await dataSpacesApi.list()).data) }
    catch {}
    finally { setSpacesLoading(false) }
  }

  const loadFiles = async () => {
    if (!selectedSpaceId) return
    try {
      const res = await dataSpacesApi.get(selectedSpaceId)
      setFiles(res.data.files || [])
    } catch {}
  }

  const loadPreview = async () => {
    if (!selectedSpaceId || !selectedFileId) return
    setPreviewLoading(true)
    try {
      setPreview((await api.get(`/data-spaces/${selectedSpaceId}/files/${selectedFileId}/preview?page=1&page_size=50`)).data)
    } catch { setPreview(null) }
    finally { setPreviewLoading(false) }
  }

  const handleCreateSpace = async () => {
    if (!newSpaceName.trim()) return
    setCreating(true)
    try {
      const res = await dataSpacesApi.create({
        name: newSpaceName.trim(),
        description: newSpaceDesc.trim() || undefined,
      })
      onSpaceChange(res.data.id)
      setNewSpaceName('')
      setNewSpaceDesc('')
      setCreateModalOpen(false)
      loadSpaces()
      message.success('数据空间已创建')
    } catch { message.error('创建失败') }
    finally { setCreating(false) }
  }

  const handleUpload = async (file: File) => {
    if (!selectedSpaceId) { message.warning('请先选择数据空间'); return false }
    if (file.size > 200 * 1024 * 1024) {
      message.error(`文件 ${file.name} 超过 200MB 限制`)
      return false
    }
    setUploading(true)
    setUploadProgress(0)
    const formData = new FormData()
    formData.append('files', file)
    try {
      const progressInterval = setInterval(() => {
        setUploadProgress(prev => Math.min(prev + 15, 90))
      }, 300)
      await dataSpacesApi.uploadFiles(selectedSpaceId, formData)
      clearInterval(progressInterval)
      setUploadProgress(100)
      message.success(`${file.name} 上传成功，正在后台解析...`)
      loadFiles()
      loadSpaces()
      // 上传只是入库，真正的解析+向量索引在后台进行，轮询真实进度
      pollProcessing(selectedSpaceId)
    } catch (err: any) {
      message.error(uploadErrorMessage(err, file.name))
    } finally {
      setTimeout(() => { setUploading(false); setUploadProgress(0) }, 800)
    }
    return false
  }

  // 轮询后台处理进度，直到所有文件就绪（或失败）
  const pollProcessing = (spaceId: string) => {
    let tries = 0
    const tick = async () => {
      tries += 1
      try {
        const { data } = await dataSpacesApi.processingStatus(spaceId)
        if (spaceId !== selectedSpaceId) { setProcessing(null); return }
        setProcessing({ ready: data.ready, total: data.total_files })
        // 结束条件：全部就绪，或已无处理中文件（ready + error 覆盖全部）
        const settled = data.ready + data.error >= data.total_files
        if (data.all_ready || data.total_files === 0 || settled) {
          setProcessing(null)
          loadFiles()
          if (data.error > 0) {
            message.warning(`数据已就绪，但有 ${data.error} 个文件解析失败`)
          } else {
            message.success('数据已就绪，可以开始分析')
          }
          return
        }
      } catch { /* 忽略单次失败，继续轮询 */ }
      // 最多轮询 5 分钟（150 次 * 2s），避免无限轮询
      if (tries < 150) setTimeout(tick, 2000)
      else setProcessing(null)
    }
    setTimeout(tick, 1500)
  }

  const handleDeleteFile = async (fileId: string) => {
    if (!selectedSpaceId) return
    try {
      await dataSpacesApi.removeFile(selectedSpaceId, fileId)
      message.success('已移除')
      loadFiles()
      loadSpaces()
      if (fileId === selectedFileId) { setSelectedFileId(undefined); setPreview(null) }
    } catch { message.error('移除失败') }
  }

  const filteredSpaces = searchText
    ? spaces.filter(s => s.name.toLowerCase().includes(searchText.toLowerCase()))
    : spaces

  // ====== 三态渲染 ======

  // 状态 1：加载中
  if (spacesLoading) {
    return (
      <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', background: colors.bg }}>
        <Spin size="large" />
      </div>
    )
  }

  // 状态 2：没有空间 — 引导创建
  if (spaces.length === 0 && !selectedSpaceId) {
    return (
      <div style={{
        height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center',
        overflow: 'auto',
        background: `radial-gradient(circle at 50% 30%, rgba(79,70,229,0.04), transparent 60%), ${colors.bg}`,
      }}>
        <div style={{ maxWidth: 560, textAlign: 'center', padding: isMobile ? 24 : 40 }}>
          <div style={{
            width: 72, height: 72, borderRadius: 20,
            background: `linear-gradient(135deg, ${colors.primary}, #7c3aed)`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            margin: '0 auto 28px',
            boxShadow: '0 8px 32px rgba(79,70,229,0.25)',
          }}>
            <DatabaseOutlined style={{ fontSize: 32, color: '#fff' }} />
          </div>

          <Title level={2} style={{ marginBottom: 8, letterSpacing: -0.5 }}>
            创建你的第一个数据空间
          </Title>
          <Text style={{ fontSize: 16, color: colors.textSecondary, display: 'block', marginBottom: 40, lineHeight: 1.7 }}>
            数据空间是你的数据容器。把相关文件放在一起，AI 就能帮你全面分析。
            比如"销售分析"、"客户调研"、"财务报表"等。
          </Text>

          {/* 三步流程 */}
          <div style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', gap: 20, marginBottom: 40, justifyContent: 'center' }}>
            {[
              { icon: <FolderOutlined />, label: '创建空间', desc: '给分析起个名字' },
              { icon: <CloudUploadOutlined />, label: '上传数据', desc: '拖拽文件上传' },
              { icon: <MessageOutlined />, label: '对话分析', desc: '用自然语言提问' },
            ].map((step, i) => (
              <div key={i} style={{ flex: 1, textAlign: 'center', position: 'relative' }}>
                <div style={{
                  width: 48, height: 48, borderRadius: 14,
                  background: colors.primaryLight, color: colors.primary,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  margin: '0 auto 10px', fontSize: 20,
                }}>
                  {step.icon}
                </div>
                <div style={{ fontSize: 14, fontWeight: 600, color: colors.textPrimary, marginBottom: 4 }}>{step.label}</div>
                <div style={{ fontSize: 12, color: colors.textMuted }}>{step.desc}</div>
                {i < 2 && !isMobile && (
                  <div style={{ position: 'absolute', right: -14, top: '50%', color: colors.border, fontSize: 16 }}>→</div>
                )}
              </div>
            ))}
          </div>

          <Button
            type="primary" size="large"
            icon={<PlusOutlined />}
            onClick={() => setCreateModalOpen(true)}
            style={{ height: 50, padding: '0 40px', fontSize: 16, fontWeight: 500, borderRadius: 14 }}
          >
            创建数据空间
          </Button>

          {renderCreateModal()}
        </div>
      </div>
    )
  }

  // 状态 3：有空间但未选中 — 空间卡片列表
  if (!selectedSpaceId) {
    return (
      <div style={{ height: '100%', overflow: 'auto', background: gradient.pageWash }}>
        <div style={{ maxWidth: 1040, margin: '0 auto', padding: isMobile ? '20px 16px 48px' : '40px 32px 64px' }}>
          {/* Header */}
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: isMobile ? 24 : 32 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
              <div style={{
                width: 44, height: 44, borderRadius: 13,
                background: gradient.brand, color: '#fff',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 21, boxShadow: shadow.soft, flexShrink: 0,
              }}>
                <DatabaseOutlined />
              </div>
              <div>
                <Title level={3} style={{ marginBottom: 2, letterSpacing: -0.4 }}>数据管理</Title>
                <Text style={{ color: colors.textMuted, fontSize: 14 }}>
                  管理你的数据空间和文件
                </Text>
              </div>
            </div>
            <Button
              type="primary" icon={<PlusOutlined />}
              onClick={() => setCreateModalOpen(true)}
              style={{ height: 42, borderRadius: 12, fontWeight: 600, boxShadow: shadow.soft, paddingInline: 18 }}
            >
              新建数据空间
            </Button>
          </div>

          {/* Search */}
          {spaces.length > 4 && (
            <Input
              prefix={<SearchOutlined style={{ color: colors.textMuted }} />}
              placeholder="搜索数据空间..."
              value={searchText}
              onChange={e => setSearchText(e.target.value)}
              allowClear
              style={{ marginBottom: 24, maxWidth: 340, borderRadius: 12, height: 40 }}
            />
          )}

          {/* Space cards */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
            gap: 18,
          }}>
            {filteredSpaces.map(space => (
              <div
                key={space.id}
                className="hover-lift"
                onClick={() => onSpaceChange(space.id)}
                style={{
                  padding: '22px',
                  borderRadius: 18,
                  border: `1px solid ${colors.border}`,
                  background: colors.surface,
                  cursor: 'pointer',
                  boxShadow: shadow.card,
                  transition: 'all 0.22s cubic-bezier(0.4,0,0.2,1)',
                  position: 'relative',
                  overflow: 'hidden',
                }}
              >
                {/* 顶部柔色条 */}
                <div style={{ position: 'absolute', top: 0, left: 0, right: 0, height: 3, background: gradient.brand, opacity: 0.85 }} />
                <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14, marginBottom: 18 }}>
                  <div style={{
                    width: 46, height: 46, borderRadius: 13,
                    background: gradient.brandSoft, color: colors.primary,
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: 21, flexShrink: 0,
                    border: `1px solid ${colors.primaryLight}`,
                  }}>
                    <AppstoreOutlined />
                  </div>
                  <div style={{ flex: 1, minWidth: 0, paddingTop: 2 }}>
                    <div style={{ fontSize: 16, fontWeight: 600, color: colors.textPrimary, marginBottom: 4, letterSpacing: -0.2 }}>
                      {space.name}
                    </div>
                    {space.description && (
                      <Text ellipsis style={{ fontSize: 13, color: colors.textMuted, display: 'block' }}>
                        {space.description}
                      </Text>
                    )}
                  </div>
                </div>

                <div style={{ display: 'flex', alignItems: 'center', gap: 16, fontSize: 13, color: colors.textMuted, marginBottom: 18 }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                    <FileTextOutlined style={{ fontSize: 12 }} />
                    {space.file_count} 个文件
                  </span>
                  <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
                    <ClockCircleOutlined style={{ fontSize: 12 }} />
                    {formatDate(space.updated_at)}
                  </span>
                </div>

                <div style={{ display: 'flex', gap: 8 }}>
                  <Button
                    size="small"
                    style={{ flex: 1, borderRadius: 9, fontSize: 12.5, height: 32 }}
                    onClick={(e) => { e.stopPropagation(); onSpaceChange(space.id) }}
                  >
                    管理文件
                  </Button>
                  {onStartChat && space.file_count > 0 && (
                    <Button
                      size="small" type="primary"
                      icon={<MessageOutlined />}
                      style={{ flex: 1, borderRadius: 9, fontSize: 12.5, height: 32 }}
                      onClick={(e) => { e.stopPropagation(); onSpaceChange(space.id); onStartChat?.() }}
                    >
                      开始分析
                    </Button>
                  )}
                </div>
              </div>
            ))}

          </div>
        </div>

        {renderCreateModal()}
      </div>
    )
  }

  // 状态 4：已选中空间 — 文件管理
  const currentSpace = spaces.find(s => s.id === selectedSpaceId)

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: colors.bg }}>
      {/* Header with breadcrumb */}
      <div style={{
        padding: isMobile ? '10px 12px' : '14px 24px',
        borderBottom: `1px solid ${colors.border}`,
        background: colors.surface,
        display: 'flex', alignItems: 'center', gap: isMobile ? 6 : 12, flexWrap: 'wrap',
      }}>
        <Button
          type="text" icon={<ArrowLeftOutlined />}
          onClick={() => { onSpaceChange(undefined); setFiles([]); setSelectedFileId(undefined); setPreview(null) }}
          style={{ color: colors.textSecondary }}
        >
          全部空间
        </Button>
        <span style={{ color: colors.border, fontSize: 16 }}>/</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1 }}>
          <AppstoreOutlined style={{ color: colors.primary }} />
          <span style={{ fontSize: 15, fontWeight: 600, color: colors.textPrimary }}>
            {currentSpace?.name || '数据空间'}
          </span>
          <Tag color="blue" style={{ margin: 0, fontSize: 11 }}>{files.length} 个文件</Tag>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {onStartChat && files.length > 0 && (
            <Button type="primary" icon={<MessageOutlined />} onClick={onStartChat} style={{ borderRadius: 8 }}>
              开始分析
            </Button>
          )}
          <Tooltip title="删除数据空间">
            <Button
              type="text"
              icon={<DeleteOutlined />}
              onClick={() => {
                Modal.confirm({
                  title: '删除数据空间',
                  icon: <ExclamationCircleOutlined />,
                  content: `确定删除「${currentSpace?.name}」？空间内的所有文件和分析数据都会被清除，此操作不可撤销。`,
                  okText: '删除',
                  okButtonProps: { danger: true },
                  cancelText: '取消',
                  onOk: async () => {
                    try {
                      await dataSpacesApi.delete(selectedSpaceId!)
                      message.success('已删除')
                      onSpaceChange(undefined)
                      setFiles([])
                      loadSpaces()
                    } catch { message.error('删除失败') }
                  },
                })
              }}
              style={{ color: colors.textMuted }}
              onMouseEnter={e => (e.currentTarget.style.color = colors.error)}
              onMouseLeave={e => (e.currentTarget.style.color = colors.textMuted)}
            />
          </Tooltip>
        </div>
      </div>

      {/* Upload progress overlay */}
      {uploading && (
        <div style={{
          padding: isMobile ? '10px 12px' : '10px 24px',
          background: '#f0f7ff',
          borderBottom: `1px solid ${colors.border}`,
          display: 'flex', alignItems: 'center', gap: 12,
        }}>
          <LoadingOutlined style={{ color: colors.primary }} />
          <Text style={{ fontSize: 13, color: colors.primary, fontWeight: 500 }}>上传中...</Text>
          <Progress percent={uploadProgress} size="small" strokeColor={colors.primary} showInfo={false} style={{ flex: 1, maxWidth: 200 }} />
        </div>
      )}

      {/* 后台解析进度：上传完成后文件仍在做画像 + 向量索引 */}
      {processing && (
        <div style={{
          padding: isMobile ? '10px 12px' : '10px 24px',
          background: '#fffbe6',
          borderBottom: `1px solid ${colors.border}`,
          display: 'flex', alignItems: 'center', gap: 12,
        }}>
          <LoadingOutlined style={{ color: '#d48806' }} />
          <Text style={{ fontSize: 13, color: '#d48806', fontWeight: 500 }}>
            正在后台解析数据 {processing.ready}/{processing.total}，可继续操作
          </Text>
          <Progress
            percent={processing.total ? Math.round((processing.ready / processing.total) * 100) : 0}
            size="small" strokeColor="#d48806" showInfo={false}
            style={{ flex: 1, maxWidth: 200 }}
          />
        </div>
      )}

      {/* Main content */}
      <div style={{ flex: 1, display: 'flex', flexDirection: isMobile ? 'column' : 'row', overflow: 'hidden' }}>
        {/* Left: file list — 移动端选中文件后隐藏，让预览占满 */}
        <div style={{
          width: isMobile ? '100%' : (files.length === 0 ? '100%' : 380),
          display: isMobile && files.length > 0 && selectedFileId ? 'none' : 'flex',
          borderRight: !isMobile && files.length > 0 ? `1px solid ${colors.border}` : 'none',
          flexDirection: 'column',
          overflow: 'hidden', flexShrink: 0,
        }}>
          {/* Upload area */}
          <div style={{ padding: files.length === 0 ? '24px 24px 0' : '16px 16px 0' }}>
            <Upload.Dragger
              className="ds-dragger"
              multiple showUploadList={false} beforeUpload={handleUpload}
              accept=".csv,.tsv,.xlsx,.xls,.json,.jsonl,.txt,.md,.pdf,.docx,.pptx,.ppt,.py,.sql,.zip,.parquet,.feather,.sqlite,.db,.sqlite3,.png,.jpg,.jpeg,.gif,.bmp,.webp,.html,.xml,.yaml,.yml,.log,.r,.ipynb,.dta,.sav,.sas7bdat"
              style={{
                border: `1.5px dashed ${colors.borderStrong}`,
                borderRadius: 16,
                background: files.length === 0 ? gradient.uploadIdle : colors.surfaceAlt,
                padding: files.length === 0 ? '44px 20px' : '14px 16px',
                transition: 'all 0.2s',
              }}
            >
            {files.length === 0 ? (
              <div style={{ textAlign: 'center' }}>
                <div style={{
                  width: 60, height: 60, borderRadius: 18, margin: '0 auto 16px',
                  background: gradient.brand, color: '#fff',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 28, boxShadow: shadow.soft,
                }}>
                  <InboxOutlined />
                </div>
                <div style={{ fontSize: 15, fontWeight: 600, color: colors.textPrimary, marginBottom: 6 }}>
                  拖拽文件到这里，或点击选择
                </div>
                <div style={{ fontSize: 12.5, color: colors.textMuted, lineHeight: 1.6, maxWidth: 340, margin: '0 auto' }}>
                  支持 CSV、Excel、PDF、Word、JSON、代码文件等 20+ 种格式<br />单文件最大 200MB
                </div>
              </div>
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10 }}>
                <CloudUploadOutlined style={{ fontSize: 17, color: colors.primary }} />
                <div style={{ fontSize: 13, color: colors.textSecondary, fontWeight: 500 }}>
                  拖拽或点击上传更多文件
                </div>
              </div>
            )}
            </Upload.Dragger>
          </div>

          {/* File list */}
          {files.length > 0 ? (
            <div style={{ flex: 1, overflow: 'auto', padding: '10px 12px' }}>
              {files.map(f => {
                const config = getFileConfig(f.file_type)
                const pal = fileTypePalette(config.color)
                const isActive = selectedFileId === f.file_id
                return (
                  <div
                    key={f.file_id}
                    onClick={() => setSelectedFileId(isActive ? undefined : f.file_id)}
                    className="ds-file-row"
                    style={{
                      padding: '11px 12px',
                      marginBottom: 6,
                      borderRadius: 12,
                      cursor: 'pointer',
                      background: isActive ? gradient.brandSoft : 'transparent',
                      border: `1px solid ${isActive ? colors.primaryLight : 'transparent'}`,
                      boxShadow: isActive ? shadow.soft : 'none',
                      display: 'flex', alignItems: 'center', gap: 12,
                      transition: 'all 0.15s',
                    }}
                    onMouseEnter={e => { if (!isActive) e.currentTarget.style.background = colors.bgSubtle }}
                    onMouseLeave={e => { if (!isActive) e.currentTarget.style.background = 'transparent' }}
                  >
                    <div style={{
                      width: 38, height: 38, borderRadius: 11,
                      background: pal.grad,
                      color: config.color,
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      fontSize: 17, flexShrink: 0,
                    }}>
                      {config.icon}
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <Text ellipsis style={{ fontSize: 13.5, fontWeight: 500, display: 'block', color: colors.textPrimary }}>
                        {f.filename}
                      </Text>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 3 }}>
                        <span style={{
                          fontSize: 10, fontWeight: 600, letterSpacing: 0.3,
                          color: config.color, background: pal.bg,
                          padding: '1px 6px', borderRadius: 5,
                        }}>
                          {f.file_type.toUpperCase()}
                        </span>
                        <Text style={{ fontSize: 11.5, color: colors.textMuted }}>{formatSize(f.file_size)}</Text>
                      </div>
                    </div>
                    <Tooltip title="下载">
                      <Button
                        type="text" size="small"
                        icon={<DownloadOutlined />}
                        onClick={async (e) => {
                          e.stopPropagation()
                          try {
                            const res = await api.get(`/files/${f.file_id}/download`, { responseType: 'blob' })
                            const url = URL.createObjectURL(res.data)
                            const a = document.createElement('a')
                            a.href = url
                            a.download = f.filename
                            a.click()
                            URL.revokeObjectURL(url)
                          } catch { message.error('下载失败') }
                        }}
                        className="ds-row-action"
                        style={{ color: colors.textMuted }}
                      />
                    </Tooltip>
                    <Popconfirm
                      title="移除此文件？"
                      onConfirm={(e) => { e?.stopPropagation(); handleDeleteFile(f.file_id) }}
                      okText="移除" cancelText="取消"
                    >
                      <Button
                        type="text" size="small" danger
                        icon={<DeleteOutlined />}
                        onClick={e => e.stopPropagation()}
                        className="ds-row-action"
                      />
                    </Popconfirm>
                  </div>
                )
              })}
            </div>
          ) : !uploading ? (
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 40 }}>
              <div style={{ textAlign: 'center' }}>
                <div style={{
                  width: 72, height: 72, borderRadius: 20, margin: '0 auto 18px',
                  background: gradient.brandSoft, color: colors.primary,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 32, border: `1px solid ${colors.primaryLight}`,
                }}>
                  <FolderOutlined />
                </div>
                <Title level={5} style={{ color: colors.textSecondary, marginBottom: 4 }}>还没有文件</Title>
                <Text style={{ color: colors.textMuted, fontSize: 13 }}>上传数据文件开始分析</Text>
              </div>
            </div>
          ) : null}
        </div>

        {/* Right: preview — 移动端仅在选中文件时显示 */}
        {files.length > 0 && (!isMobile || selectedFileId) && (
          <div className="ds-preview" style={{ flex: 1, overflow: 'auto', padding: isMobile ? 12 : 24 }}>
            {isMobile && selectedFileId && (
              <Button
                type="text"
                size="small"
                icon={<ArrowLeftOutlined />}
                onClick={() => { setSelectedFileId(undefined); setPreview(null) }}
                style={{ color: colors.textSecondary, marginBottom: 8, paddingLeft: 0 }}
              >
                返回文件列表
              </Button>
            )}
            {!selectedFileId ? (
              <div style={{ textAlign: 'center', paddingTop: 80 }}>
                <div style={{
                  width: 72, height: 72, borderRadius: 20, margin: '0 auto 18px',
                  background: gradient.brandSoft, color: colors.primary,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: 32, border: `1px solid ${colors.primaryLight}`,
                }}>
                  <FileTextOutlined />
                </div>
                <Title level={5} style={{ color: colors.textSecondary }}>点击左侧文件查看预览</Title>
                <Text style={{ color: colors.textMuted, fontSize: 13 }}>选择一个文件查看其数据内容</Text>
              </div>
            ) : previewLoading ? (
              <div style={{ textAlign: 'center', paddingTop: 80 }}>
                <Spin size="large" />
                <div style={{ marginTop: 12, color: colors.textMuted }}>加载预览...</div>
              </div>
            ) : preview?.type === 'table' ? (
              <div>
                <div style={{ marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8 }}>
                  <Text style={{ fontSize: 14, fontWeight: 600 }}>
                    {files.find(f => f.file_id === selectedFileId)?.filename}
                  </Text>
                  <Tag>{preview.total_rows} 行</Tag>
                  <Tag>{preview.columns?.length} 列</Tag>
                </div>
                <Table
                  dataSource={preview.rows?.map((row: string[], i: number) => {
                    const obj: Record<string, string> = { _key: String(i) }
                    preview.columns?.forEach((col: any, j: number) => { obj[col.name] = row[j] })
                    return obj
                  })}
                  columns={preview.columns?.map((col: any) => ({
                    title: <Tooltip title={`类型: ${col.dtype}`}><span style={{ fontSize: 12 }}>{col.name}</span></Tooltip>,
                    dataIndex: col.name, key: col.name, width: 140, ellipsis: true,
                    render: (v: string) => <span style={{ fontSize: 12 }}>{v}</span>,
                  }))}
                  rowKey="_key" size="small"
                  scroll={{ x: (preview.columns?.length || 1) * 140 }}
                  pagination={{ pageSize: 50, size: 'small' }}
                  style={{ borderRadius: 10 }}
                />
              </div>
            ) : preview?.type === 'workbook' ? (
              <div>
                <div style={{ marginBottom: 12, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <Text style={{ fontSize: 14, fontWeight: 600 }}>
                    {files.find(f => f.file_id === selectedFileId)?.filename}
                  </Text>
                  <Tag>{preview.sheet_count} 个工作表</Tag>
                </div>
                <Tabs
                  size="small"
                  items={preview.sheets?.map((sheet: any) => ({
                    key: sheet.name,
                    label: `${sheet.name} (${sheet.total_rows} 行)`,
                    children: (
                      <Table
                        dataSource={sheet.rows?.map((row: string[], i: number) => {
                          const obj: Record<string, string> = { _key: `${sheet.name}-${i}` }
                          sheet.columns?.forEach((col: any, j: number) => { obj[col.name] = row[j] })
                          return obj
                        })}
                        columns={sheet.columns?.map((col: any) => ({
                          title: <Tooltip title={`类型: ${col.dtype}`}><span style={{ fontSize: 12 }}>{col.name}</span></Tooltip>,
                          dataIndex: col.name, key: col.name, width: 140, ellipsis: true,
                          render: (v: string) => <span style={{ fontSize: 12 }}>{v}</span>,
                        }))}
                        rowKey="_key" size="small"
                        scroll={{ x: (sheet.columns?.length || 1) * 140 }}
                        pagination={{ pageSize: 50, size: 'small' }}
                      />
                    ),
                  }))}
                />
              </div>
            ) : preview?.type === 'text' ? (
              <div>
                <div style={{ marginBottom: 12 }}>
                  <Text style={{ fontSize: 14, fontWeight: 600 }}>
                    {files.find(f => f.file_id === selectedFileId)?.filename}
                  </Text>
                  {preview.total_lines && <Tag style={{ marginLeft: 8 }}>{preview.total_lines} 行</Tag>}
                </div>
                <pre style={{
                  padding: 20, fontSize: 13, lineHeight: 1.7,
                  background: colors.bgSubtle, border: `1px solid ${colors.border}`,
                  borderRadius: 12, maxHeight: 500, overflow: 'auto',
                  whiteSpace: 'pre-wrap', wordBreak: 'break-word', color: colors.textSecondary,
                }}>
                  {preview.content}
                </pre>
              </div>
            ) : preview?.type === 'database' ? (
              <div>
                <div style={{ marginBottom: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {preview.tables?.map((t: string) => (
                    <Tag key={t} color={t === preview.current_table ? 'blue' : 'default'}>{t}</Tag>
                  ))}
                </div>
                {preview.columns && (
                  <Table
                    dataSource={preview.rows?.map((row: string[], i: number) => {
                      const obj: Record<string, string> = { _key: String(i) }
                      preview.columns?.forEach((col: any, j: number) => { obj[col.name] = row[j] })
                      return obj
                    })}
                    columns={preview.columns?.map((col: any) => ({
                      title: col.name, dataIndex: col.name, key: col.name,
                      width: 140, ellipsis: true,
                      render: (v: string) => <span style={{ fontSize: 12 }}>{v}</span>,
                    }))}
                    rowKey="_key" size="small"
                    scroll={{ x: (preview.columns?.length || 1) * 140 }}
                    pagination={{ pageSize: 50, size: 'small' }}
                  />
                )}
              </div>
            ) : preview?.type === 'image' ? (
              <ImagePreview fileId={selectedFileId!} filename={preview.filename} sizeKb={preview.file_size_kb} />
            ) : preview?.type === 'unsupported' ? (
              <div style={{ textAlign: 'center', paddingTop: 80 }}>
                <FileTextOutlined style={{ fontSize: 48, color: colors.border, marginBottom: 16 }} />
                <Title level={5} style={{ color: colors.textSecondary, marginBottom: 8 }}>
                  {preview.message || '不支持预览此文件类型'}
                </Title>
                <Text style={{ color: colors.textMuted, fontSize: 13 }}>
                  该文件已上传成功，AI 对话中仍可分析此文件
                </Text>
              </div>
            ) : (
              <div style={{ textAlign: 'center', paddingTop: 80 }}>
                <FileTextOutlined style={{ fontSize: 48, color: colors.border, marginBottom: 16 }} />
                <Title level={5} style={{ color: colors.textSecondary, marginBottom: 8 }}>
                  暂无预览
                </Title>
                <Text style={{ color: colors.textMuted, fontSize: 13 }}>
                  该文件已上传成功，AI 对话中仍可分析此文件
                </Text>
              </div>
            )}
          </div>
        )}
      </div>

      {renderCreateModal()}
    </div>
  )

  function renderCreateModal() {
    return (
      <Modal
        title={null}
        open={createModalOpen}
        onCancel={() => { setCreateModalOpen(false); setNewSpaceName(''); setNewSpaceDesc('') }}
        footer={null}
        centered
        width={isMobile ? '92%' : 440}
      >
        <div style={{ padding: '8px 0' }}>
          <div style={{
            width: 52, height: 52, borderRadius: 14,
            background: colors.primaryLight, color: colors.primary,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 24, margin: '0 auto 16px',
          }}>
            <FolderOutlined />
          </div>
          <Title level={4} style={{ textAlign: 'center', marginBottom: 4 }}>创建数据空间</Title>
          <Text style={{ display: 'block', textAlign: 'center', color: colors.textMuted, marginBottom: 24, fontSize: 13 }}>
            一个数据空间对应一组相关数据，创建后可上传文件开始分析
          </Text>

          <div style={{ marginBottom: 16 }}>
            <Text style={{ fontSize: 13, fontWeight: 500, display: 'block', marginBottom: 6 }}>空间名称</Text>
            <Input
              size="large"
              placeholder="例如：Q4 销售分析、客户满意度调研..."
              value={newSpaceName}
              onChange={e => setNewSpaceName(e.target.value)}
              onPressEnter={handleCreateSpace}
              style={{ borderRadius: 10 }}
              autoFocus
            />
          </div>
          <div style={{ marginBottom: 24 }}>
            <Text style={{ fontSize: 13, fontWeight: 500, display: 'block', marginBottom: 6 }}>描述（可选）</Text>
            <Input.TextArea
              placeholder="简单描述这个项目的分析目的..."
              value={newSpaceDesc}
              onChange={e => setNewSpaceDesc(e.target.value)}
              rows={2}
              style={{ borderRadius: 10 }}
            />
          </div>

          <Button
            type="primary" block size="large"
            onClick={handleCreateSpace}
            loading={creating}
            disabled={!newSpaceName.trim()}
            style={{ height: 46, borderRadius: 12, fontWeight: 500 }}
          >
            创建空间
          </Button>
        </div>
      </Modal>
    )
  }
}
