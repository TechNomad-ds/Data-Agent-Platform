// 设计令牌：贴近 ChatGPT / Claude 的中性灰阶 + 单一主色
// 整体策略：去除所有廉价渐变，靠克制的颜色与层次感塑造专业感
export const colors = {
  // 品牌主色 — 仍保留 indigo 作为产品识别，但只用于交互态而非装饰
  primary: '#4f46e5',
  primaryLight: '#eef2ff',
  primaryHover: '#4338ca',
  primarySoft: '#f5f3ff',

  // 中性面板（ChatGPT 风：主区纯白，侧栏极浅灰）
  bg: '#ffffff',
  bgSubtle: '#f7f7f8',     // 侧栏底色
  bgMuted: '#fafafa',      // 卡片悬浮态
  surface: '#ffffff',
  surfaceAlt: '#f9fafb',

  // 边框 — 极浅，避免硬切割感
  border: '#ececf1',
  borderStrong: '#d9d9e3',
  borderLight: '#f4f4f5',

  // 文本（贴近 OpenAI 文档站点的层次）
  textPrimary: '#1f2328',
  textSecondary: '#4b5563',
  textMuted: '#8e8ea0',
  textPlaceholder: '#acacbe',

  // 状态色
  success: '#10a37f',
  warning: '#f59e0b',
  error: '#ef4444',
  info: '#3b82f6',

  // 消息气泡（用户淡灰，AI 透明，全部去掉紫色描边）
  userBubble: '#f4f4f5',
  userBubbleText: '#1f2328',
  aiBubble: 'transparent',
  aiBorder: 'transparent',

  // 头像
  userAvatar: '#1f2328',
  aiAvatar: '#4f46e5',
}

export const radius = {
  sm: 6,
  md: 10,
  lg: 14,
  xl: 18,
  pill: 999,
}

export const spacing = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
}

export const shadow = {
  none: 'none',
  sm: '0 1px 2px rgba(15, 23, 42, 0.04)',
  md: '0 2px 8px rgba(15, 23, 42, 0.06)',
  lg: '0 8px 24px rgba(15, 23, 42, 0.08)',
  focus: '0 0 0 3px rgba(79, 70, 229, 0.15)',
}
