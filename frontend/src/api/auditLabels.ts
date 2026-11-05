export const ACTION_LABELS: Record<string, string> = {
  'auth.login': '登录',
  'auth.logout': '退出登录',
  'auth.password.change': '修改密码',
  'user.create': '创建用户',
  'user.update': '更新用户',
  'user.password.reset': '重置密码',
  'user.delete': '删除用户',
  'dataset.upload': '上传数据集',
  'dataset.delete': '删除数据集',
  'document.upload': '上传文档',
  'document.delete': '删除文档',
  'report.export': '导出报表',
  'report.share.create': '创建分享链接',
  'report.share.revoke': '撤销分享链接',
  'report.view.create': '保存报表视图',
  'report.view.delete': '删除报表视图',
}

export const ACTION_OPTIONS = Object.entries(ACTION_LABELS).map(([value, label]) => ({
  value,
  label,
}))

export function actionLabel(action: string): string {
  return ACTION_LABELS[action] ?? action
}

export function formatTime(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN', { hour12: false })
}
