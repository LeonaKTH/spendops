import * as real from './client'
import * as mock from './mock'

const useMock = import.meta.env.VITE_USE_MOCK !== 'false'

// 编译期校验：Mock 模式必须实现真实 API 的全部方法，漏一个都会构建失败。
export const _mockParity: typeof real = mock

export const api = useMock ? mock : real

export const USING_MOCK = useMock
