// WS 连通性冒烟：无 token 应被拒（close 4401），带 token 应连接成功
const base = 'ws://127.0.0.1:8123/ws/notifications'

async function login() {
  const res = await fetch('http://127.0.0.1:8123/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: 'full_admin', password: 'FullAdmin12345!' }),
  })
  const data = await res.json()
  return data.access
}

function tryConnect(url, label) {
  return new Promise((resolve) => {
    const ws = new WebSocket(url)
    const timer = setTimeout(() => {
      ws.close()
      resolve(`${label}: TIMEOUT`)
    }, 5000)
    ws.onopen = () => {
      clearTimeout(timer)
      ws.close()
      resolve(`${label}: OPENED (ok)`)
    }
    ws.onclose = (ev) => {
      clearTimeout(timer)
      resolve(`${label}: CLOSED code=${ev.code}`)
    }
    ws.onerror = () => {
      clearTimeout(timer)
      resolve(`${label}: ERROR`)
    }
  })
}

const token = await login()
console.log(await tryConnect(base, 'no-token'))
console.log(await tryConnect(`${base}?token=${token}`, 'with-token'))
process.exit(0)
