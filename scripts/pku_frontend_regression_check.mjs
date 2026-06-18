#!/usr/bin/env node
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const requireFromFrontend = createRequire(path.join(root, 'frontend/package.json'))
const katex = requireFromFrontend('katex')

function read(rel) {
  return fs.readFileSync(path.join(root, rel), 'utf8')
}

function assert(condition, message) {
  if (!condition) {
    throw new Error(message)
  }
}

const pkg = JSON.parse(read('frontend/package.json'))
for (const dep of ['remark-math', 'rehype-katex', 'katex']) {
  assert(pkg.dependencies?.[dep], `frontend/package.json missing dependency: ${dep}`)
}

const main = read('frontend/src/main.tsx')
assert(main.includes("import 'katex/dist/katex.min.css'"), 'main.tsx must import KaTeX CSS')

const markdown = read('frontend/src/components/Chat/MarkdownRenderer.tsx')
assert(markdown.includes("import remarkMath from 'remark-math'"), 'MarkdownRenderer missing remark-math')
assert(markdown.includes("import rehypeKatex from 'rehype-katex'"), 'MarkdownRenderer missing rehype-katex')
assert(markdown.includes('remarkPlugins={[remarkGfm, remarkMath]}'), 'MarkdownRenderer must enable remarkMath')
assert(markdown.includes('rehypePlugins={[rehypeKatex]}'), 'MarkdownRenderer must enable rehypeKatex')

const formulaHtml = katex.renderToString('AMAT = HitTime + MissRate \\times MissPenalty')
assert(formulaHtml.includes('katex'), 'KaTeX render smoke check failed')

const chatView = read('frontend/src/components/Chat/ChatView.tsx')
assert(chatView.includes("import MarkdownRenderer from '@/components/Chat/MarkdownRenderer'"), 'ChatView must use shared MarkdownRenderer')
assert(!chatView.includes('ReactMarkdown'), 'ChatView should not render markdown through bare ReactMarkdown')
assert(
  /const showStreaming = isStreaming && streamingConversationId === conversationId/.test(chatView),
  'ChatView must bind streaming display to conversationId'
)
assert(
  /\{showStreaming \? \(/.test(chatView),
  'Stop button must only render for the currently streaming conversation'
)
assert(
  chatView.includes('`/chat/conversations/${streamingConversationId}/abort`'),
  'Abort request must target streamingConversationId, not the currently selected conversation'
)
assert(
  chatView.includes("isStreaming ? '其他对话正在生成，请稍后'"),
  'Non-streaming conversations should show a clear disabled-send tooltip while another stream is active'
)
assert(
  chatView.includes("thinkingText={seg.content || ''}") && chatView.includes('defaultExpanded={false}'),
  'Streaming thinking content should be hidden in a collapsed ThinkingBlock by default'
)

const messageContent = read('frontend/src/components/Chat/MessageContent.tsx')
assert(
  messageContent.includes("thinkingText={seg.content || ''}") && messageContent.includes('defaultExpanded={false}'),
  'Saved thinking content should be hidden in a collapsed ThinkingBlock by default'
)

const pkuChecklist = read('DEPLOY_PKU.md')
const reportTemplate = read('PKU_ACCEPTANCE_REPORT_TEMPLATE.md')
const nginxConf = read('frontend/nginx.conf')
const smokeScript = read('scripts/pku_acceptance_smoke.py')
const llmScript = read('scripts/pku_llm_acceptance_check.py')
assert(nginxConf.includes('proxy_pass http://127.0.0.1:8002;'), 'frontend/nginx.conf should proxy to local gunicorn by default')
assert(!nginxConf.includes('proxy_pass http://backend:8002;'), 'frontend/nginx.conf should not default to Docker-only backend hostname')
assert(nginxConf.includes('proxy_buffering off;'), 'frontend/nginx.conf must disable buffering for SSE')
assert(nginxConf.includes('proxy_request_buffering off;'), 'frontend/nginx.conf should disable request buffering for large uploads')
for (const phrase of ['输出内容格式乱码', '数据空间 name 无法修改', '单次上传 7 个文件请求频繁', '公式渲染问题', '流式输出切换污染']) {
  assert(reportTemplate.includes(phrase), `PKU report template missing original issue: ${phrase}`)
}
for (const phrase of ['计算机体系结构', '线性代数复习', '现代文学导论']) {
  assert(pkuChecklist.includes(phrase), `PKU checklist missing course: ${phrase}`)
  assert(reportTemplate.includes(phrase), `PKU report template missing course: ${phrase}`)
}
for (const phrase of ['online_course_ops_multisheet.xlsx', '"type") != "workbook"', '课程目录', '报名记录', '学习日志']) {
  assert(smokeScript.includes(phrase), `PKU smoke script missing multi-sheet Excel coverage: ${phrase}`)
}
for (const phrase of ['multisheet_excel_join', 'sentiment_improvement_request', '希望增加更多实战', 'pku_llm_acceptance_report.json', '/api/models/available', 'DATAMIND_LLM_RUN_LABEL']) {
  assert(llmScript.includes(phrase), `PKU LLM script missing behavior check: ${phrase}`)
  assert(pkuChecklist.includes('pku_llm_acceptance_check.py'), 'PKU checklist missing LLM acceptance script')
  assert(reportTemplate.includes('pku_llm_acceptance_check.py'), 'PKU report template missing LLM acceptance script')
}

console.log(JSON.stringify({
  ok: true,
  checks: [
    'math_dependencies',
    'katex_css',
    'markdown_math_pipeline',
    'katex_render',
    'shared_stream_markdown_renderer',
    'streaming_conversation_isolation',
    'thinking_collapsed_by_default',
    'abort_targets_active_stream',
    'multisheet_excel_smoke_coverage',
    'real_llm_acceptance_script',
    'pku_acceptance_template_coverage',
    'nginx_host_deployment_proxy',
  ],
}, null, 2))
