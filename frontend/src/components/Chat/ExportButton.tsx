import { Button, Dropdown, message } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import { saveAs } from 'file-saver'
import { reportsApi } from '@/api/reports'
import { colors } from '@/styles/tokens'

interface Props {
  conversationId: string | undefined
}

export default function ExportButton({ conversationId }: Props) {
  if (!conversationId) return null

  const handleExport = async (format: string) => {
    try {
      const res = await reportsApi.generate(conversationId, format)
      const disposition = res.headers['content-disposition'] || ''
      // 优先读 RFC 5987 的 filename*（含中文，UTF-8 百分号编码），回退到普通 filename
      let filename = `report.${format === 'markdown' ? 'md' : 'pdf'}`
      const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i)
      const asciiMatch = disposition.match(/filename="([^"]+)"/i)
      if (utf8Match) {
        try { filename = decodeURIComponent(utf8Match[1]) } catch { /* 保持默认 */ }
      } else if (asciiMatch) {
        filename = asciiMatch[1]
      }
      saveAs(res.data, filename)
      message.success('报告已导出')
    } catch {
      message.error('导出失败')
    }
  }

  const items = [
    { key: 'markdown', label: '导出 Markdown', onClick: () => handleExport('markdown') },
  ]

  return (
    <Dropdown menu={{ items }} placement="bottomRight">
      <Button
        type="text"
        icon={<DownloadOutlined />}
        style={{ color: colors.textSecondary }}
        size="small"
      >
        导出
      </Button>
    </Dropdown>
  )
}
