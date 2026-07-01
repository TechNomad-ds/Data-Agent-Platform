import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { Tooltip, message as antMessage } from 'antd'
import { CopyOutlined, CheckOutlined } from '@ant-design/icons'
import ChartMessage from '@/components/Charts/ChartMessage'
import AnswerCard from './AnswerCard'
import FileCard from './FileCard'
import { copyText } from '@/utils/clipboard'
import { colors } from '@/styles/tokens'

/** 带复制按钮的代码块（浅色主题，悬停显示复制） */
function CodeBlock({ code, language }: { code: string; language: string }) {
  const [copied, setCopied] = useState(false)
  const [hover, setHover] = useState(false)

  const handleCopy = async () => {
    if (await copyText(code)) {
      setCopied(true)
      antMessage.success('已复制')
      setTimeout(() => setCopied(false), 1800)
    } else {
      antMessage.error('复制失败')
    }
  }

  return (
    <div
      style={{ position: 'relative', margin: '12px 0' }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
    >
      <Tooltip title={copied ? '已复制' : '复制代码'} placement="left">
        <span
          onClick={handleCopy}
          style={{
            position: 'absolute',
            top: 8,
            right: 8,
            zIndex: 1,
            cursor: 'pointer',
            padding: '4px 6px',
            borderRadius: 6,
            background: colors.bg,
            border: `1px solid ${colors.border}`,
            color: copied ? colors.success : colors.textMuted,
            fontSize: 12,
            lineHeight: 1,
            opacity: hover || copied ? 1 : 0,
            transition: 'opacity 0.15s',
          }}
        >
          {copied ? <CheckOutlined /> : <CopyOutlined />}
        </span>
      </Tooltip>
      <SyntaxHighlighter
        style={oneLight}
        language={language}
        PreTag="div"
        customStyle={{
          borderRadius: 10,
          fontSize: 13,
          margin: 0,
          padding: '14px 16px',
          background: colors.bgSubtle,
          border: `1px solid ${colors.border}`,
        }}
      >
        {code}
      </SyntaxHighlighter>
    </div>
  )
}

function MarkdownRaw({ content }: { content: string }) {
  return (
    <div className="markdown-body">
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath]}
        rehypePlugins={[rehypeKatex]}
        components={{
          table({ children, ...props }) {
            return (
              <div className="table-wrapper">
                <table {...props}>{children}</table>
              </div>
            )
          },
          img({ node, ...props }) {
            // 标准 markdown 图片 ![](url) 默认就能渲染，这里只补样式与健壮性：
            // 限制宽度避免撑破气泡、懒加载、加载失败时隐藏（坏链不留裂图占位）。
            return (
              <img
                {...props}
                loading="lazy"
                referrerPolicy="no-referrer"
                style={{
                  maxWidth: '100%',
                  height: 'auto',
                  borderRadius: 8,
                  margin: '8px 0',
                  border: `1px solid ${colors.border}`,
                }}
                onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none' }}
              />
            )
          },
          code({ className, children, ...props }) {
            const match = /language-(\w+)/.exec(className || '')
            const codeString = String(children).replace(/\n$/, '')
            if (match || codeString.includes('\n')) {
              return <CodeBlock code={codeString} language={match?.[1] || 'text'} />
            }
            return (
              <code
                style={{
                  background: colors.bgSubtle,
                  padding: '2px 6px',
                  borderRadius: 4,
                  fontSize: '0.875em',
                  color: colors.textPrimary,
                  fontFamily:
                    "'SF Mono', SFMono-Regular, Menlo, Consolas, monospace",
                }}
                {...props}
              >
                {children}
              </code>
            )
          },
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}

export default function MarkdownRenderer({ content, conversationId }: { content: string; conversationId?: string }) {
  const specialBlockRe = /```(chart|answer|file)\n([\s\S]*?)```/g
  const parts: { type: 'markdown' | 'chart' | 'answer' | 'file'; content: string }[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null

  while ((match = specialBlockRe.exec(content)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ type: 'markdown', content: content.slice(lastIndex, match.index) })
    }
    parts.push({ type: match[1] as 'chart' | 'answer' | 'file', content: match[2] })
    lastIndex = match.index + match[0].length
  }

  if (lastIndex < content.length) {
    parts.push({ type: 'markdown', content: content.slice(lastIndex) })
  }

  if (parts.length === 0) return <MarkdownRaw content={content} />

  return (
    <>
      {parts.map((part, i) => {
        if (part.type === 'markdown') {
          return part.content.trim() ? <MarkdownRaw key={i} content={part.content} /> : null
        }
        if (part.type === 'chart') return <ChartMessage key={i} chartJson={part.content} />
        if (part.type === 'file') return <FileCard key={i} raw={part.content} conversationId={conversationId} />
        return <AnswerCard key={i} raw={part.content} />
      })}
    </>
  )
}
