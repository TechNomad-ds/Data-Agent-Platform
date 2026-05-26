import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { ConfigProvider } from 'antd'
import { useAuthStore } from '@/stores/authStore'
import { lightThemeConfig } from '@/theme/themeConfig'
import AppLayout from '@/components/Layout/AppLayout'
import Login from '@/pages/Login'
import Register from '@/pages/Register'
import ChatView from '@/pages/Chat'

function PrivateRoute({ children }: { children: React.ReactNode }) {
  const token = useAuthStore((s) => s.token)
  if (!token) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <ConfigProvider theme={lightThemeConfig}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/register" element={<Register />} />
          <Route
            path="/"
            element={
              <PrivateRoute>
                <AppLayout />
              </PrivateRoute>
            }
          >
            <Route index element={<ChatView />} />
            <Route path="chat" element={<ChatView />} />
            <Route path="chat/:conversationId" element={<ChatView />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </ConfigProvider>
  )
}
