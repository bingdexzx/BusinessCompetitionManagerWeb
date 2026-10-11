<template>
  <!-- 实时通知宿主：收到推送弹出通知（点击跳消息中心） -->
  <span class="message-toast-host" aria-hidden="true" />
</template>

<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElNotification } from 'element-plus'
import { useNotifications, type NotificationPayload } from '@/composables/useNotifications'

const router = useRouter()

function onNotification(message: NotificationPayload): void {
  if (message.type !== 'notification') return
  ElNotification({
    title: message.title || '新消息',
    message: message.body || '',
    type: 'info',
    duration: 6000,
    onClick: () => {
      void router.push({ name: 'messages' })
    },
  })
}

const { startNotifications, stopNotifications } = useNotifications(onNotification)

onMounted(() => {
  startNotifications()
})

onUnmounted(() => {
  // 离开登录态（布局卸载）即断开通道
  stopNotifications()
})
</script>

<style scoped>
.message-toast-host {
  display: none;
}
</style>
