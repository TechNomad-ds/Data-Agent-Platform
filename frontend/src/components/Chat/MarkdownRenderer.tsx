import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import ChartMessage from '@/components/Charts/ChartMessage'
import AnswerCard from './AnswerCard'
import { colors } from '@/styles/tokens'

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
          code({ className, children, ...props }) {
            const match = /language-(\w+)/.exec(className || '')
            const codeString = String(children).replace(/\n$/, '')
            if (match || codeString.includes('\n')) {
              return (
                <SyntaxHighlighter
                  style={oneDark}
                  language={match?.[1] || 'text'}
                  PreTag="div"
                  customStyle={{
                    borderRadius: 10,
                    fontSize: 13,
                    margin: '12px 0',
                    padding: '14px 16px',
                  }}
                >
                  {codeString}
                </SyntaxHighlighter>
              )
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

export default function MarkdownRenderer({ content }: { content: string }) {
  const specialBlockRe = /```(chart|answer)\n([\s\S]*?)```/g
  const parts: { type: 'markdown' | 'chart' | 'answer'; content: string }[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null

  while ((match = specialBlockRe.exec(content)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ type: 'markdown', content: content.slice(lastIndex, match.index) })
    }
    parts.push({ type: match[1] as 'chart' | 'answer', content: match[2] })
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
        return <AnswerCard key={i} raw={part.content} />
      })}
    </>
  )
}
