<template>
  <div class="dm-hub">
    <!-- 枢纽头部：一句话说明 + 记录总数（只读统计，不改变任何接口契约） -->
    <header class="dm-hub-head anim-fade-in-up">
      <div class="dm-hub-copy">
        <h1 class="page-title dm-hub-title">数据管理</h1>
        <p class="dm-hub-sub">
          按数据域维护比赛基础数据；选择下方分区进入对应管理器，这里的改动会实时同步给其他窗口。
        </p>
      </div>
      <div class="dm-hub-stat">
        <span class="metric-label">记录总数</span>
        <div class="dm-hub-stat-value">
          <span class="value-num">{{ totalShown }}</span>
          <span class="metric-unit">条</span>
        </div>
      </div>
    </header>

    <!-- 数据域入口：图标 + 名称 + 一句话说明 + 记录数（仍走 ?type= 查询参数路由） -->
    <nav class="dm-grid anim-stagger" aria-label="数据域">
      <button
        v-for="item in navItems"
        :key="item.type"
        type="button"
        class="dm-card metric-card"
        :class="{ 'is-active': item.type === type }"
        :aria-current="item.type === type ? 'page' : undefined"
        @click="selectType(item)"
      >
        <span class="dm-card-top">
          <span class="dm-card-icon">
            <el-icon><component :is="item.icon" /></el-icon>
          </span>
          <span class="metric-label dm-card-label">{{ item.label }}</span>
          <span class="dm-card-count metric-value">
            <span v-if="!countsReady" class="skeleton dm-card-skeleton" />
            <template v-else>
              <span class="value-num">{{ countText(item.type) }}</span>
              <span v-if="countOf(item.type) !== null" class="metric-unit">条</span>
            </template>
          </span>
        </span>
        <span class="dm-card-desc">{{ item.desc }}</span>
      </button>
    </nav>

    <component :is="managerComponent" v-if="isManagerType" :cid="cid" :key="type" />
    <div v-else class="placeholder">
      <h2 class="page-title">{{ title }}</h2>
      <p>此模块正在开发中</p>
    </div>
  </div>
</template>

<script setup lang="ts">
// 数据管理入口枢纽：按类型切换到各管理器组件（照旧项目的切换方式：
// MANAGER_COMPONENTS 一次性创建异步组件引用 + <component :is> 渲染，
// 避免 computed 里每次调用 defineAsyncComponent 工厂导致组件反复卸载重挂载）。
import { computed, defineAsyncComponent, onMounted, ref, type Component } from "vue";
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
import {
  fuelsApi,
  infrastructuresApi,
  listMapNodes,
  materialsApi,
  partsApi,
  productionLinesApi,
  productsApi,
  techNodesApi,
  vehiclesApi,
  warehousesApi,
  type BasedataListResult,
} from "@/api/basedataApi";
import { useCountUp } from "@/composables/useMotion";
import { useResourceRefresh } from "@/composables/useNotifications";

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

/** 数据域入口（顺序/图标/文案照旧项目侧栏「数据管理」子菜单，另加一句话说明） */
interface NavItem {
  type: string;
  label: string;
  icon: Component;
  /** 入口卡片上的一句话说明（只加信息量，不改任何业务文案） */
  desc: string;
  /** 地图项不在本页渲染，跳转地图页 */
  external?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { type: "materials", label: "原料", icon: Box, desc: "生产零件的基础原料，按产地节点定价" },
  { type: "parts", label: "零件", icon: Setting, desc: "原料配比而成的中间件" },
  { type: "products", label: "产品", icon: Goods, desc: "零件配比而成的最终产品" },
  { type: "maps", label: "地图", icon: MapLocation, desc: "城市节点、连线与路径类型画布" },
  {
    type: "infrastructures",
    label: "基建",
    icon: OfficeBuilding,
    desc: "占地、人口与幸福度等城市加成",
  },
  { type: "tech-tree", label: "科技树", icon: DataLine, desc: "科技节点、层级与前置依赖" },
  { type: "fuels", label: "燃料", icon: Watermelon, desc: "载具消耗的燃料与每升价格" },
  { type: "vehicles", label: "载具", icon: Van, desc: "运力、油耗与可通行路径类型" },
  { type: "warehouses", label: "仓库", icon: Box, desc: "各类物资的仓储容量与价格" },
  { type: "production-lines", label: "生产线", icon: Cpu, desc: "加工能力、劳动力与年加工上限" },
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

/**
 * 各数据域的记录数（入口卡片的信息量）。
 * 只读统计：沿用各表既有的 list 接口，pageSize=1 仅取 total，不新增/不改动任何接口契约。
 */
function totalOf(res: BasedataListResult | undefined): number {
  if (typeof res?.total === "number" && Number.isFinite(res.total)) return res.total;
  return Array.isArray(res?.items) ? res.items.length : 0;
}

const countJobs: Array<{ type: string; load: () => Promise<number> }> = [
  {
    type: "materials",
    load: async () => totalOf(await materialsApi.list(props.cid, { page: 1, pageSize: 1 })),
  },
  {
    type: "parts",
    load: async () => totalOf(await partsApi.list(props.cid, { page: 1, pageSize: 1 })),
  },
  {
    type: "products",
    load: async () => totalOf(await productsApi.list(props.cid, { page: 1, pageSize: 1 })),
  },
  {
    type: "maps",
    load: async () => (await listMapNodes(props.cid)).length,
  },
  {
    type: "infrastructures",
    load: async () =>
      totalOf(await infrastructuresApi.list(props.cid, { page: 1, pageSize: 1 })),
  },
  {
    type: "tech-tree",
    load: async () => totalOf(await techNodesApi.list(props.cid, { page: 1, pageSize: 1 })),
  },
  {
    type: "fuels",
    load: async () => totalOf(await fuelsApi.list(props.cid, { page: 1, pageSize: 1 })),
  },
  {
    type: "vehicles",
    load: async () => totalOf(await vehiclesApi.list(props.cid, { page: 1, pageSize: 1 })),
  },
  {
    type: "warehouses",
    load: async () => totalOf(await warehousesApi.list(props.cid, { page: 1, pageSize: 1 })),
  },
  {
    type: "production-lines",
    load: async () =>
      totalOf(await productionLinesApi.list(props.cid, { page: 1, pageSize: 1 })),
  },
];

const counts = ref<Record<string, number | null>>({});
const countsReady = ref(false);
let countsPending = false;

/** 拉取记录数：失败的数据域保留「—」，不打断页面（不带 toast） */
async function loadCounts(): Promise<void> {
  if (countsPending) return;
  if (!props.cid) {
    counts.value = {};
    countsReady.value = true;
    return;
  }
  countsPending = true;
  try {
    const results = await Promise.allSettled(countJobs.map((job) => job.load()));
    const next: Record<string, number | null> = {};
    countJobs.forEach((job, index) => {
      const result = results[index];
      next[job.type] = result && result.status === "fulfilled" ? result.value : null;
    });
    counts.value = next;
  } finally {
    countsPending = false;
    countsReady.value = true;
  }
}

onMounted(loadCounts);

// 基础数据变更后刷新记录数（沿用全局 400ms 去抖合并，不额外造刷新风暴）。
// 注意：枢纽与其下方管理器是**同一页**同时可见，所以不能按「是否在管理器里」跳过统计。
useResourceRefresh(["basedata"], loadCounts);

function countOf(t: string): number | null {
  return counts.value[t] ?? null;
}
function countText(t: string): string {
  const n = countOf(t);
  return n === null ? "—" : n.toLocaleString("zh-CN");
}

/** 记录总数：数字滚动到目标值（尊重系统「减少动态效果」偏好） */
const totalCount = computed(() =>
  Object.values(counts.value).reduce<number>((sum, n) => sum + (n ?? 0), 0),
);
const totalShown = useCountUp(totalCount);
</script>

<style scoped>
.dm-hub {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* ---------- 枢纽头部：标题 + 说明 + 记录总数 ---------- */
.dm-hub-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
}
/* 提高特异性压过全局 .app-content .page-title（H1 略大于管理器标题，形成层级） */
.dm-hub .dm-hub-title {
  font-size: var(--font-3xl);
  margin: 0;
}
.dm-hub-sub {
  margin: 6px 0 0;
  font-size: var(--font-sm);
  line-height: 1.6;
  color: var(--color-text-secondary);
}
.dm-hub-stat {
  flex-shrink: 0;
  padding: 10px 16px;
  text-align: right;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-xs);
}
.dm-hub-stat-value {
  display: flex;
  align-items: baseline;
  justify-content: flex-end;
  gap: 4px;
  margin-top: 2px;
  font-size: var(--font-2xl);
  font-weight: 700;
  line-height: 1.15;
  color: var(--color-text-primary);
}

/* ---------- 数据域入口卡片 ---------- */
.dm-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(204px, 1fr));
  gap: 12px 16px;
}
.dm-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px 14px;
  font: inherit;
  text-align: left;
  appearance: none;
  cursor: pointer;
}
.dm-card:focus-visible {
  outline: 2px solid rgba(var(--color-primary-rgb), 0.55);
  outline-offset: 2px;
}
.dm-card-top {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
}
.dm-card-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  height: 30px;
  border-radius: var(--radius-sm);
  background: var(--surface-sunken);
  color: var(--color-text-secondary);
  font-size: 16px;
  transition:
    color var(--dur-fast) var(--ease-standard),
    background-color var(--dur-fast) var(--ease-standard);
}
.dm-card-label {
  font-size: var(--font-sm);
  font-weight: 600;
  color: var(--color-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
/* 单行省略：卡片高度稳定，10 个入口不因说明长短参差 */
.dm-card-desc {
  font-size: var(--font-xs);
  line-height: 1.4;
  color: var(--color-text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.dm-card-count {
  display: flex;
  align-items: baseline;
  gap: 2px;
  margin-top: 0;
  font-size: var(--font-lg);
  font-weight: 700;
}
.dm-card-skeleton {
  display: inline-block;
  width: 28px;
  height: 14px;
  border-radius: var(--radius-xs);
}
/* 当前数据域：品牌色描边 + 浅色底，和悬停位移区分开（不改变尺寸） */
.dm-card.is-active {
  border-color: var(--color-primary);
  background: var(--gradient-brand-soft);
  box-shadow: var(--shadow-glow-sm);
}
.dm-card.is-active .dm-card-label {
  color: var(--color-primary);
}
.dm-card.is-active .dm-card-icon {
  background: rgba(var(--color-primary-rgb), 0.12);
  color: var(--color-primary);
}

/* 兜底占位（不属于任何管理器的数据域） */
.placeholder {
  padding: 24px;
}
.placeholder p {
  font-size: var(--font-base);
  color: var(--color-text-secondary);
}

/* ---------- 响应式：平板收紧，手机两列紧凑卡 ---------- */
@media (max-width: 1024px) {
  .dm-grid {
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 12px;
  }
}
@media (max-width: 640px) {
  /* 手机端头部收到一行：标题 + 记录总数（说明文字与标签让位给数据域卡片） */
  .dm-hub-head {
    align-items: center;
    gap: 12px;
  }
  .dm-hub-sub {
    display: none;
  }
  .dm-hub-stat {
    display: flex;
    align-items: baseline;
    gap: 6px;
    padding: 6px 12px;
  }
  .dm-hub-stat .metric-label {
    display: none;
  }
  .dm-hub-stat-value {
    margin-top: 0;
    font-size: var(--font-lg);
  }
  /* 手机端两列紧凑卡：只留图标 + 名称 + 记录数 */
  .dm-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 8px;
  }
  .dm-card {
    padding: 9px 11px;
  }
  .dm-card-top {
    gap: 6px;
  }
  .dm-card-icon {
    width: 26px;
    height: 26px;
    font-size: 15px;
  }
  .dm-card-label {
    font-size: var(--font-xs);
  }
  .dm-card-count {
    font-size: var(--font-md);
  }
  .dm-card-desc {
    display: none;
  }
}
</style>
