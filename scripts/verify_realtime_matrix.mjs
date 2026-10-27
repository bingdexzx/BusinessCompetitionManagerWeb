// 实时同步「资源矩阵」端到端验证：
//   HTTP 写入各业务域 → 断言 WS 收到对应 resource:changed（资源名 + 作用域）
//   另验证：断线 seq 重放（global / 比赛）、站内信 notification 定向推送
//
// 前置：HTTP 8000（waitress/runserver）+ WS 8001（daphne）
// 用法：node scripts\verify_realtime_matrix.mjs
//   环境变量：HTTP_BASE / WS_BASE / SYNC_USER / SYNC_PASSWORD / SYNC_CID
//             PROBE_USER_TOKEN（可选：另一个用户的 access，用于验证站内信定向推送）
//
// 说明：所有探针数据（用户/学校/区域/需求/燃料/准则）创建后删除，失败也会清理。
//      合同走 DELETE 接口是**软删除**（deleted_at），列表已过滤故界面不可见；
//      如需彻底清除，用仓库根的清理脚本或 ORM 按 name 前缀 rt_contract_ 删除。

const HTTP = process.env.HTTP_BASE || 'http://127.0.0.1:8000'
const WS = process.env.WS_BASE || 'ws://127.0.0.1:8001'
const USER = process.env.SYNC_USER || 'full_admin'
const PASS = process.env.SYNC_PASSWORD || 'FullAdmin12345!'
const CID = Number(process.env.SYNC_CID || '49')
const PROBE_TOKEN = process.env.PROBE_USER_TOKEN || ''
const stamp = Date.now()

const results = []
const cleanup = []
function ok(name, detail) {
  results.push(`✓ ${name}${detail ? ' — ' + detail : ''}`)
}
function bad(name, detail) {
  results.push(`✗ ${name} — ${detail}`)
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
  try {
    json = text ? JSON.parse(text) : null
  } catch {
    /* 非 JSON */
  }
  return { status: res.status, json, text }
}

function connectWs(token) {
  const ws = new WebSocket(`${WS}/ws/notifications?token=${encodeURIComponent(token)}`)
  const frames = []
  const waiters = []
  const opened = new Promise((resolve, reject) => {
    ws.onopen = () => resolve()
    ws.onerror = () => reject(new Error('WS 连接失败'))
  })
  ws.onmessage = (ev) => {
    let msg = null
    try {
      msg = JSON.parse(ev.data)
    } catch {
      return
    }
    frames.push(msg)
    waiters.slice().forEach((fn) => fn(msg))
  }
  const waitFor = (pred, label, timeoutMs = 8000) => {
    const hit = frames.find(pred)
    if (hit) return Promise.resolve(hit)
    return new Promise((resolve, reject) => {
      const timer = setTimeout(
        () => reject(new Error(`${label} 超时（${timeoutMs}ms）`)),
        timeoutMs,
      )
      const check = (f) => {
        if (!pred(f)) return
        clearTimeout(timer)
        const i = waiters.indexOf(check)
        if (i >= 0) waiters.splice(i, 1)
        resolve(f)
      }
      waiters.push(check)
    })
  }
  return { ws, opened, waitFor, frames }
}

// ---------------------------------------------------------------- 登录 + 连接
const login = await api('/api/auth/login', { method: 'POST', body: { username: USER, password: PASS } })
if (login.status !== 200) {
  console.error(`登录失败 ${login.status} ${login.text.slice(0, 200)}`)
  process.exit(1)
}
const token = login.json.access

const main = connectWs(token)
// 探针数据 id：必须在 try 外声明，否则 finally 里引用会抛 ReferenceError 而漏清理
let regionId = null
try {
  await main.opened
  main.ws.send(JSON.stringify({ type: 'subscribe', scope: 'global' }))
  await main.waitFor((m) => m.type === 'resource:subscribed' && m.scope === 'global', 'global 回执')
  main.ws.send(JSON.stringify({ type: 'subscribe', competitionId: CID }))
  await main.waitFor(
    (m) => m.type === 'resource:subscribed' && m.competitionId === CID,
    '比赛回执',
  )
  ok('WS 建连与订阅', `global + comp_${CID}`)

  /** 一次「写入 → 等广播」的断言 */
  async function expectEvent(label, resource, scopeCid, doWrite) {
    const before = main.frames.length
    const res = await doWrite()
    if (res.status >= 300) {
      bad(label, `写入失败 ${res.status} ${String(res.text).slice(0, 160)}`)
      return null
    }
    try {
      const ev = await main.waitFor(
        (m) =>
          m.type === 'resource:changed' &&
          m.resource === resource &&
          (scopeCid === null ? m.competitionId == null : m.competitionId === scopeCid),
        `${label} 广播`,
      )
      ok(label, `resource=${ev.resource} action=${ev.action} seq=${ev.seq}`)
      return res
    } catch (err) {
      const recent = main.frames.slice(before).map((m) => `${m.type}/${m.resource || m.scope}`)
      bad(label, `${err.message}；这段时间收到：${JSON.stringify(recent)}`)
      return res
    }
  }

  // 1) 系统级 users
  let createdUser = null
  await expectEvent('系统级 users', 'users', null, async () => {
    const r = await api('/api/users', {
      method: 'POST',
      token,
      body: { username: `rt_probe_${stamp}`, password: 'ProbePass12345!', displayName: '实时探针' },
    })
    createdUser = r.json
    if (r.status < 300 && r.json?.id) cleanup.push(() => api(`/api/users/${r.json.id}`, { method: 'DELETE', token }))
    return r
  })

  // 2) 系统级 schools
  await expectEvent('系统级 schools', 'schools', null, async () => {
    const r = await api('/api/schools', { method: 'POST', token, body: { name: `实时探针学校_${stamp}` } })
    if (r.status < 300 && r.json?.id) cleanup.push(() => api(`/api/schools/${r.json.id}`, { method: 'DELETE', token }))
    return r
  })

  // 3) 系统级 system（限流计数重置：无业务数据变化）
  await expectEvent('系统级 system', 'system', null, () =>
    api('/api/system/rate-limit/reset', { method: 'POST', token, body: {} }),
  )

  // 4) 比赛级 regions
  await expectEvent(`比赛级 regions`, 'regions', CID, async () => {
    const r = await api(`/api/competitions/${CID}/regions`, {
      method: 'POST',
      token,
      body: { name: `rt_region_${stamp}` },
    })
    regionId = r.json?.id ?? null
    return r
  })

  // 5) 比赛级 consumer-demands（区域名关联）
  await expectEvent('比赛级 consumer-demands', 'consumer-demands', CID, async () => {
    const r = await api(`/api/competitions/${CID}/consumer-demands`, {
      method: 'POST',
      token,
      body: { region: `rt_region_${stamp}`, productName: '探针产品', quantity: 1, note: 'rt' },
    })
    if (r.status < 300 && r.json?.id)
      cleanup.push(() => api(`/api/competitions/${CID}/consumer-demands/${r.json.id}`, { method: 'DELETE', token }))
    return r
  })

  // 6) 比赛级 basedata
  await expectEvent('比赛级 basedata', 'basedata', CID, async () => {
    const r = await api(`/api/competitions/${CID}/basedata/fuels`, {
      method: 'POST',
      token,
      body: { name: `rt_fuel_${stamp}`, pricePerLiter: 1.5 },
    })
    if (r.status < 300 && r.json?.id)
      cleanup.push(() => api(`/api/competitions/${CID}/basedata/fuels/${r.json.id}`, { method: 'DELETE', token }))
    return r
  })

  // 7) 比赛级 settlement（评分准则）
  await expectEvent('比赛级 settlement', 'settlement', CID, async () => {
    const r = await api(`/api/competitions/${CID}/settlement/config`, {
      method: 'POST',
      token,
      body: { kind: 'criterion', name: `rt_crit_${stamp}`, fieldKey: 'cash', weight: 1 },
    })
    if (r.status < 300 && r.json?.id)
      cleanup.push(() =>
        api(`/api/competitions/${CID}/settlement/config/criterion/${r.json.id}`, { method: 'DELETE', token }),
      )
    return r
  })

  // 8) 比赛级 logs（字段日志导出：只读，但路径推导为 logs，验证映射）
  await expectEvent('比赛级 logs', 'logs', CID, () =>
    api(`/api/competitions/${CID}/logs/fields/export`, { method: 'POST', token, body: {} }),
  )

  // 9) 比赛级 contracts（建草稿 → 软删除；输入项按 inputSchema 的最小可满足值填）
  const types = await api(`/api/competitions/${CID}/contract-types`, { token })
  const companies = await api(`/api/competitions/${CID}/companies`, { token })
  const products = await api(`/api/competitions/${CID}/basedata/products`, { token })
  const typeList = Array.isArray(types.json) ? types.json : []
  const companyIds = (Array.isArray(companies.json) ? companies.json : []).map((c) => c.id)
  const refValue = (Array.isArray(products.json?.items) ? products.json.items[0]?.name : '') || 'P1'

  /** 按 INPUT_SCHEMA 生成一份可过「必填校验」的最小输入 */
  function buildInputs(schema) {
    const inputs = {}
    for (const item of schema || []) {
      if (!item?.key) continue
      const t = String(item.type || '').toUpperCase()
      if (t.startsWith('NUMBER')) inputs[item.key] = item.min ?? 1
      else if (t.startsWith('REF')) inputs[item.key] = refValue
      else if (t.startsWith('BOOL')) inputs[item.key] = true
      else inputs[item.key] = '探针'
    }
    return inputs
  }

  const type = typeList.find((t) => (t.partyRoles || []).length >= 2) || typeList[0]
  if (type && companyIds.length >= 2) {
    const roles = (type.partyRoles || []).slice(0, 2)
    await expectEvent('比赛级 contracts', 'contracts', CID, async () => {
      const r = await api(`/api/competitions/${CID}/contracts`, {
        method: 'POST',
        token,
        body: {
          contractTypeKey: type.key,
          name: `rt_contract_${stamp}`,
          parties: roles.map((role, i) => ({ role: role.role, companyId: companyIds[i] })),
          inputs: buildInputs(type.inputSchema),
        },
      })
      if (r.status < 300 && r.json?.id)
        cleanup.push(() => api(`/api/competitions/${CID}/contracts/${r.json.id}`, { method: 'DELETE', token }))
      return r
    })
  } else {
    bad('比赛级 contracts', `前置不足：type=${!!type} companies=${companyIds.length}`)
  }

  // 10) 断线重放（global + 比赛）
  main.ws.send(JSON.stringify({ type: 'replay', scope: 'global', lastSeq: 0 }))
  const gReplay = await main.waitFor(
    (m) => m.type === 'resource:replay' && m.scope === 'global' && Array.isArray(m.events),
    'global 重放',
  )
  const gNames = [...new Set(gReplay.events.map((e) => e.resource))]
  if (gNames.includes('users')) ok('断线重放 global', `${gReplay.events.length} 条，含 users`)
  else bad('断线重放 global', `未见 users：${JSON.stringify(gNames)}`)

  main.ws.send(JSON.stringify({ type: 'replay', competitionId: CID, lastSeq: 0 }))
  const cReplay = await main.waitFor(
    (m) => m.type === 'resource:replay' && m.competitionId === CID && Array.isArray(m.events),
    '比赛重放',
  )
  const cNames = [...new Set(cReplay.events.map((e) => e.resource))]
  if (cNames.includes('regions')) ok('断线重放 比赛', `${cReplay.events.length} 条，含 regions`)
  else bad('断线重放 比赛', `未见 regions：${JSON.stringify(cNames)}`)

  // 11) 站内信定向推送：临时用户登录后建连，由 admin 发信 → 断言收到 notification 帧
  const msgUser = `rt_msg_${stamp}`
  const msgPass = 'ProbePass12345!'
  const created = await api('/api/users', {
    method: 'POST',
    token,
    body: { username: msgUser, password: msgPass, displayName: '实时消息探针' },
  })
  if (created.status >= 300 || !created.json?.id) {
    bad('站内信通知帧', `临时用户创建失败 ${created.status} ${String(created.text).slice(0, 120)}`)
  } else {
    const recipientId = created.json.id
    cleanup.push(() => api(`/api/users/${recipientId}`, { method: 'DELETE', token }))
    let probe = null
    try {
      const probeLogin = await api('/api/auth/login', {
        method: 'POST',
        body: { username: msgUser, password: msgPass },
      })
      if (probeLogin.status !== 200) throw new Error(`探针用户登录失败 ${probeLogin.status}`)
      probe = connectWs(probeLogin.json.access)
      await probe.opened
      const sent = await api('/api/messages/send', {
        method: 'POST',
        token,
        body: { title: `rt_${stamp}`, body: '实时探针', recipientUserIds: [recipientId] },
      })
      if (sent.status >= 300) throw new Error(`发送失败 ${sent.status} ${String(sent.text).slice(0, 120)}`)
      const frame = await probe.waitFor(
        (m) => m.type === 'notification' && String(m.title || '').includes(`rt_${stamp}`),
        '站内信定向推送',
      )
      ok('站内信通知帧', `recipient=${recipientId} title=${frame.title}`)
    } catch (err) {
      bad('站内信通知帧', err.message)
    } finally {
      try {
        probe?.ws.close()
      } catch {
        /* ignore */
      }
    }
  }
} catch (err) {
  bad('建连/执行', err.message)
} finally {
  // 清理：合同/准则/燃料/需求/区域/学校/用户
  for (const fn of cleanup.reverse()) {
    try {
      await fn()
    } catch {
      /* 清理失败不影响结论 */
    }
  }
  try {
    if (regionId) await api(`/api/competitions/${CID}/regions/${regionId}`, { method: 'DELETE', token })
  } catch {
    /* ignore */
  }
  try {
    main.ws.close()
  } catch {
    /* ignore */
  }
}

console.log('\n=== 实时同步资源矩阵 ===')
results.forEach((r) => console.log(r))
const failed = results.filter((r) => r.startsWith('✗'))
console.log(`\n通过 ${results.filter((r) => r.startsWith('✓')).length} / 失败 ${failed.length}`)
process.exit(failed.length ? 1 : 0)
