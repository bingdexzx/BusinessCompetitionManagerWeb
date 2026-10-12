<template>
  <div class="dm-hub">
    <!-- 数据域切换入口（对应旧项目侧栏「数据管理」子菜单；地图项跳转地图页） -->
    <div class="dm-nav">
      <button
        v-for="item in navItems"
        :key="item.type"
        type="button"
        class="dm-nav-item"
        :class="{ 'is-active': item.type === type }"
        @click="selectType(item)"
      >
        <el-icon class="dm-nav-icon"><component :is="item.icon" /></el-icon>
        <span>{{ item.label }}</span>
      </button>
    </div>

    <component :is="managerComponent" v-if="isManagerType" :cid="cid" :key="type" />
    <div v-else class="placeholder">
      <h2>{{ title }}</h2>
      <p>此模块正在开发中</p>
    </div>
  </div>
</template>

<script setup lang="ts">
// 数据管理入口枢纽：按类型切换到各管理器组件（照旧项目的切换方式：
// MANAGER_COMPONENTS 一次性创建异步组件引用 + <component :is> 渲染，
// 避免 computed 里每次调用 defineAsyncComponent 工厂导致组件反复卸载重挂载）。
import { computed, defineAsyncComponent, type Component } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  Box,
  Cpu,
  DataLine,
  Goods,
  MapLocation,
  OfficeBuilding,
  Setting,
  Van,
  Watermelon,
} from "@element-plus/icons-vue";
import { useAuthStore } from "@/stores/auth";

const props = defineProps<{ cid: string }>();

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();

/** 系统超管或本比赛超管：可新建/编辑/删除（其余只读） */
const canManage = computed(
  () =>
    authStore.isSuperuser ||
    authStore.memberships.some(
      (m) => String(m.id) === props.cid && m.identity === "COMP_SUPER_ADMIN",
    ),
);

/** 数据域入口（顺序/图标/文案照旧项目侧栏「数据管理」子菜单） */
interface NavItem {
  type: string;
  label: string;
  icon: Component;
  /** 地图项不在本页渲染，跳转地图页 */
  external?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { type: "materials", label: "原料", icon: Box },
  { type: "parts", label: "零件", icon: Setting },
  { type: "products", label: "产品", icon: Goods },
  { type: "maps", label: "地图", icon: MapLocation },
  { type: "infrastructures", label: "基建", icon: OfficeBuilding },
  { type: "tech-tree", label: "科技树", icon: DataLine },
  { type: "fuels", label: "燃料", icon: Watermelon },
  { type: "vehicles", label: "载具", icon: Van },
  { type: "warehouses", label: "仓库", icon: Box },
  { type: "production-lines", label: "生产线", icon: Cpu },
];

// 拥有管理权限时标题保留「管理」二字，否则去掉（照旧侧栏文案规则）
const navItems = computed(() =>
  NAV_ITEMS.map((item) => ({
    ...item,
    label: canManage.value ? `${item.label}管理` : item.label,
  })),
);

const type = computed(() => {
  const q = route.query?.type;
  const t = typeof q === "string" ? q : "";
  return t || "materials";
});
const title = computed(
  () => navItems.value.find((i) => i.type === type.value)?.label || "数据管理",
);

// 一次性创建所有异步组件引用，避免 computed 里每次调用 defineAsyncComponent 工厂
// 导致每次渲染返回新引用，Vue 反复判定组件类型变化、卸载重挂载、陷入 loading 死循环。
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
  // 地图管理挂回枢纽页内切换（保持顶部数据域菜单常驻；不再跳独立页）
  maps: defineAsyncComponent(() => import("./MapsManager.vue")),
};

const MANAGER_TYPES = Object.keys(MANAGER_COMPONENTS);

const isManagerType = computed(() => MANAGER_TYPES.includes(type.value));

const managerComponent = computed(
  () => MANAGER_COMPONENTS[type.value] as Component | undefined,
);

function selectType(item: NavItem): void {
  if (item.type === type.value) return;
  void router.push({ path: route.path, query: { ...route.query, type: item.type } });
}
</script>

<style scoped>
.dm-hub {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* 数据域切换条：横向排列，窄屏自动换行 */
.dm-nav {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.dm-nav-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border: 1px solid var(--color-border, #e4e7ed);
  border-radius: var(--radius-sm, 6px);
  background: var(--color-surface, #fff);
  color: var(--color-text-secondary, #5c5c5c);
  font-size: 13.5px;
  line-height: 1.2;
  cursor: pointer;
  transition: all var(--dur-base, 0.2s) var(--ease-out-expo, ease);
}
.dm-nav-item:hover {
  border-color: var(--color-primary, #6366f1);
  color: var(--color-primary, #6366f1);
}
.dm-nav-item.is-active {
  background: var(--gradient-brand-soft, #eef2ff);
  border-color: var(--color-primary, #6366f1);
  color: var(--color-primary, #6366f1);
  font-weight: 600;
}
.dm-nav-icon {
  font-size: 15px;
}

.placeholder {
  padding: 24px;
}
.placeholder h2 {
  position: relative;
  font-size: var(--font-2xl);
  font-weight: 700;
  color: var(--color-text-primary);
  letter-spacing: -0.01em;
  padding-left: 14px;
  margin: 0 0 8px;
}
.placeholder h2::before {
  content: "";
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 4px;
  height: 18px;
  border-radius: 4px;
  background: var(--gradient-brand);
}
.placeholder p {
  font-size: 14px;
  color: #8c8c8c;
}
</style>
