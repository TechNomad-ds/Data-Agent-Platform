import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { Form, Input, Button, Typography, Checkbox, Modal, message, ConfigProvider } from 'antd'
import { UserOutlined, LockOutlined, MailOutlined } from '@ant-design/icons'
import { authApi } from '@/api/auth'
import { lightThemeConfig } from '@/theme/themeConfig'
import { useIsMobile } from '@/hooks/useIsMobile'
import AuthBrand from '@/components/Layout/AuthBrand'
import { colors } from '@/styles/tokens'

const { Title, Text, Paragraph } = Typography

export default function Register() {
  const [loading, setLoading] = useState(false)
  const [legalOpen, setLegalOpen] = useState(false)
  const navigate = useNavigate()
  const isMobile = useIsMobile()

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
      <div style={{ display: 'flex', minHeight: '100vh' }}>
        {!isMobile && <AuthBrand />}

        <div
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'center',
            padding: isMobile ? '24px 20px' : '36px 72px',
            background: '#ffffff',
            overflowY: 'auto',
          }}
        >
          <div style={{ maxWidth: 380, width: '100%', margin: '0 auto' }}>
            {isMobile && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 24 }}>
                <div style={{
                  width: 36, height: 36, borderRadius: 11,
                  background: `linear-gradient(135deg, ${colors.primary}, #7c3aed)`,
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                }}>
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
                    <path d="M12 2.5L13.5 9L20 10.5L13.5 12L12 18.5L10.5 12L4 10.5L10.5 9L12 2.5Z" fill="#ffffff" />
                  </svg>
                </div>
                <span style={{ fontSize: 18, fontWeight: 600, color: colors.textPrimary, letterSpacing: -0.2 }}>DataMind</span>
              </div>
            )}
            <div style={{ marginBottom: 28 }}>
              <Title level={3} style={{ marginBottom: 6, color: colors.textPrimary, fontWeight: 600, letterSpacing: -0.3 }}>
                创建 DataMind 账号
              </Title>
              <Text style={{ color: colors.textMuted, fontSize: 14 }}>
                注册以开始数据分析
              </Text>
            </div>

            <Form layout="vertical" onFinish={onFinish} size="large">
              <Form.Item
                name="email"
                rules={[
                  { required: true, message: '请输入邮箱' },
                  { type: 'email', message: '邮箱格式不正确' },
                ]}
              >
                <Input prefix={<MailOutlined style={{ color: colors.textMuted }} />} placeholder="邮箱" autoComplete="email" />
              </Form.Item>
              <Form.Item
                name="username"
                rules={[
                  { required: true, message: '请输入用户名' },
                  { min: 2, message: '用户名至少 2 个字符' },
                ]}
              >
                <Input prefix={<UserOutlined style={{ color: colors.textMuted }} />} placeholder="用户名" autoComplete="username" />
              </Form.Item>
              <Form.Item
                name="password"
                rules={[
                  { required: true, message: '请输入密码' },
                  { min: 8, message: '密码至少 8 个字符' },
                ]}
              >
                <Input.Password prefix={<LockOutlined style={{ color: colors.textMuted }} />} placeholder="密码" autoComplete="new-password" />
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
                <Input.Password prefix={<LockOutlined style={{ color: colors.textMuted }} />} placeholder="确认密码" autoComplete="new-password" />
              </Form.Item>
              <Form.Item
                name="agreement"
                valuePropName="checked"
                rules={[{ validator: (_, v) => v ? Promise.resolve() : Promise.reject('请同意用户协议与隐私政策') }]}
              >
                <Checkbox>
                  我已阅读并同意{' '}
                  <a onClick={(e) => { e.preventDefault(); setLegalOpen(true) }} style={{ color: colors.primary }}>
                    用户协议与隐私政策
                  </a>
                </Checkbox>
              </Form.Item>
              <Form.Item name="research_consent" valuePropName="checked" style={{ marginTop: -8 }}>
                <Checkbox>
                  同意将匿名化后的交互数据用于产品改进与学术研究
                </Checkbox>
              </Form.Item>
              <Form.Item style={{ marginBottom: 16 }}>
                <Button type="primary" htmlType="submit" loading={loading} block style={{ height: 44, fontWeight: 500 }}>
                  注册
                </Button>
              </Form.Item>
            </Form>

            <div style={{ textAlign: 'center', fontSize: 13.5 }}>
              <Text style={{ color: colors.textMuted }}>
                已有账号？
                <Link to="/login" style={{ color: colors.primary, fontWeight: 500, marginLeft: 4 }}>立即登录</Link>
              </Text>
            </div>
          </div>
        </div>
      </div>

      <Modal
        title="用户协议与隐私政策"
        open={legalOpen}
        onCancel={() => setLegalOpen(false)}
        footer={<Button type="primary" onClick={() => setLegalOpen(false)}>我已知悉</Button>}
        width={640}
        centered
        styles={{ body: { maxHeight: '60vh', overflow: 'auto' } }}
      >
        <LegalContent />
      </Modal>
    </ConfigProvider>
  )
}

function LegalContent() {
  return (
    <div style={{ fontSize: 13.5, lineHeight: 1.8, color: colors.textSecondary }}>
      <Title level={4}>一、服务说明</Title>
      <Paragraph>
        DataMind Analyst（以下简称"本平台"）是一个基于人工智能的数据分析平台，提供数据上传、智能对话分析、可视化图表生成等服务。注册或使用本平台即表示您同意接受本协议的全部条款。
      </Paragraph>
      <Title level={4}>二、账户与安全</Title>
      <Paragraph>
        注册时请提供真实、准确的信息，并妥善保管账户密码。因个人保管不当导致的安全问题由您自行承担。每位用户限注册一个账户，平台有权对异常注册行为进行限制。
      </Paragraph>
      <Title level={4}>三、数据与隐私</Title>
      <Paragraph>
        您上传的数据文件归您所有。平台采用用户隔离存储，密码经加盐哈希处理，敏感凭据加密保存。我们不会未经授权访问、使用或向第三方披露您的数据，亦不会将您的信息出售或出租。
      </Paragraph>
      <Paragraph>
        使用分析功能时，相关数据会发送至 AI 模型进行处理。若您配置了自有 API Key，数据将直接发送至您指定的服务端点，平台不做中转。
      </Paragraph>
      <Title level={4}>四、使用规范</Title>
      <Paragraph>请确保上传的数据合法合规、不侵犯他人权益。禁止利用本平台从事违法活动、反向工程或恶意攻击。</Paragraph>
      <Title level={4}>五、AI 分析免责</Title>
      <Paragraph>AI 分析结果由大语言模型生成，仅供参考，不构成任何专业建议。内容可能存在偏差，请在做出重要决策前自行核实关键信息。</Paragraph>
      <Title level={4}>六、额度</Title>
      <Paragraph>平台为每位用户提供每日免费分析额度，也支持配置自有 API Key 使用，后者不消耗平台额度，费用由对应服务商收取。</Paragraph>
      <Title level={4}>七、学术研究</Title>
      <Paragraph>只有在您主动勾选授权后，您的交互数据才会在匿名化处理后用于产品改进与学术研究。您可以在个人资料中调整该授权。</Paragraph>
      <Title level={4}>八、数据删除与账户注销</Title>
      <Paragraph>您可随时删除项目、文件或对话记录，删除操作不可撤销。账户注销后，所有关联数据将被永久清除。</Paragraph>
      <Title level={4}>九、协议修订</Title>
      <Paragraph>本平台保留修订本协议的权利，修订后将在平台公布。继续使用即视为同意修订内容。涉及重大变更时，我们将以显著方式另行通知。</Paragraph>
    </div>
  )
}
