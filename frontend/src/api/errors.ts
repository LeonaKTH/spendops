/** 带 HTTP 状态码的错误，便于页面对 409 等场景做分支处理。 */
export class ApiError extends Error {
  readonly status: number

  constructor(message: string, status: number) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}
