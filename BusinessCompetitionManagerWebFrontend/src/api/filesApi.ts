// 文件上传服务 API（后端 app：apps.global_.files，统一挂在 /api 下）
//   POST   /api/files/upload                              通用上传（multipart file，≤100MB）
//   GET    /api/files/view/<path:name>                     读取已上传文件（浏览器直接引用该 url）
//   GET    /api/competitions/{cid}/files/map-background    地图背景 {url, transform|null}
//   POST   /api/competitions/{cid}/files/map-background    multipart file 或 JSON {url, transform}
//   PATCH  /api/competitions/{cid}/files/map-background    只更新 transform
//   DELETE /api/competitions/{cid}/files/map-background    清除背景 {ok:true}
//   POST   /api/messages/upload-image                      站内信图片（multipart file，≤5MB）
// 错误响应统一 {code, message, details}（client.ts 的 ApiError 已封装）。
import { http, request } from './client'

/** 通用上传返回 */
export interface UploadedFile {
  /** 对外可读取地址（/api/files/view/...） */
  url: string
  /** 原始文件名 */
  fileName: string
  /** 字节数 */
  size: number
  /** MIME 类型 */
  contentType: string
  /** 上传时间（ISO 字符串） */
  uploadedAt: string
}

/** 背景图变换（画布世界坐标；null = 按节点包围盒自动适配） */
export interface MapBackgroundTransform {
  scale: number
  x: number
  y: number
}

/** 地图背景（GET/POST/PATCH 统一返回形状） */
export interface MapBackground {
  /** 背景图地址（无背景时为空串） */
  url: string
  transform: MapBackgroundTransform | null
}

/** 保存地图背景：上传文件或图片 URL 二选一，可带 transform */
export interface MapBackgroundSavePayload {
  file?: File
  url?: string
  transform?: MapBackgroundTransform | null
}

/** 通用文件上传：≤100MB，扩展名 png/jpg/jpeg/gif/webp/pdf/xlsx/csv/zip/txt/md */
export function uploadFile(file: File): Promise<UploadedFile> {
  const form = new FormData()
  form.append('file', file)
  return request<UploadedFile>('/files/upload', { method: 'POST', body: form })
}

/** 读取当前比赛的地图背景（无背景时 url=""、transform=null） */
export function getMapBackground(cid: number | string): Promise<MapBackground> {
  return http.get<MapBackground>(`/competitions/${cid}/files/map-background`)
}

/** 保存地图背景：payload.file（multipart 上传）或 payload.url（图片 URL）二选一 */
export function saveMapBackground(
  cid: number | string,
  payload: MapBackgroundSavePayload,
): Promise<MapBackground> {
  if (payload.file) {
    const form = new FormData()
    form.append('file', payload.file)
    if (payload.transform) {
      form.append('transform', JSON.stringify(payload.transform))
    }
    return request<MapBackground>(`/competitions/${cid}/files/map-background`, {
      method: 'POST',
      body: form,
    })
  }
  return http.post<MapBackground>(`/competitions/${cid}/files/map-background`, {
    url: payload.url ?? '',
    transform: payload.transform ?? null,
  })
}

/** 只更新背景图变换（位置/缩放；null 表示恢复自动适配） */
export function updateMapBackgroundTransform(
  cid: number | string,
  transform: MapBackgroundTransform | null,
): Promise<MapBackground> {
  return http.patch<MapBackground>(`/competitions/${cid}/files/map-background`, { transform })
}

/** 清除地图背景（删记录，磁盘文件尽力删除） */
export function deleteMapBackground(cid: number | string): Promise<{ ok: boolean }> {
  return http.delete<{ ok: boolean }>(`/competitions/${cid}/files/map-background`)
}

/** 站内信图片上传：≤5MB，仅 png/jpg/jpeg/gif/webp */
export function uploadMessageImage(file: File): Promise<{ url: string }> {
  const form = new FormData()
  form.append('file', file)
  return request<{ url: string }>('/messages/upload-image', { method: 'POST', body: form })
}
