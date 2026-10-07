// 竞赛相关接口封装（调用 Django 后端 /api）
export interface Competition {
  id: number
  name: string
  description: string
  start_date: string | null
  created_at: string
}

const BASE = '/api'

export async function getCompetitions(): Promise<Competition[]> {
  const res = await fetch(`${BASE}/competitions/`)
  if (!res.ok) {
    throw new Error(`请求失败: ${res.status}`)
  }
  return res.json()
}
