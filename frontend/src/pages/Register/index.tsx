import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { Form, Input, Button, Typography, Checkbox, message, ConfigProvider } from 'antd'
import { UserOutlined, LockOutlined, MailOutlined } from '@ant-design/icons'
import { authApi } from '@/api/auth'
import { lightThemeConfig } from '@/theme/themeConfig'

const { Title, Text } = Typography

export default function Register() {
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  const onFinish = async (values: any) => {
    setLoading(true)
    try {
      await authApi.register({
        email: values.email,
        username: values.username,
        password: values.password,
        research_consent: values.research_consent || false,
      })
      message.success('注册成功，请登录')
      navigate('/login')
    } catch (err: any) {
      message.error(err.response?.data?.detail || '注册失败')
    } finally {
      setLoading(false)
    }
  }

  return (
    <ConfigProvider theme={lightThemeConfig}>
      <div className="auth-page">
        <div className="auth-card" style={{ width: 440 }}>
          <div style={{ textAlign: 'center', marginBottom: 24 }}>
            <div style={{
              width: 56, height: 56, borderRadius: 14, margin: '0 auto 16px',
              background: 'linear-gradient(135deg, #4f46e5, #7c3aed)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: 24, color: '#fff', fontWeight: 700,
              boxShadow: '0 4px 16px rgba(79,70,229,0.2)',
            }}>
              D
            </div>
            <Title level={3} style={{ marginBottom: 4, color: '#1e293b' }}>注册账号</Title>
            <Text style={{ color: '#64748b' }}>创建你的 Data Agent 账号</Text>
          </div>

          <Form layout="vertical" onFinish={onFinish} size="large">
            <Form.Item name="email" rules={[{ required: true, message: '请输入邮箱' }, { type: 'email', message: '邮箱格式不正确' }]}>
              <Input prefix={<MailOutlined style={{ color: '#94a3b8' }} />} placeholder="邮箱" />
            </Form.Item>
            <Form.Item name="username" rules={[{ required: true, message: '请输入用户名' }, { min: 2, message: '用户名至少2个字符' }]}>
              <Input prefix={<UserOutlined style={{ color: '#94a3b8' }} />} placeholder="用户名" />
            </Form.Item>
            <Form.Item name="password" rules={[{ required: true, message: '请输入密码' }, { min: 6, message: '密码至少6个字符' }]}>
              <Input.Password prefix={<LockOutlined style={{ color: '#94a3b8' }} />} placeholder="密码" />
            </Form.Item>
            <Form.Item
              name="confirm"
              dependencies={['password']}
              rules={[
                { required: true, message: '请确认密码' },
                ({ getFieldValue }) => ({
                  validator(_, value) {
                    if (!value || getFieldValue('password') === value) return Promise.resolve()
                    return Promise.reject(new Error('两次密码不一致'))
                  },
                }),
              ]}
            >
              <Input.Password prefix={<LockOutlined style={{ color: '#94a3b8' }} />} placeholder="确认密码" />
            </Form.Item>
            <Form.Item name="agreement" valuePropName="checked" rules={[{ validator: (_, v) => v ? Promise.resolve() : Promise.reject('请同意用户协议') }]}>
              <Checkbox>我已阅读并同意 <a style={{ color: '#4f46e5' }}>用户协议</a> 和 <a style={{ color: '#4f46e5' }}>隐私政策</a></Checkbox>
            </Form.Item>
            <Form.Item>
              <Button type="primary" htmlType="submit" loading={loading} block style={{ height: 44 }}>注册</Button>
            </Form.Item>
          </Form>

          <div style={{ textAlign: 'center' }}>
            <Text style={{ color: '#64748b' }}>
              已有账号？<Link to="/login" style={{ color: '#4f46e5' }}>立即登录</Link>
            </Text>
          </div>
        </div>
      </div>
    </ConfigProvider>
  )
}
