import type { AuthUser, Role } from '../types'

export const MOCK_USERS_KEY = 'procurebi.mock.users'
export const MOCK_SESSION_KEY = 'procurebi.mock.session'
export const MOCK_AUDIT_KEY = 'procurebi.mock.audit'

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

export interface MockUserRecord {
  id: string
  username: string
  password: string
  displayName: string
  role: Role
  isActive: boolean
  mustChangePassword: boolean
  lastLoginAt: string | null
  createdAt: string
}

export interface MockAuditRecord {
  id: string
  actorUsername: string
  action: string
  targetType: string | null
  targetId: string | null
  status: 'success' | 'failure'
  detail: Record<string, unknown> | null
  ip: string | null
  createdAt: string
}

const DEMO_USERS: MockUserRecord[] = [
  {
    id: 'u-admin',
    username: 'admin',
    password: 'admin123456',
    displayName: '系统管理员',
    role: 'admin',
    isActive: true,
    mustChangePassword: false,
    lastLoginAt: null,
    createdAt: '2026-01-01T00:00:00.000Z',
  },
  {
    id: 'u-viewer',
    username: 'viewer',
    password: 'viewer123456',
    displayName: '演示用户',
    role: 'viewer',
    isActive: true,
    mustChangePassword: false,
    lastLoginAt: null,
    createdAt: '2026-01-02T00:00:00.000Z',
  },
]

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}

function writeJson(key: string, value: unknown) {
  localStorage.setItem(key, JSON.stringify(value))
}

export function readUsers(): MockUserRecord[] {
  const stored = readJson<MockUserRecord[] | null>(MOCK_USERS_KEY, null)
  if (stored && Array.isArray(stored)) return stored
  writeJson(MOCK_USERS_KEY, DEMO_USERS)
  return DEMO_USERS.map((item) => ({ ...item }))
}

export function writeUsers(users: MockUserRecord[]) {
  writeJson(MOCK_USERS_KEY, users)
}

export function toAuthUser(record: MockUserRecord): AuthUser {
  return {
    id: record.id,
    username: record.username,
    displayName: record.displayName || record.username,
    role: record.role,
    isActive: record.isActive,
    mustChangePassword: record.mustChangePassword,
    lastLoginAt: record.lastLoginAt,
    createdAt: record.createdAt,
  }
}

export function currentRecord(): MockUserRecord | null {
  const session = readJson<{ userId?: string } | null>(MOCK_SESSION_KEY, null)
  if (!session?.userId) return null
  return readUsers().find((item) => item.id === session.userId) ?? null
}

export function requireAdminRecord(): MockUserRecord {
  const user = currentRecord()
  if (!user || !user.isActive) throw new Error('未登录或登录已过期。')
  if (user.role !== 'admin') throw new Error('需要管理员权限。')
  return user
}

export function recordAudit(
  actor: MockUserRecord | null,
  action: string,
  options: {
    actorUsername?: string
    targetType?: string | null
    targetId?: string | null
    status?: 'success' | 'failure'
    detail?: Record<string, unknown> | null
    ip?: string | null
  } = {},
) {
  const entries = readJson<MockAuditRecord[]>(MOCK_AUDIT_KEY, [])
  const entry: MockAuditRecord = {
    id: `audit-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    actorUsername: actor?.username ?? options.actorUsername ?? '',
    action,
    targetType: options.targetType ?? null,
    targetId: options.targetId ?? null,
    status: options.status ?? 'success',
    detail: options.detail ?? null,
    ip: options.ip ?? '127.0.0.1',
    createdAt: new Date().toISOString(),
  }
  writeJson(MOCK_AUDIT_KEY, [entry, ...entries].slice(0, 500))
}

function touchLogin(user: MockUserRecord) {
  user.lastLoginAt = new Date().toISOString()
  const users = readUsers().map((item) => (item.id === user.id ? user : item))
  writeUsers(users)
}

export async function login(username: string, password: string): Promise<AuthUser> {
  await sleep(320)
  const normalized = username.trim().toLowerCase()
  const user = readUsers().find((item) => item.username === normalized)

  if (!user || user.password !== password) {
    recordAudit(null, 'auth.login', {
      actorUsername: normalized,
      status: 'failure',
      detail: { reason: 'invalid_credentials' },
    })
    throw new Error('用户名或密码错误。')
  }
  if (!user.isActive) throw new Error('账号已被停用，请联系管理员。')

  touchLogin(user)
  writeJson(MOCK_SESSION_KEY, { userId: user.id })
  recordAudit(user, 'auth.login')
  return toAuthUser(user)
}

export async function logout(): Promise<void> {
  await sleep(120)
  const user = currentRecord()
  localStorage.removeItem(MOCK_SESSION_KEY)
  if (user) recordAudit(user, 'auth.logout')
}

export async function me(): Promise<AuthUser> {
  await sleep(80)
  const user = currentRecord()
  if (!user || !user.isActive) throw new Error('未登录或登录已过期。')
  return toAuthUser(user)
}

export async function changePassword(
  currentPassword: string,
  newPassword: string,
): Promise<AuthUser> {
  await sleep(260)
  const user = currentRecord()
  if (!user) throw new Error('未登录或登录已过期。')
  if (user.password !== currentPassword) throw new Error('当前密码不正确。')
  if (currentPassword === newPassword) throw new Error('新密码不能与当前密码相同。')
  if (newPassword.trim().length < 8) throw new Error('密码至少 8 个字符。')

  user.password = newPassword
  user.mustChangePassword = false
  writeUsers(readUsers().map((item) => (item.id === user.id ? user : item)))
  recordAudit(user, 'auth.password.change')
  return toAuthUser(user)
}
