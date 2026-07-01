import { useState, useEffect } from 'react'
import { Spin, Modal, Tooltip, message as antMessage } from 'antd'
import { FileOutlined, DownloadOutlined, EyeOutlined } from '@ant-design/icons'
import { saveAs } from 'file-saver'
import api from '@/api/client'
import { dataSpacesApi } from '@/api/dataSpaces'
import { colors } from '@/styles/tokens'

type Resolved = {
  file_id: string
  filename: string
  file_type: string
  file_size: number
  mime_type: string | null
}

const IMAGE_EXTS = ['png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp']

function fmtSize(n: number): string {
  if (!n) return ''
  if (n > 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`
  return `${Math.max(1, Math.round(n / 1024))} KB`
}

/** 回答区的「文件卡」：把 ```file 块里的文件名解析为本对话可见的真实文件，
 *  渲染成可下载（图片可预览）的卡片。解析失败时优雅降级为纯文本提示。 */
export default function FileCard({ raw, conversationId }: { raw: string; conversationId?: string }) {
  const filename = (raw || '').trim().split('\n')[0].trim()
  const [resolved, setResolved] = useState<Resolved | null>(null)
  const [loading, setLoading] = useState(true)
  const [failed, setFailed] = useState(false)
  const [downloading, setDownloading] = useState(false)
  const [previewSrc, setPreviewSrc] = useState<string | null>(null)
  const [previewOpen, setPreviewOpen] = useState(false)

  useEffect(() => {
    let alive = true
    if (!filename || !conversationId) { setLoading(false); setFailed(true); return }
    setLoading(true)
    dataSpacesApi.resolveConversationFile(conversationId, filename)
      .then((res) => { if (alive) { setResolved(res.data); setFailed(false) } })
      .catch(() => { if (alive) setFailed(true) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [filename, conversationId])

  const isImage = resolved ? IMAGE_EXTS.includes((resolved.file_type || '').toLowerCase()) : false

  const handleDownload = async () => {
    if (!resolved) return
    setDownloading(true)
    try {
      const res = await api.get(`/files/${resolved.file_id}/download`, { responseType: 'blob' })
      saveAs(res.data, resolved.filename)
    } catch {
      antMessage.error('下载失败')
    } finally {
      setDownloading(false)
    }
  }

  const handlePreview = async () => {
    if (!resolved) return
    setPreviewOpen(true)
    if (previewSrc) return
    try {
      const res = await api.get(`/files/${resolved.file_id}/download`, { responseType: 'blob' })
      setPreviewSrc(URL.createObjectURL(res.data))
    } catch {
      antMessage.error('预览加载失败')
    }
  }

  useEffect(() => () => { if (previewSrc) URL.revokeObjectURL(previewSrc) }, [previewSrc])

  return <FileCardView
    filename={filename}
    resolved={resolved}
    loading={loading}
    failed={failed}
    downloading={downloading}
    isImage={isImage}
    onDownload={handleDownload}
    onPreview={handlePreview}
    previewOpen={previewOpen}
    previewSrc={previewSrc}
    onClosePreview={() => setPreviewOpen(false)}
  />
}

// FILECARD_VIEW_PLACEHOLDER
function FileCardView(props: {
  filename: string
  resolved: Resolved | null
  loading: boolean
  failed: boolean
  downloading: boolean
  isImage: boolean
  onDownload: () => void
  onPreview: () => void
  previewOpen: boolean
  previewSrc: string | null
  onClosePreview: () => void
}) {
  const { filename, resolved, loading, failed, downloading, isImage,
    onDownload, onPreview, previewOpen, previewSrc, onClosePreview } = props

  // 解析失败：优雅降级为纯文本，不留裂卡
  if (failed && !loading) {
    return (
      <span style={{ color: colors.textMuted, fontSize: 13 }}>
        📎 {filename || '文件'}（未找到，可能已删除或不在本对话）
      </span>
    )
  }

  return (
    <div
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 10,
        padding: '10px 14px',
        margin: '8px 0',
        maxWidth: 360,
        background: colors.bgSubtle,
        border: `1px solid ${colors.border}`,
        borderRadius: 10,
      }}
    >
      <FileOutlined style={{ color: colors.primary, fontSize: 20, flexShrink: 0 }} />
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{
          fontSize: 13.5, fontWeight: 500, color: colors.textPrimary,
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>
          {resolved?.filename || filename}
        </div>
        <div style={{ fontSize: 11.5, color: colors.textMuted }}>
          {loading ? '解析中…' : [
            (resolved?.file_type || '').toUpperCase(),
            resolved ? fmtSize(resolved.file_size) : '',
          ].filter(Boolean).join(' · ')}
        </div>
      </div>
      {loading ? (
        <Spin size="small" />
      ) : (
        <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
          {isImage && (
            <Tooltip title="预览">
              <EyeOutlined
                onClick={onPreview}
                style={{ fontSize: 16, color: colors.textSecondary, cursor: 'pointer', padding: 4 }}
              />
            </Tooltip>
          )}
          <Tooltip title="下载">
            {downloading ? <Spin size="small" /> : (
              <DownloadOutlined
                onClick={onDownload}
                style={{ fontSize: 16, color: colors.primary, cursor: 'pointer', padding: 4 }}
              />
            )}
          </Tooltip>
        </div>
      )}

      <Modal open={previewOpen} onCancel={onClosePreview} footer={null} title={resolved?.filename} width={720}>
        {previewSrc
          ? <img src={previewSrc} alt={resolved?.filename} style={{ maxWidth: '100%', borderRadius: 6 }} />
          : <div style={{ textAlign: 'center', padding: 40 }}><Spin /></div>}
      </Modal>
    </div>
  )
}

