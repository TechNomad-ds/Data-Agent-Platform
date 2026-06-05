import type { AxiosError } from 'axios'

/**
 * 把上传失败的各种情况翻译成可读的中文提示。
 * 覆盖：后端明确原因(detail)、413 超大小、超时、网络断开等。
 */
export function uploadErrorMessage(err: any, fileName?: string): string {
  const prefix = fileName ? `${fileName} 上传失败：` : '上传失败：'
  const ax = err as AxiosError<any>

  // axios 超时（timeout 触发会是 ECONNABORTED）
  if (ax?.code === 'ECONNABORTED' || /timeout/i.test(ax?.message || '')) {
    return `${prefix}上传超时，请检查网络或稍后重试`
  }

  // 无响应：网络中断 / 服务不可达
  if (!ax?.response) {
    if (ax?.code === 'ERR_NETWORK') return `${prefix}网络连接中断`
    return `${prefix}无法连接到服务器`
  }

  const status = ax.response.status
  const detail = ax.response.data?.detail

  // 413：文件体积超过 nginx/服务端限制
  if (status === 413) {
    return `${prefix}文件过大，超过服务器允许的上传大小`
  }
  if (status === 401 || status === 403) {
    return `${prefix}登录状态已失效，请重新登录后再试`
  }
  if (status === 404) {
    return `${prefix}数据空间不存在或已被删除`
  }

  // 后端明确给出的原因（如"不支持的文件类型""超过大小限制"）
  if (typeof detail === 'string' && detail.trim()) {
    return `${prefix}${detail}`
  }

  if (status >= 500) {
    return `${prefix}服务器处理出错，请稍后重试`
  }
  return `${prefix}请稍后重试`
}
