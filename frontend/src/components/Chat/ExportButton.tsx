import { Button, Dropdown, message } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import { saveAs } from 'file-saver'
import { reportsApi } from '@/api/reports'

interface Props {
  conversationId: string | undefined
}

export default function ExportButton({ conversationId }: Props) {
  if (!conversationId) return null

  const handleExport = async (format: string) => {
    try {
      const res = await reportsApi.generate(conversationId, format)
      const disposition = res.headers['content-disposition'] || ''
      const filenameMatch = disposition.match(/filename="(.+)"/)
      const filename = filenameMatch ? filenameMatch[1] : `report.${format === 'markdown' ? 'md' : 'pdf'}`
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
        style={{ color: '#8888a0' }}
        size="small"
      >
        导出
      </Button>
    </Dropdown>
  )
}
