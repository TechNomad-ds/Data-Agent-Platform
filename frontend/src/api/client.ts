import axios from 'axios'
import { useAuthStore } from '@/stores/authStore'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// 请求拦截器：添加 token
api.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器：处理 401
let isRefreshing = false
let failedQueue: Array<{ resolve: (token: string) => void; reject: (err: any) => void }> = []

const processQueue = (error: any, token: string | null = null) => {
  failedQueue.forEach((prom) => {
    if (token) prom.resolve(token)
    else prom.reject(error)
  })
  failedQueue = []
}

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config
    if (error.response?.status === 401 && !originalRequest._retry) {
      if (isRefreshing) {
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve: (token) => {
            originalRequest.headers.Authorization = `Bearer ${token}`
            resolve(api(originalRequest))
          }, reject })
        })
      }

      originalRequest._retry = true
      isRefreshing = true

      const refreshToken = useAuthStore.getState().refreshToken
      if (refreshToken) {
        try {
          const res = await axios.post('/api/auth/refresh', { refresh_token: refreshToken })
          const { access_token, refresh_token } = res.data
          useAuthStore.getState().setTokens(access_token, refresh_token)
          processQueue(null, access_token)
          originalRequest.headers.Authorization = `Bearer ${access_token}`
          return api(originalRequest)
        } catch {
          processQueue(error, null)
          useAuthStore.getState().logout()
        } finally {
          isRefreshing = false
        }
      } else {
        useAuthStore.getState().logout()
      }
    }
    return Promise.reject(error)
  }
)

/**
 * 获取当前有效的 token（用于非 axios 请求如 fetch/SSE）
 * 如果 token 可能过期，尝试刷新
 */
export async function getValidToken(): Promise<string | null> {
  const { token, refreshToken } = useAuthStore.getState()
  if (!token) return null

  // 简单检查：尝试用当前 token，如果失败则刷新
  // JWT 解码检查过期时间
  try {
    const payload = JSON.parse(atob(token.split('.')[1]))
    const exp = payload.exp * 1000
    const now = Date.now()
    // 如果 token 还有 2 分钟以上有效期，直接用
    if (exp - now > 120000) return token
  } catch {
    return token
  }

  // token 快过期了，尝试刷新
  if (refreshToken) {
    try {
      const res = await axios.post('/api/auth/refresh', { refresh_token: refreshToken })
      const { access_token, refresh_token: newRefresh } = res.data
      useAuthStore.getState().setTokens(access_token, newRefresh)
      return access_token
    } catch {
      useAuthStore.getState().logout()
      return null
    }
  }

  return token
}

export default api
