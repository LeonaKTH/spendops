import 'vue-router'

declare module 'vue-router' {
  interface RouteMeta {
    title?: string
    /** 无需登录即可访问。 */
    public?: boolean
    /** 已登录用户也可以留在该公开页面（例如分享报表）。 */
    allowAuthenticated?: boolean
    /** 仅管理员可访问。 */
    requiresAdmin?: boolean
  }
}

export {}
