/**
 * 受保护文件（`/api/files/view/...`）的图片预览。
 *
 * `<img src>` 不会携带 Authorization 头，直接引用会 401（预览空白）；
 * 这里用 fetch + Bearer token 拉取，转成 object URL 供 <img> 使用，卸载/换图时释放。
 */
import { onBeforeUnmount, ref, watch } from 'vue'
import { ensureFreshAccessToken, getAccessToken } from '@/api/client'

export function useAuthedImage(source: () => string | null | undefined) {
  const src = ref('')
  let objectUrl: string | null = null

  function release(): void {
    if (objectUrl) {
      URL.revokeObjectURL(objectUrl)
      objectUrl = null
    }
  }

  async function load(url: string, retried = false): Promise<void> {
    release()
    src.value = ''
    try {
      const token = getAccessToken()
      const res = await fetch(url, token ? { headers: { Authorization: `Bearer ${token}` } } : {})
      if (res.status === 401 && !retried) {
        await ensureFreshAccessToken()
        return load(url, true)
      }
      if (!res.ok) return
      objectUrl = URL.createObjectURL(await res.blob())
      src.value = objectUrl
    } catch {
      // 预览失败不阻塞业务（封面仍为已保存的 URL）
    }
  }

  watch(
    () => source(),
    (url) => {
      if (url) {
        void load(url)
      } else {
        release()
        src.value = ''
      }
    },
    { immediate: true },
  )

  onBeforeUnmount(release)
  return src
}
