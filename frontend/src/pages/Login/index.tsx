import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { Form, Input, Button, Typography, message, ConfigProvider } from 'antd'
import { LockOutlined, MailOutlined } from '@ant-design/icons'
import { authApi } from '@/api/auth'
import { useAuthStore } from '@/stores/authStore'
import { lightThemeConfig } from '@/theme/themeConfig'

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
      <div className="auth-page">
        <div className="auth-card">
          <div style={{ textAlign: 'center', marginBottom: 32 }}>
            <div style={{
              width: 56, height: 56, borderRadius: 14, margin: '0 auto 16px',
              background: 'linear-gradient(135deg, #4f46e5, #7c3aed)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 24, color: '#fff', fontWeight: 700,
              boxShadow: '0 4px 16px rgba(79,70,229,0.2)',
            }}>
              D
            </div>
            <Title level={3} style={{ marginBottom: 4, color: '#1e293b' }}>
              Data Agent Platform
            </Title>
            <Text style={{ color: '#64748b' }}>智能数据交互平台</Text>
          </div>

          <Form layout="vertical" onFinish={onFinish} size="large">
            <Form.Item name="email" rules={[{ required: true, message: '请输入邮箱' }, { type: 'email', message: '邮箱格式不正确' }]}>
              <Input prefix={<MailOutlined style={{ color: '#94a3b8' }} />} placeholder="邮箱" />
            </Form.Item>
            <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }]}>
              <Input.Password prefix={<LockOutlined style={{ color: '#94a3b8' }} />} placeholder="密码" />
            </Form.Item>
            <Form.Item>
              <Button type="primary" htmlType="submit" loading={loading} block style={{ height: 44 }}>
                登录
              </Button>
            </Form.Item>
          </Form>

          <div style={{ textAlign: 'center' }}>
            <Text style={{ color: '#64748b' }}>
              还没有账号？<Link to="/register" style={{ color: '#4f46e5' }}>立即注册</Link>
            </Text>
          </div>
        </div>
      </div>
    </ConfigProvider>
  )
}
