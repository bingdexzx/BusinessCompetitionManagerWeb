<template>
  <div class="nav-tool">
    <MapsManager :cid="cid" navigation-only />
  </div>
</template>

<script setup lang="ts">
// 工具箱里的「地图导航」：复用地图画布与寻路逻辑，只是导航面板常驻
import MapsManager from "@/views/data-management/MapsManager.vue";

defineProps<{ cid: string }>();
</script>

<style scoped>
.nav-tool {
  display: flex;
  flex-direction: column;
  height: calc(100vh - var(--page-padding, 24px) * 2);
  min-height: 520px;
}
.nav-tool :deep(.maps-manager) {
  flex: 1;
  min-height: 0;
}
</style>
