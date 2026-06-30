/**
 * 复制文本到剪贴板，带 HTTP 降级。
 *
 * navigator.clipboard 只在安全上下文（HTTPS / localhost）可用。本平台通过 IP+HTTP
 * 访问时它是 undefined，直接用会抛异常导致「复制失败」。这里优先用现代 API，
 * 不可用时退回老式 document.execCommand('copy')（HTTP 下也能用）。
 */
export async function copyText(text: string): Promise<boolean> {
  // 现代 API：仅安全上下文可用
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // 落到下面的降级方案
    }
  }
  // 降级：隐藏 textarea + execCommand('copy')
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    // 避免滚动/聚焦跳动
    ta.style.position = 'fixed'
    ta.style.top = '-9999px'
    ta.style.left = '-9999px'
    ta.setAttribute('readonly', '')
    document.body.appendChild(ta)
    ta.select()
    ta.setSelectionRange(0, text.length)
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}
