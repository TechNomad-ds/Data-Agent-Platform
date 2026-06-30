/**
 * 飞书渠道配置表单：App ID + App Secret + 可选 Encrypt Key / Verification Token。
 * 逻辑复用 CredentialChannelForm，本文件只声明字段。
 */
import { type ChannelStatus } from '@/api/channels'
import CredentialChannelForm from './CredentialChannelForm'

interface Props {
  status: ChannelStatus | null
  onStatusChange: (s: ChannelStatus) => void
}

export default function LarkForm(props: Props) {
  return (
    <CredentialChannelForm
      channelId="lark"
      channelLabel="飞书"
      fields={[
        { name: 'app_id', label: 'App ID', placeholder: 'cli_xxxxxxxxxxxxxxxx' },
        { name: 'app_secret', label: 'App Secret', placeholder: 'App Secret', password: true },
      ]}
      optionalFields={[
        { name: 'encrypt_key', label: 'Encrypt Key（WS 模式可不填）', placeholder: '可选' },
        { name: 'verification_token', label: 'Verification Token（WS 模式可不填）', placeholder: '可选' },
      ]}
      optionalLabel="显示可选配置（Encrypt Key / Verification Token）"
      {...props}
    />
  )
}
