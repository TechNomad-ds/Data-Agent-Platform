import { theme, ThemeConfig } from 'antd'
import { colors, radius } from '@/styles/tokens'

// 大屏（≥1680px）上适度放大 Ant 基础字号与控件高度。
// 注意：matchMedia 只在模块加载时求值一次，跨断点缩放窗口后需刷新才会生效。
const isLargeScreen =
  typeof window !== 'undefined' &&
  typeof window.matchMedia === 'function' &&
  window.matchMedia('(min-width: 1680px)').matches

export const lightThemeConfig: ThemeConfig = {
  algorithm: theme.defaultAlgorithm,
  token: {
    colorPrimary: colors.primary,
    colorBgContainer: colors.surface,
    colorBgElevated: colors.surface,
    colorBgLayout: colors.bg,
    colorBorder: colors.border,
    colorBorderSecondary: colors.borderLight,
    colorText: colors.textPrimary,
    colorTextSecondary: colors.textSecondary,
    colorTextTertiary: colors.textMuted,
    colorTextPlaceholder: colors.textPlaceholder,
    colorSuccess: colors.success,
    colorError: colors.error,
    colorWarning: colors.warning,
    borderRadius: radius.md,
    borderRadiusLG: radius.lg,
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif',
    fontSize: isLargeScreen ? 15 : 14,
    controlHeight: isLargeScreen ? 40 : 36,
    wireframe: false,
  },
  components: {
    Button: {
      primaryColor: '#fff',
      colorPrimaryHover: colors.primaryHover,
      borderRadius: radius.md,
      fontWeight: 500,
    },
    Input: {
      colorBgContainer: colors.surface,
      colorBorder: colors.border,
      activeBorderColor: colors.primary,
      hoverBorderColor: colors.borderStrong,
      borderRadius: radius.md,
    },
    Select: {
      colorBgContainer: colors.surface,
      colorBorder: colors.border,
      optionSelectedBg: colors.primarySoft,
      borderRadius: radius.md,
    },
    Modal: {
      contentBg: colors.surface,
      headerBg: colors.surface,
      borderRadiusLG: radius.lg,
    },
    Dropdown: {
      colorBgElevated: colors.surface,
      borderRadiusLG: radius.md,
    },
    Card: {
      colorBorderSecondary: colors.border,
      borderRadiusLG: radius.lg,
    },
    Tooltip: {
      colorBgSpotlight: '#1f2328',
      borderRadius: radius.sm,
    },
    Tag: {
      borderRadiusSM: radius.sm,
    },
  },
}
