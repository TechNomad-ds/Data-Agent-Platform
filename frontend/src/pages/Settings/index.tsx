import { useState, useEffect } from 'react'
import { Typography, Card, Button, Form, Input, Modal, message } from 'antd'
import { UserOutlined, LockOutlined } from '@ant-design/icons'
import { authApi } from '@/api/auth'
import { useAuthStore } from '@/stores/authStore'

const { Title, Text } = Typography

export default function SettingsPage() {
  const [profileForm] = Form.useForm()
  const [passwordForm] = Form.useForm()
  const [passwordModalOpen, setPasswordModalOpen] = useState(false)
  const { user, fetchUser } = useAuthStore()

  useEffect(() => {
    if (user) {
      profileForm.setFieldsValue({
        username: user.username,
        email: user.email,
      })
    }
  }, [user])

  const handleProfileUpdate = async (values: { username: string }) => {
    try {
      await authApi.updateProfile({
        username: values.username,
      })
      message.success('资料已更新')
      await fetchUser()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '更新失败')
    }
  }

  const handleChangePassword = async (values: { old_password: string; new_password: string; confirm_password: string }) => {
    if (values.new_password !== values.confirm_password) {
      message.error('两次输入的新密码不一致')
      return
    }
    try {
      await authApi.changePassword(values.old_password, values.new_password)
      message.success('密码已修改')
      setPasswordModalOpen(false)
      passwordForm.resetFields()
    } catch (err: any) {
      message.error(err.response?.data?.detail || '修改失败')
    }
  }

  return (
    <div style={{ height: '100vh', overflow: 'auto', background: '#f8fafc', padding: 32 }}>
      <div style={{ maxWidth: 600, margin: '0 auto' }}>
        <Title level={3} style={{ marginBottom: 8 }}>设置</Title>
        <Text type="secondary" style={{ display: 'block', marginBottom: 24 }}>
          管理你的账户信息
        </Text>

        <Card
          title={<span><UserOutlined style={{ marginRight: 8 }} />账户信息</span>}
          extra={
            <Button icon={<LockOutlined />} onClick={() => setPasswordModalOpen(true)}>
              修改密码
            </Button>
          }
        >
          <Form
            form={profileForm}
            layout="vertical"
            onFinish={handleProfileUpdate}
            style={{ maxWidth: 400 }}
          >
            <Form.Item label="邮箱" name="email">
              <Input disabled />
            </Form.Item>
            <Form.Item
              label="用户名"
              name="username"
              rules={[
                { required: true, message: '请输入用户名' },
                { min: 2, message: '至少 2 个字符' },
              ]}
            >
              <Input />
            </Form.Item>
            <Form.Item>
              <Button type="primary" htmlType="submit">保存</Button>
            </Form.Item>
          </Form>
          {user && (
            <div style={{ fontSize: 12, color: '#94a3b8', marginTop: 8 }}>
              角色: {user.role === 'admin' ? '管理员' : '普通用户'} | 注册时间: {new Date(user.created_at).toLocaleDateString('zh-CN')}
            </div>
          )}
        </Card>
      </div>

      <Modal
        title="修改密码"
        open={passwordModalOpen}
        onCancel={() => { setPasswordModalOpen(false); passwordForm.resetFields() }}
        onOk={() => passwordForm.submit()}
        okText="确认修改"
        cancelText="取消"
      >
        <Form form={passwordForm} layout="vertical" onFinish={handleChangePassword}>
          <Form.Item name="old_password" label="当前密码" rules={[{ required: true, message: '请输入当前密码' }]}>
            <Input.Password placeholder="输入当前密码" />
          </Form.Item>
          <Form.Item name="new_password" label="新密码" rules={[
            { required: true, message: '请输入新密码' },
            { min: 6, message: '至少 6 个字符' },
          ]}>
            <Input.Password placeholder="输入新密码" />
          </Form.Item>
          <Form.Item name="confirm_password" label="确认新密码" rules={[{ required: true, message: '请确认新密码' }]}>
            <Input.Password placeholder="再次输入新密码" />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  )
}
