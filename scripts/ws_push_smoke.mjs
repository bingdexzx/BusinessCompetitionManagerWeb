// WS 跨进程推送冒烟：验证「HTTP worker 进程发出的推送，经跨进程通道层到达 WS 进程」。
//
// 拓扑：scripts/run_servers.py 同时拉起 N 个 HTTP worker（waitress）+ 1 个 WS 进程（daphne），
// 站内信在 HTTP 进程内 group_send，推送必须跨进程到达 WS 进程的客户端——这正是
// apps/common/pg_channel_layer.py 存在的原因。
//
// 用法（另开终端用 Django shell 给该账号发一封站内信，title 用 SMOKE_TITLE）：
//   node scripts\ws_push_smoke.mjs
//   环境变量：HTTP_BASE / WS_BASE / SMOKE_USER / SMOKE_PASSWORD / SMOKE_TITLE / SMOKE_WAIT

const HTTP = process.env.HTTP_BASE || 'http://127.0.0.1:8123'
const WS = process.env.WS_BASE || 'ws://127.0.0.1:8124'
const USER = process.env.SMOKE_USER || 'full_admin'
const PASS = process.env.SMOKE_PASSWORD || 'FullAdmin12345!'
const TITLE = process.env.SMOKE_TITLE || '__push_smoke__'
const WAIT = Number(process.env.SMOKE_WAIT || 30)

const login = await fetch(`${HTTP}/api/auth/login`, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ username: USER, password: PASS }),
})
if (!login.ok) {
  console.error(`login failed: ${login.status} ${await login.text()}`)
  process.exit(1)
}
const data = await login.json()
const token = data.access
console.log(`login ok: ${USER} (uid=${data?.user?.id ?? '?'})`)

const url = `${WS}/ws/notifications?token=${token}`
const started = Date.now()
const ws = new WebSocket(url)

const timer = setTimeout(() => {
  console.error(`TIMEOUT: ${WAIT}s 内没收到推送`)
  ws.close()
  process.exit(1)
}, WAIT * 1000)

ws.onopen = () => console.log('ws connected')
ws.onmessage = (ev) => {
  let msg = null
  try { msg = JSON.parse(ev.data) } catch { /* 忽略非 JSON */ }
  if (msg && msg.title === TITLE) {
    clearTimeout(timer)
    console.log(`PUSH RECEIVED (${Date.now() - started}ms): ${ev.data}`)
    ws.close()
    process.exit(0)
  } else {
    console.log(`other message: ${ev.data}`)
  }
}
ws.onclose = (ev) => console.log(`ws closed code=${ev.code}`)
ws.onerror = () => { console.error('ws error') }
