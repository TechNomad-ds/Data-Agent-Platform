/**
 * 钉钉渠道配置表单：Client ID + Client Secret。
 * 逻辑复用 CredentialChannelForm，本文件只声明字段。
 */
import { type ChannelStatus } from '@/api/channels'
import CredentialChannelForm from './CredentialChannelForm'

interface Props {
  status: ChannelStatus | null
  onStatusChange: (s: ChannelStatus) => void
}

export default function DingTalkForm(props: Props) {
  return (
    <CredentialChannelForm
      channelId="dingtalk"
      channelLabel="钉钉"
      fields={[
        { name: 'client_id', label: 'Client ID', placeholder: 'ding_xxxxxxxxxxxxxxxx' },
        { name: 'client_secret', label: 'Client Secret', placeholder: 'Client Secret', password: true },
      ]}
      {...props}
    />
  )
}
