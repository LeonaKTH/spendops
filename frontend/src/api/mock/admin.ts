import type {
  AdminOverview,
  AuditLogItem,
  AuditLogParams,
  AuthUser,
  CreateUserInput,
  ListUsersParams,
  Paginated,
  Role,
  UpdateUserInput,
} from '../types'
import { MOCK_DATASETS } from './data'
import {
  MOCK_AUDIT_KEY,
  readUsers,
  recordAudit,
  requireAdminRecord,
  toAuthUser,
  writeUsers,
  type MockAuditRecord,
  type MockUserRecord,
} from './auth'

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))
const DATASET_KEY = 'procurebi.mock.datasets'
const HIDDEN_KEY = 'procurebi.mock.hidden'
const DOCUMENT_KEY = 'procurebi.mock.documents'

const USERNAME_RE = /^[a-z0-9_.-]{3,32}$/
const ROLES: Role[] = ['admin', 'viewer']

function readJson<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : fallback
  } catch {
    return fallback
  }
}

function paginate<T>(items: T[], page: number, pageSize: number): Paginated<T> {
  const safePage = Math.max(1, page)
  const safeSize = Math.max(1, pageSize)
  const start = (safePage - 1) * safeSize
  return {
    items: items.slice(start, start + safeSize),
    total: items.length,
    page: safePage,
    pageSize: safeSize,
  }
}

function activeAdminCount(users: MockUserRecord[]): number {
  return users.filter((item) => item.role === 'admin' && item.isActive).length
}

function validatePassword(password: string) {
  if (!password || !password.trim()) throw new Error('密码不能为空白字符。')
  if (password.length < 8) throw new Error('密码至少 8 个字符。')
  if (new TextEncoder().encode(password).length > 72) {
    throw new Error('密码不能超过 72 字节（约 24 个中文字符）。')
  }
}

function findUser(userId: string): MockUserRecord {
  const user = readUsers().find((item) => item.id === userId)
  if (!user) throw new Error('用户不存在。')
  return user
}

function replaceUser(updated: MockUserRecord) {
  writeUsers(readUsers().map((item) => (item.id === updated.id ? updated : item)))
}

export async function getAdminOverview(): Promise<AdminOverview> {
  await sleep(220)
  requireAdminRecord()

  const users = readUsers()
  const hidden = new Set(readJson<string[]>(HIDDEN_KEY, []))
  const storedDatasets = readJson<unknown[]>(DATASET_KEY, [])
  const datasets = storedDatasets.length + MOCK_DATASETS.filter((item) => !hidden.has(item.id)).length
  const documents = readJson<unknown[]>(DOCUMENT_KEY, []).length
  const audit = readJson<MockAuditRecord[]>(MOCK_AUDIT_KEY, [])
  const since = Date.now() - 24 * 60 * 60 * 1000

  return {
    users: users.length,
    activeUsers: users.filter((item) => item.isActive).length,
    admins: activeAdminCount(users),
    datasets,
    activeDatasets: datasets,
    documents,
    auditEvents24h: audit.filter((item) => Date.parse(item.createdAt) >= since).length,
    recentAudit: audit.slice(0, 10) as AuditLogItem[],
  }
}

export async function listUsers(params: ListUsersParams = {}): Promise<Paginated<AuthUser>> {
  await sleep(180)
  requireAdminRecord()

  const keyword = params.q?.trim().toLowerCase() ?? ''
  const filtered = readUsers()
    .filter((item) => {
      if (keyword && !`${item.username} ${item.displayName}`.toLowerCase().includes(keyword)) {
        return false
      }
      if (params.role && item.role !== params.role) return false
      if (params.isActive !== undefined && item.isActive !== params.isActive) return false
      return true
    })
    .sort((a, b) => b.createdAt.localeCompare(a.createdAt))

  const result = paginate(filtered, params.page ?? 1, params.pageSize ?? 20)
  return { ...result, items: result.items.map(toAuthUser) }
}

export async function createUser(input: CreateUserInput): Promise<AuthUser> {
  await sleep(260)
  const actor = requireAdminRecord()

  const username = input.username.trim().toLowerCase()
  if (!USERNAME_RE.test(username)) {
    throw new Error('用户名需为 3-32 位字母、数字、下划线、点或短横线。')
  }
  if (!ROLES.includes(input.role)) throw new Error('角色只能是 admin 或 viewer。')
  validatePassword(input.password)

  const users = readUsers()
  if (users.some((item) => item.username === username)) throw new Error('用户名已存在。')

  const created: MockUserRecord = {
    id: `u-${Date.now()}`,
    username,
    password: input.password,
    displayName: input.displayName?.trim() || username,
    role: input.role,
    isActive: true,
    mustChangePassword: true,
    lastLoginAt: null,
    createdAt: new Date().toISOString(),
  }
  writeUsers([...users, created])
  recordAudit(actor, 'user.create', {
    targetType: 'user',
    targetId: created.id,
    detail: { username: created.username, role: created.role },
  })
  return toAuthUser(created)
}

export async function updateUser(id: string, input: UpdateUserInput): Promise<AuthUser> {
  await sleep(220)
  const actor = requireAdminRecord()
  const target = findUser(id)
  const users = readUsers()
  const isSelf = actor.id === target.id

  if (input.isActive === false && target.isActive) {
    if (isSelf) throw new Error('不能停用当前登录的管理员账号。')
    if (target.role === 'admin' && activeAdminCount(users) <= 1) {
      throw new Error('系统至少需要保留一个启用状态的管理员。')
    }
  }
  if (input.role === 'viewer' && target.role === 'admin') {
    if (isSelf) throw new Error('不能降级当前登录的管理员账号。')
    if (activeAdminCount(users) <= 1) {
      throw new Error('系统至少需要保留一个启用状态的管理员。')
    }
  }

  const changed: string[] = []
  if (input.displayName !== undefined) {
    target.displayName = input.displayName.trim().slice(0, 100)
    changed.push('display_name')
  }
  if (input.role !== undefined && input.role !== target.role) {
    target.role = input.role
    changed.push('role')
  }
  if (input.isActive !== undefined && input.isActive !== target.isActive) {
    target.isActive = input.isActive
    changed.push('is_active')
  }

  replaceUser(target)
  recordAudit(actor, 'user.update', {
    targetType: 'user',
    targetId: target.id,
    detail: { username: target.username, changed },
  })
  return toAuthUser(target)
}

export async function resetUserPassword(id: string, newPassword: string): Promise<void> {
  await sleep(240)
  const actor = requireAdminRecord()
  const target = findUser(id)
  if (target.id === actor.id) throw new Error('请使用「修改密码」修改自己的密码。')
  validatePassword(newPassword)

  target.password = newPassword
  target.mustChangePassword = true
  replaceUser(target)
  recordAudit(actor, 'user.password.reset', {
    targetType: 'user',
    targetId: target.id,
    detail: { username: target.username },
  })
}

export async function deleteUser(id: string): Promise<void> {
  await sleep(220)
  const actor = requireAdminRecord()
  const target = findUser(id)
  if (target.id === actor.id) throw new Error('不能删除当前登录的账号。')
  if (target.role === 'admin' && target.isActive && activeAdminCount(readUsers()) <= 1) {
    throw new Error('系统至少需要保留一个启用状态的管理员。')
  }

  writeUsers(readUsers().filter((item) => item.id !== target.id))
  recordAudit(actor, 'user.delete', {
    targetType: 'user',
    targetId: target.id,
    detail: { username: target.username },
  })
}

export async function listAuditLogs(
  params: AuditLogParams = {},
): Promise<Paginated<AuditLogItem>> {
  await sleep(200)
  requireAdminRecord()

  const actor = params.actor?.trim().toLowerCase() ?? ''
  const start = params.start ? Date.parse(params.start) : null
  const end = params.end ? Date.parse(params.end) : null

  const filtered = readJson<MockAuditRecord[]>(MOCK_AUDIT_KEY, []).filter((item) => {
    if (params.action && item.action !== params.action) return false
    if (params.status && item.status !== params.status) return false
    if (actor && !item.actorUsername.toLowerCase().includes(actor)) return false
    if (start !== null && Date.parse(item.createdAt) < start) return false
    if (end !== null && Date.parse(item.createdAt) > end) return false
    return true
  })

  return paginate(filtered, params.page ?? 1, params.pageSize ?? 20)
}
