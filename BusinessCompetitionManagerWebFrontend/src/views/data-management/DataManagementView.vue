<template>
  <div class="dm-hub page">
    <component :is="managerComponent" v-if="isManagerType" :cid="cid" :key="type" />
    <div v-else class="placeholder">
      <PageHeader :title="title" hint="此模块正在开发中" />
    </div>
  </div>
</template>

<script setup lang="ts">
// 一次性创建异步组件引用，避免 computed 每次生成新组件类型导致卸载重挂载/loading 死循环
import { computed, defineAsyncComponent, type Component } from "vue";
import PageHeader from '@/components/common/PageHeader.vue'
import { useRoute } from "vue-router";

defineProps<{ cid: string }>();

// 子模块入口在左侧「数据管理」子菜单里，这里只按 ?type= 渲染对应模块
const route = useRoute();

const SUB_MODULE_TITLES: Record<string, string> = {
  materials: "原料管理",
  parts: "零件管理",
  products: "产品管理",
  maps: "地图管理",
  infrastructures: "基建管理",
  "tech-tree": "科技树",
  fuels: "燃料管理",
  vehicles: "载具管理",
  warehouses: "仓库管理",
  "production-lines": "生产线管理",
};

const type = computed(() => {
  const q = route.query?.type;
  const t = typeof q === "string" ? q : "";
  return t || "materials";
});
const title = computed(
  () => SUB_MODULE_TITLES[type.value] || "数据管理",
);

const MANAGER_COMPONENTS: Record<string, Component> = {
  parts: defineAsyncComponent(() => import("./PartsManager.vue")),
  products: defineAsyncComponent(() => import("./ProductsManager.vue")),
  vehicles: defineAsyncComponent(() => import("./VehiclesManager.vue")),
  "tech-tree": defineAsyncComponent(() => import("./TechTreeManager.vue")),
  materials: defineAsyncComponent(() => import("./MaterialsManager.vue")),
  warehouses: defineAsyncComponent(() => import("./WarehousesManager.vue")),
  "production-lines": defineAsyncComponent(() =>
    import("./ProductionLinesManager.vue"),
  ),
  infrastructures: defineAsyncComponent(() =>
    import("./InfrastructureManager.vue"),
  ),
  fuels: defineAsyncComponent(() => import("./FuelManager.vue")),
  // 地图管理在枢纽内切换，保持顶部菜单常驻
  maps: defineAsyncComponent(() => import("./MapsManager.vue")),
};

const MANAGER_TYPES = Object.keys(MANAGER_COMPONENTS);

const isManagerType = computed(() => MANAGER_TYPES.includes(type.value));

const managerComponent = computed(
  () => MANAGER_COMPONENTS[type.value] as Component | undefined,
);

</script>

<style scoped>
/* 子模块入口在左侧「数据管理」子菜单，这里只负责渲染当前模块 */
.dm-hub {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.placeholder {
  padding: 24px;
}
.placeholder p {
  font-size: var(--font-base);
  color: var(--color-text-secondary);
}
</style>
