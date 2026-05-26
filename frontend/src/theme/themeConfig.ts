import { theme, ThemeConfig } from 'antd'

export const lightThemeConfig: ThemeConfig = {
  algorithm: theme.defaultAlgorithm,
  token: {
    colorPrimary: '#4f46e5',
    colorBgContainer: '#ffffff',
    colorBgElevated: '#ffffff',
    colorBgLayout: '#f8fafc',
    colorBorder: '#e2e8f0',
    colorBorderSecondary: '#f1f5f9',
    colorText: '#1e293b',
    colorTextSecondary: '#64748b',
    colorTextTertiary: '#94a3b8',
    borderRadius: 10,
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif',
  },
  components: {
    Button: {
      primaryColor: '#fff',
      colorPrimaryHover: '#6366f1',
    },
    Input: {
      colorBgContainer: '#ffffff',
      colorBorder: '#e2e8f0',
      activeBorderColor: '#4f46e5',
    },
    Select: {
      colorBgContainer: '#ffffff',
      colorBorder: '#e2e8f0',
      optionSelectedBg: '#f1f5f9',
    },
    Modal: {
      contentBg: '#ffffff',
      headerBg: '#ffffff',
    },
    Dropdown: {
      colorBgElevated: '#ffffff',
    },
  },
}
