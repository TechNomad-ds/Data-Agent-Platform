import api from './client'

export interface LoginData {
  email: string
  password: string
}

export interface RegisterData {
  email: string
  username: string
  password: string
  research_consent: boolean
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
}

export interface UserInfo {
  id: string
  email: string
  username: string
  role: string
  is_active: boolean
  research_consent: boolean
  created_at: string
}

export const authApi = {
  login: (data: LoginData) => api.post<TokenResponse>('/auth/login', data),
  register: (data: RegisterData) => api.post<UserInfo>('/auth/register', data),
  getMe: () => api.get<UserInfo>('/auth/me'),
  refresh: (refreshToken: string) =>
    api.post<TokenResponse>('/auth/refresh', { refresh_token: refreshToken }),
}
