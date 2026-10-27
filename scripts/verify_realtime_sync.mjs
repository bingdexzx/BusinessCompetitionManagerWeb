// 实时同步端到端验证：登录 → WS 订阅（global + 某比赛）→ HTTP 写入 → 断言收到 resource:changed。
//
// 用途：确认「写接口 → 广播 → WS 推送 → 前端可按资源增量重拉」整条链路在真实部署下通。
// 前置：scripts/run_servers.py 已启动（HTTP 8000 / WS 8001）。
//
// 用法：
//   node scripts\verify_realtime_sync.mjs
//   环境变量：HTTP_BASE / WS_BASE / SYNC_USER / SYNC_PASSWORD / SYNC_CID
//
// 说明：会把探针数据（一个临时用户 + 一个临时区域）创建后删除，不污染业务数据。

const HTTP = process.env.HTTP_BASE || 'http://127.0.0.1:8000'
const WS = process.env.WS_BASE || 'ws://127.0.0.1:8001'
const USER = process.env.SYNC_USER || 'full_admin'
const PASS = process.env.SYNC_PASSWORD || 'FullAdmin12345!'
const CID = Number(process.env.SYNC_CID || '49')

const stamp = Date.now()

function fail(msg) {
  console.error(`FAIL: ${msg}`)
  process.exit(1)
}

async function api(path, { method = 'GET', body, token } = {}) {
  const res = await fetch(`${HTTP}${path}`, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      'X-Competition-Id': String(CID),
    },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  })
  const text = await res.text()
  let json = null
  try { json = text ? JSON.parse(text) : null } catch { /* 非 JSON */ }
  return { status: res.status, json, text }
}

// ---------------------------------------------------------------- 登录
const login = await api('/api/auth/login', {
  method: 'POST',
  body: { username: USER, password: PASS },
})
if (login.status !== 200) fail(`登录失败 ${login.status} ${login.text.slice(0, 200)}`)
const token = login.json.access
console.log(`✓ 登录成功 ${USER} (uid=${login.json?.user?.id})`)

// ---------------------------------------------------------------- WS
const ws = new WebSocket(`${WS}/ws/notifications?token=${encodeURIComponent(token)}`)
const frames = []
const seen = []

function waitFor(pred, label, timeoutMs = 10000) {
  const existing = frames.find(pred)
  if (existing) return Promise.resolve(existing)
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(new Error(`${label} 超时（10s）。已收帧：${JSON.stringify(seen)}`))
    }, timeoutMs)
    const check = (frame) => {
      if (!pred(frame)) return
      clearTimeout(timer)
      const i = waiters.indexOf(check)
      if (i >= 0) waiters.splice(i, 1)
      resolve(frame)
    }
    waiters.push(check)
  })
}
const waiters = []

const opened = new Promise((resolve, reject) => {
  ws.onopen = () => resolve()
  ws.onerror = () => reject(new Error('WS 连接失败'))
})
ws.onmessage = (ev) => {
  let msg = null
  try { msg = JSON.parse(ev.data) } catch { return }
  frames.push(msg)
  seen.push(`${msg.type}${msg.resource ? `/${msg.resource}` : ''}${msg.competitionId != null ? `@${msg.competitionId}` : '@global'}`)
  waiters.slice().forEach((fn) => fn(msg))
}

try {
  await opened
  console.log('✓ WS 已连接')

  // 1) 系统级订阅（连接即入组，仅回执）
  ws.send(JSON.stringify({ type: 'subscribe', scope: 'global' }))
  await waitFor((m) => m.type === 'resource:subscribed' && m.scope === 'global',
    'global 订阅回执')
  console.log('✓ 系统级（global）订阅已确认')

  // 2) 比赛级订阅
  ws.send(JSON.stringify({ type: 'subscribe', competitionId: CID }))
  await waitFor((m) => m.type === 'resource:subscribed' && m.competitionId === CID,
    `比赛 ${CID} 订阅回执`)
  console.log(`✓ 比赛 ${CID} 订阅已确认`)

  // 3) 系统级写入 → global 流（用户管理是全局库资源）
  const uname = `sync_probe_${stamp}`
  const created = await api('/api/users', {
    method: 'POST',
    token,
    body: { username: uname, password: 'SyncProbe12345!', displayName: '同步探针' },
  })
  if (created.status !== 201) fail(`创建用户失败 ${created.status} ${created.text.slice(0, 200)}`)
  const userEvent = await waitFor(
    (m) => m.type === 'resource:changed' && m.resource === 'users' && m.competitionId == null,
    '系统级 users 广播')
  console.log(`✓ 收到系统级广播 resource=${userEvent.resource} action=${userEvent.action} seq=${userEvent.seq}`)

  // 4) 比赛级写入 → comp_<cid> 流（区域资源）
  const region = await api(`/api/competitions/${CID}/regions`, {
    method: 'POST',
    token,
    body: { name: `sync_probe_${stamp}` },
  })
  if (region.status !== 201) fail(`创建区域失败 ${region.status} ${region.text.slice(0, 200)}`)
  const regionEvent = await waitFor(
    (m) => m.type === 'resource:changed' && m.resource === 'regions' && m.competitionId === CID,
    `比赛级 regions 广播`)
  console.log(`✓ 收到比赛级广播 resource=${regionEvent.resource} action=${regionEvent.action} seq=${regionEvent.seq} cid=${regionEvent.competitionId}`)

  // 5) 断线重放：global 作用域按 seq 补发
  ws.send(JSON.stringify({ type: 'replay', scope: 'global', lastSeq: 0 }))
  const replay = await waitFor(
    (m) => m.type === 'resource:replay' && m.scope === 'global' && Array.isArray(m.events),
    'global 重放响应')
  if (!replay.events.length) fail('global 重放为空（应有刚写入的 users 事件）')
  const hasUsers = replay.events.some((e) => e.resource === 'users')
  if (!hasUsers) fail(`global 重放未包含 users 事件：${JSON.stringify(replay.events.slice(0, 3))}`)
  console.log(`✓ global 断线重放补发 ${replay.events.length} 条（含 users）`)

  // 6) 比赛级重放
  ws.send(JSON.stringify({ type: 'replay', competitionId: CID, lastSeq: 0 }))
  const compReplay = await waitFor(
    (m) => m.type === 'resource:replay' && m.competitionId === CID && Array.isArray(m.events),
    '比赛级重放响应')
  const hasRegions = compReplay.events.some((e) => e.resource === 'regions')
  if (!hasRegions) fail(`比赛级重放未包含 regions 事件：${JSON.stringify(compReplay.events.slice(0, 3))}`)
  console.log(`✓ 比赛级断线重放补发 ${compReplay.events.length} 条（含 regions）`)

  // ---------------------------------------------------------------- 清理探针数据
  if (created.json?.id) await api(`/api/users/${created.json.id}`, { method: 'DELETE', token })
  if (region.json?.id) await api(`/api/competitions/${CID}/regions/${region.json.id}`, { method: 'DELETE', token })
  console.log('✓ 探针数据已清理')

  ws.close()
  console.log('\n实时同步链路验证通过：写入 → 广播 → WS 推送 → 断线重放 均正常。')
  process.exit(0)
} catch (err) {
  console.error(`FAIL: ${err.message}`)
  try { ws.close() } catch { /* ignore */ }
  process.exit(1)
}
