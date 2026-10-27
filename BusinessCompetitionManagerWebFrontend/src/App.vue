<template>
  <router-view v-if="isPublic" />
  <AppLayout v-else>
    <MessageToastHost />
    <router-view v-slot="{ Component, route: current }">
      <transition name="page-shift" mode="out-in">
        <div :key="current.path" class="page-shift-root">
          <component :is="Component" />
        </div>
      </transition>
    </router-view>
  </AppLayout>

  <!-- 版本硬封锁：客户端版本与服务端版本不一致时全屏阻断 -->
  <div v-if="versionMismatch" class="version-block">
    <div class="version-block__box">
      <h2>版本已更新，请刷新页面</h2>
      <p>
        当前页面版本 <b>{{ APP_VERSION }}</b> 与服务端版本 <b>{{ serverVersion }}</b> 不一致，
        为避免数据错误已暂停操作。
      </p>
      <el-button type="primary" @click="reload">刷新页面</el-button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import AppLayout from '@/components/layout/AppLayout.vue'
import MessageToastHost from '@/components/MessageToastHost.vue'
import { fetchVersion } from '@/api'
import { APP_VERSION } from '@/version'

const route = useRoute()
const isPublic = computed(() => Boolean(route.meta.public))

const serverVersion = ref('')
const versionMismatch = ref(false)
let timer: number | undefined

async function checkVersion(): Promise<void> {
  try {
    const { version } = await fetchVersion()
    serverVersion.value = version
    versionMismatch.value = Boolean(version) && version !== APP_VERSION
  } catch {
    // 版本服务暂不可用时不阻断
  }
}

function reload(): void {
  window.location.reload()
}

onMounted(() => {
  void checkVersion()
  timer = window.setInterval(() => {
    void checkVersion()
  }, 5 * 60 * 1000)
})

onBeforeUnmount(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<style scoped>
.version-block {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(15, 23, 42, 0.72);
  backdrop-filter: blur(4px);
}

.version-block__box {
  max-width: 420px;
  padding: 32px 36px;
  text-align: center;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.25);
}

.version-block__box h2 {
  margin: 0 0 12px;
  font-size: 18px;
}

.version-block__box p {
  margin: 0 0 20px;
  color: #64748b;
  line-height: 1.7;
}
</style>
