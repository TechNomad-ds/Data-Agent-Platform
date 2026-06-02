import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { Form, Input, Button, Typography, message, ConfigProvider } from 'antd'
import { LockOutlined, MailOutlined } from '@ant-design/icons'
import { authApi } from '@/api/auth'
import { useAuthStore } from '@/stores/authStore'
import { lightThemeConfig } from '@/theme/themeConfig'
import AuthBrand from '@/components/Layout/AuthBrand'
import { colors } from '@/styles/tokens'

const { Title, Text } = Typography

export default function Login() {
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const { setTokens, fetchUser } = useAuthStore()

  const onFinish = async (values: { email: string; password: string }) => {
    setLoading(true)
    try {
      const res = await authApi.login(values)
      setTokens(res.data.access_token, res.data.refresh_token)
      await fetchUser()
      message.success('登录成功')
      navigate('/')
    } catch (err: any) {
      message.error(err.response?.data?.detail || '登录失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <ConfigProvider theme={lightThemeConfig}>
      <div style={{ display: 'flex', minHeight: '100vh' }}>
        <AuthBrand />

        <div
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'center',
            padding: '48px 72px',
            background: '#ffffff',
          }}
        >
          <div style={{ maxWidth: 380, width: '100%', margin: '0 auto' }}>
            <div style={{ marginBottom: 36 }}>
              <Title level={3} style={{ marginBottom: 6, color: colors.textPrimary, fontWeight: 600, letterSpacing: -0.3 }}>
                欢迎使用 DataMind
              </Title>
              <Text style={{ color: colors.textMuted, fontSize: 14 }}>
                登录以开始数据分析
              </Text>
            </div>

            <Form layout="vertical" onFinish={onFinish} size="large">
              <Form.Item
                name="email"
                rules={[{ required: true, message: '请输入邮箱或用户名' }]}
              >
                <Input prefix={<MailOutlined style={{ color: colors.textMuted }} />} placeholder="邮箱或用户名" autoComplete="email" />
              </Form.Item>
              <Form.Item
                name="password"
                rules={[{ required: true, message: '请输入密码' }]}
              >
                <Input.Password prefix={<LockOutlined style={{ color: colors.textMuted }} />} placeholder="密码" autoComplete="current-password" />
              </Form.Item>
              <Form.Item style={{ marginBottom: 16 }}>
                <Button type="primary" htmlType="submit" loading={loading} block style={{ height: 44, fontWeight: 500 }}>
                  登录
                </Button>
              </Form.Item>
            </Form>

            <div style={{ textAlign: 'center', fontSize: 13.5 }}>
              <Text style={{ color: colors.textMuted }}>
                还没有账号？
                <Link to="/register" style={{ color: colors.primary, fontWeight: 500, marginLeft: 4 }}>立即注册</Link>
              </Text>
            </div>
          </div>
        </div>
      </div>
    </ConfigProvider>
  )
}
