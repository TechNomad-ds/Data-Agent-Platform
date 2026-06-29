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
  // 现代明丽：柔和的彩色投影，用于卡片 hover / 主操作区，制造轻盈的浮起感
  soft: '0 4px 16px rgba(79, 70, 229, 0.08)',
  softLg: '0 12px 32px rgba(79, 70, 229, 0.12)',
  card: '0 1px 3px rgba(15, 23, 42, 0.05), 0 1px 2px rgba(15, 23, 42, 0.03)',
  cardHover: '0 10px 28px rgba(15, 23, 42, 0.10)',
}

// 柔渐变：现代明丽风的核心装饰手段（克制、低饱和，不俗气）
export const gradient = {
  // 品牌主渐变 — 用于主图标块/强调区
  brand: 'linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%)',
  brandSoft: 'linear-gradient(135deg, #eef2ff 0%, #f5f3ff 100%)',
  // 页面/区域柔背景
  pageWash: 'linear-gradient(180deg, #fbfbfd 0%, #ffffff 140px)',
  uploadIdle: 'linear-gradient(135deg, #f7f8ff 0%, #fdf7ff 100%)',
  uploadHover: 'linear-gradient(135deg, #eef1ff 0%, #f8edff 100%)',
}

// 文件类型的柔和配色：{ color 文本/图标主色, bg 浅底, grad 柔渐变底 }
// 用于文件图标块，比纯色块更精致。
export function fileTypePalette(hex: string) {
  return {
    color: hex,
    bg: `${hex}14`,
    grad: `linear-gradient(135deg, ${hex}1f 0%, ${hex}0d 100%)`,
  }
}

