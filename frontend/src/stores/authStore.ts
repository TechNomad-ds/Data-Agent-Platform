import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import { authApi, UserInfo } from '@/api/auth'

interface AuthState {
  token: string | null
  refreshToken: string | null
  user: UserInfo | null
  setTokens: (token: string, refreshToken: string) => void
  setUser: (user: UserInfo) => void
  logout: () => void
  fetchUser: () => Promise<void>
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      refreshToken: null,
      user: null,

      setTokens: (token, refreshToken) => set({ token, refreshToken }),

      setUser: (user) => set({ user }),

      logout: () => {
        set({ token: null, refreshToken: null, user: null })
        window.location.href = '/login'
      },

      fetchUser: async () => {
        try {
          const res = await authApi.getMe()
          set({ user: res.data })
        } catch {
          get().logout()
        }
      },
    }),
    {
      name: 'auth-storage',
      partialize: (state) => ({
        token: state.token,
        refreshToken: state.refreshToken,
      }),
    }
  )
)
