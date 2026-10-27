<template>
  <div class="techtree-manager">
    <div class="tt-toolbar">
      <h2 class="tt-title">{{ canManage ? "科技树管理" : "科技树" }}</h2>
      <div class="tt-actions">
        <el-button @click="viewMode = viewMode === 'tree' ? 'table' : 'tree'">
          {{ viewMode === "tree" ? "表格模式" : "可视化模式" }}
        </el-button>
        <el-button v-if="canManage" type="primary" @click="openCreate">+ 新建节点</el-button>
      </div>
    </div>

    <div v-if="!cid" class="notice notice--warning">
      请先在「比赛管理」中选择一个比赛
    </div>

    <div v-if="viewMode === 'tree'" class="tt-tree-container">
      <div ref="panWrapRef" class="tt-pan-wrap">
        <div ref="chartRef" class="tt-chart"></div>
      </div>
      <div v-if="selectedNode" class="tt-tree-info">
        <h4>{{ selectedNode.name }}</h4>
        <div class="tt-info-row">
          <span class="tt-info-label">描述</span>{{ selectedNode.description || "-" }}
        </div>
        <div class="tt-info-row">
          <span class="tt-info-label">层级</span><span class="value-num">{{ selectedNode.tier }}</span>
        </div>
        <div class="tt-info-row">
          <span class="tt-info-label">研发费用</span
          ><span class="value-num">{{ selectedNode.researchCost ?? 0 }}</span>
        </div>
        <div class="tt-info-row">
          <span class="tt-info-label">前置依赖</span>
          <span v-if="selectedNode.prerequisites?.length">
            {{ selectedNode.prerequisites.map((p: any) => p.prerequisite?.name).join("、") }}
          </span>
          <span v-else class="cell-empty">无</span>
        </div>
        <div class="tt-info-actions">
          <el-button v-if="canManage" size="small" @click="editNode(selectedNode)">编辑</el-button>
          <el-button
            v-if="canManage"
            size="small"
            type="danger"
            plain
            @click="handleDelete(selectedNode)"
            >删除</el-button
          >
        </div>
      </div>
    </div>

    <div v-show="viewMode !== 'tree'">
      <el-table
        v-if="!isPhone"
        v-loading="loading"
        :data="nodes"
        border
        stripe
        class="anim-fade-in-up"
        style="width: 100%"
      >
        <el-table-column prop="name" label="名称" min-width="160" />
        <el-table-column prop="description" label="描述" min-width="180" />
        <el-table-column prop="tier" label="层级" align="right" min-width="90">
          <template #default="{ row }">
            <span class="value-num">{{ row.tier }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="researchCost" label="研发费用" align="right" min-width="120">
          <template #default="{ row }">
            <span class="value-num">{{ row.researchCost }}</span>
          </template>
        </el-table-column>
        <el-table-column label="前置依赖" min-width="180">
          <template #default="{ row }">
            <span v-if="row.prerequisites?.length">
              <el-tag
                v-for="p in row.prerequisites"
                :key="p.prerequisiteNodeId"
                size="small"
                style="margin: 2px"
              >
                {{ p.prerequisite?.name }}
              </el-tag>
            </span>
            <span v-else class="cell-empty">无</span>
          </template>
        </el-table-column>
        <el-table-column v-if="canManage" label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="showDetail(row)">详情</el-button>
            <el-button v-if="canManage" size="small" @click="editNode(row)">编辑</el-button>
            <el-button v-if="canManage" size="small" type="danger" plain @click="handleDelete(row)"
              >删除</el-button
            >
          </template>
        </el-table-column>
        <template #empty>
          <el-empty v-if="!loading" :image-size="72" description="暂无科技节点" />
        </template>
      </el-table>
      <MobileCards
        v-else
        :data="nodes"
        :columns="techColumns"
        :loading="loading"
        :row-key="(row: any) => row.id"
        empty-text="暂无科技节点"
        class="anim-fade-in-up"
      >
        <template #prereqs="{ row }">
          <span v-if="row.prerequisites?.length">
            <el-tag
              v-for="p in row.prerequisites"
              :key="p.prerequisiteNodeId"
              size="small"
              style="margin: 2px"
            >
              {{ p.prerequisite?.name }}
            </el-tag>
          </span>
          <span v-else class="cell-empty">无</span>
        </template>
        <template #actions="{ row }">
          <el-button size="small" @click="showDetail(row)">详情</el-button>
          <el-button v-if="canManage" size="small" @click="editNode(row)">编辑</el-button>
          <el-button v-if="canManage" size="small" type="danger" plain @click="handleDelete(row)"
            >删除</el-button
          >
        </template>
      </MobileCards>
    </div>

    <el-dialog append-to-body v-model="detailVisible" title="科技节点详情" width="560px">
      <el-descriptions v-if="detailData" :column="1" border>
        <el-descriptions-item label="名称">{{ detailData.name }}</el-descriptions-item>
        <el-descriptions-item label="描述">{{ detailData.description || "-" }}</el-descriptions-item>
        <el-descriptions-item label="层级">
          <span class="value-num">{{ detailData.tier }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="研发费用">
          <span class="value-num">{{ detailData.researchCost ?? 0 }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="前置依赖">
          <template v-if="detailData.prerequisites?.length">
            <el-tag
              v-for="p in detailData.prerequisites"
              :key="p.prerequisiteNodeId"
              size="small"
              style="margin: 2px"
            >
              {{ p.prerequisite?.name }}
            </el-tag>
          </template>
          <span v-else class="cell-empty">无</span>
        </el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ formatDateTime(detailData.createdAt) }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ formatDateTime(detailData.updatedAt) }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>

    <el-dialog append-to-body v-model="showDialog" :title="isEdit ? '编辑节点' : '新建节点'" width="560px">
      <el-form :model="form" label-width="100px">
        <el-form-item label="名称" required><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="描述"
          ><el-input v-model="form.description" type="textarea" :rows="2"
        /></el-form-item>
        <el-form-item label="层级"><el-input-number v-model="form.tier" :min="0" /></el-form-item>
        <el-form-item label="研发费用" required
          ><BigNumberInput v-model="form.researchCost" :min="0" style="width: 100%"
        /></el-form-item>
        <el-form-item label="前置依赖">
          <el-select v-model="form.prerequisiteIds" multiple filterable placeholder="选择前置节点">
            <el-option
              v-for="n in nodes.filter((x) => x.id !== editId)"
              :key="n.id"
              :label="`[T${n.tier}] ${n.name}`"
              :value="n.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showDialog = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted, onBeforeUnmount, watch, nextTick, computed } from "vue";
import { ElMessage } from "element-plus";
import * as echarts from "echarts";
import { techNodesApi, type BasedataRow } from "@/api/basedataApi";
import { confirmDeleteWithImpact, type DeleteImpact } from "@/utils/deleteConfirm";
import { useAuthStore } from "@/stores/auth";
import { errorMessage } from "@/utils/errors";
import { formatDateTime } from "@/utils/format";
import BigNumberInput from "@/components/common/BigNumberInput.vue";
import MobileCards from "@/components/common/MobileCards.vue";
import { useBreakpoint } from "@/composables/useBreakpoint";
import { useResourceRefresh } from "@/composables/useNotifications";

const props = defineProps<{ cid: string }>();
const authStore = useAuthStore();
const { isPhone } = useBreakpoint();
const nodes = ref<any[]>([]);
const loading = ref(false);
const viewMode = ref<"table" | "tree">("tree");

/** 系统超管或本比赛超管：可新建/编辑/删除（其余只读） */
const canManage = computed(
  () =>
    authStore.isSuperuser ||
    authStore.memberships.some(
      (m) => String(m.id) === props.cid && m.identity === "COMP_SUPER_ADMIN",
    ),
);

const techColumns = [
  { prop: "name", label: "名称" },
  { prop: "description", label: "描述" },
  { prop: "tier", label: "层级" },
  { prop: "researchCost", label: "研发费用" },
  { label: "前置依赖", slot: "prereqs" },
];
const showDialog = ref(false);
const isEdit = ref(false);
const editId = ref(0);
const submitting = ref(false);
const selectedNode = ref<any>(null);
const detailVisible = ref(false);
const detailData = ref<any>(null);
const chartRef = ref<HTMLDivElement>();
const panWrapRef = ref<HTMLDivElement>();
let chart: echarts.ECharts | null = null;
let resizeHandler: (() => void) | null = null;
let mouseMoveHandler: ((e: MouseEvent) => void) | null = null;
let mouseUpHandler: (() => void) | null = null;
let mouseDownHandler: ((e: MouseEvent) => void) | null = null;
let wheelHandler: ((e: WheelEvent) => void) | null = null;

const form = reactive<{
  name: string;
  description: string;
  tier: number;
  researchCost: number | string;
  prerequisiteIds: number[];
}>({
  name: "",
  description: "",
  tier: 0,
  researchCost: 0,
  prerequisiteIds: [],
});

onMounted(loadData);

// 资源变更实时刷新：basedata 变更时自动重拉当前列表（保留视图模式/选中节点）
useResourceRefresh(["basedata"], loadData);

onBeforeUnmount(() => {
  if (resizeHandler) {
    window.removeEventListener("resize", resizeHandler);
    resizeHandler = null;
  }
  if (mouseMoveHandler) {
    window.removeEventListener("mousemove", mouseMoveHandler);
    mouseMoveHandler = null;
  }
  if (mouseUpHandler) {
    window.removeEventListener("mouseup", mouseUpHandler);
    mouseUpHandler = null;
  }
  const wrap = panWrapRef.value;
  if (mouseDownHandler && wrap) {
    wrap.removeEventListener("mousedown", mouseDownHandler);
    mouseDownHandler = null;
  }
  if (wheelHandler && wrap) {
    wrap.removeEventListener("wheel", wheelHandler);
    wheelHandler = null;
  }
  if (chart) {
    chart.dispose();
    chart = null;
  }
});

watch(viewMode, async (v) => {
  if (v === "tree") {
    await nextTick();
    if (chart) {
      chart.dispose();
      chart = null;
    }
    renderTree();
  }
});

/**
 * 行内关联归一化：新契约 tech_nodes 行带 relations.prerequisites
 * （items 形如 [{ id, prerequisiteNodeId, prerequisiteName }]）；
 * 展示层沿用旧页面的 prerequisites / prerequisite.name 结构。
 */
function normalizeTechNode(row: BasedataRow): any {
  const rel = (row?.relations ?? {}) as Record<string, any>;
  const raw: any[] = rel.prerequisites ?? (row as any)?.prerequisites ?? [];
  const prerequisites = (Array.isArray(raw) ? raw : []).map((p: any) => {
    const prerequisiteNodeId = Number(
      typeof p === "number" || typeof p === "string"
        ? p
        : (p?.prerequisiteNodeId ?? p?.techNodeId ?? p?.prerequisite?.id ?? p?.id ?? 0),
    );
    const name =
      (typeof p === "object"
        ? (p?.prerequisiteName ?? p?.prerequisite?.name ?? p?.techNodeName ?? p?.name)
        : "") || prereqNameById(prerequisiteNodeId);
    return {
      id: typeof p === "object" ? p?.id : undefined,
      prerequisiteNodeId,
      prerequisite: { id: prerequisiteNodeId, name },
    };
  });
  return { ...(row as any), prerequisites };
}

function prereqNameById(id: number): string {
  const n = nodes.value.find((x) => Number(x.id) === Number(id));
  return n?.name ?? "";
}

/** 列表行可能不含 relations：编辑前补拉单行（GET /{id} 保证含 relations），避免整体替换时丢前置 */
async function withRelations(row: any): Promise<any> {
  if (row?.relations) return row;
  try {
    return normalizeTechNode(await techNodesApi.get(props.cid, row.id));
  } catch {
    return row;
  }
}

async function loadData() {
  loading.value = true;
  try {
    if (!props.cid) {
      nodes.value = [];
      return;
    }
    const res = await techNodesApi.list(props.cid, { page: 1, pageSize: 500 });
    nodes.value = (res.items || []).map((r) => normalizeTechNode(r));
    await nextTick();
    if (viewMode.value === "tree") renderTree();
  } catch (e) {
    nodes.value = [];
    ElMessage.error(errorMessage(e, "操作失败"));
  } finally {
    loading.value = false;
  }
}

function buildTreeData() {
  const nodeMap = new Map<number, any>();
  for (const n of nodes.value) {
    nodeMap.set(n.id, {
      id: n.id,
      name: `[T${n.tier}] ${n.name}`,
      value: n.name,
      description: n.description,
      tier: n.tier,
      _raw: n,
      children: [] as any[],
    });
  }

  const roots: any[] = [];
  const hasParent = new Set<number>();

  for (const n of nodes.value) {
    const prereqs = n.prerequisites || [];
    for (const p of prereqs) {
      const child = nodeMap.get(n.id);
      const parent = nodeMap.get(p.prerequisiteNodeId);
      if (child && parent) {
        parent.children.push(child);
        hasParent.add(n.id);
      }
    }
  }

  for (const [id, node] of nodeMap) {
    if (!hasParent.has(id)) roots.push(node);
  }

  if (roots.length === 0 && nodeMap.size > 0) {
    return { name: "科技树", children: Array.from(nodeMap.values()) };
  }

  return roots.length === 1 ? roots[0] : { name: "科技树", children: roots };
}

function buildTreeOpt() {
  return {
    tooltip: { trigger: "item" as const },
    series: [
      {
        type: "tree" as const,
        data: [buildTreeData()],
        orient: "LR" as const,
        symbolSize: 14,
        roam: true,
        scaleLimit: { min: 0.2, max: 5 },
        label: {
          position: "left" as const,
          verticalAlign: "middle" as const,
          align: "right" as const,
          fontSize: 12,
          color: "#1F1F1F",
        },
        leaves: {
          label: {
            position: "right" as const,
            verticalAlign: "middle" as const,
            align: "left" as const,
          },
        },
        lineStyle: { color: "#C0C4CC", width: 2, curveness: 0.5 },
        itemStyle: { color: "#6366f1", borderColor: "#4f46e5" },
        animationDuration: 300,
      },
    ],
  };
}

function renderTree() {
  if (!chartRef.value) return;
  if (chart) {
    chart.dispose();
    chart = null;
  }
  chart = echarts.init(chartRef.value);

  chart.setOption(buildTreeOpt());

  chart.off("click");
  chart.on("click", (params: any) => {
    if (params.data?._raw) {
      selectedNode.value = params.data._raw;
    }
  });

  // 自定义平移/缩放作用于内部 .tt-chart（图谱内容），白色背景卡片 .tt-pan-wrap 固定不动
  const wrap = chartRef.value!;
  wrap.style.transformOrigin = "0 0";
  let panning = false,
    panStart: [number, number] = [0, 0];
  let ox = 0,
    oy = 0,
    s = 1;

  // 清理之前的 mousedown 事件监听器
  if (mouseDownHandler) {
    wrap.removeEventListener("mousedown", mouseDownHandler);
  }
  mouseDownHandler = (e: MouseEvent) => {
    if (e.button !== 0) return;
    panning = true;
    panStart = [e.clientX - ox, e.clientY - oy];
  };
  wrap.addEventListener("mousedown", mouseDownHandler);

  const mover = (e: MouseEvent) => {
    if (!panning) return;
    ox = e.clientX - panStart[0];
    oy = e.clientY - panStart[1];
    wrap.style.transform = `translate(${ox}px, ${oy}px) scale(${s})`;
  };
  const uper = () => {
    panning = false;
  };

  // 清理之前的事件监听器
  if (mouseMoveHandler) {
    window.removeEventListener("mousemove", mouseMoveHandler);
  }
  if (mouseUpHandler) {
    window.removeEventListener("mouseup", mouseUpHandler);
  }

  mouseMoveHandler = mover;
  mouseUpHandler = uper;
  window.addEventListener("mousemove", mover);
  window.addEventListener("mouseup", uper);

  // 清理之前的 wheel 事件监听器
  if (wheelHandler) {
    wrap.removeEventListener("wheel", wheelHandler);
  }
  wheelHandler = (e: WheelEvent) => {
    e.preventDefault();
    const r = wrap.parentElement!.getBoundingClientRect();
    const mx = (e.clientX - r.left) / s,
      my = (e.clientY - r.top) / s;
    s = Math.max(0.2, Math.min(5, s * (e.deltaY > 0 ? 0.9 : 1.1)));
    ox = e.clientX - r.left - mx * s;
    oy = e.clientY - r.top - my * s;
    wrap.style.transform = `translate(${ox}px, ${oy}px) scale(${s})`;
  };
  wrap.addEventListener("wheel", wheelHandler, { passive: false });

  // 清理之前的 resize 事件监听器
  if (resizeHandler) {
    window.removeEventListener("resize", resizeHandler);
  }

  resizeHandler = () => chart?.resize();
  window.addEventListener("resize", resizeHandler);
  chart.resize();
}

function showDetail(row: any) {
  detailData.value = row;
  detailVisible.value = true;
}

function openCreate() {
  if (!props.cid) {
    ElMessage.warning("请先在「比赛管理」中选择一个比赛");
    return;
  }
  isEdit.value = false;
  editId.value = 0;
  form.name = "";
  form.description = "";
  form.tier = 0;
  form.researchCost = 0;
  form.prerequisiteIds = [];
  showDialog.value = true;
}

async function editNode(row: any) {
  const full = await withRelations(row);
  isEdit.value = true;
  editId.value = full.id;
  form.name = full.name;
  form.description = full.description || "";
  form.tier = full.tier;
  form.researchCost = full.researchCost || 0;
  form.prerequisiteIds = (full.prerequisites || []).map((p: any) => p.prerequisiteNodeId);
  showDialog.value = true;
}

async function handleSubmit() {
  submitting.value = true;
  try {
    // relations.prerequisites 同名数组整体替换（嵌套在 relations 下，与 GET 对称）
    const payload = {
      name: form.name,
      description: form.description,
      tier: form.tier,
      researchCost: form.researchCost,
      relations: {
        prerequisites: form.prerequisiteIds.map((id) => ({ prerequisiteNodeId: id })),
      },
    };
    if (isEdit.value) {
      await techNodesApi.update(props.cid, editId.value, payload);
    } else {
      await techNodesApi.create(props.cid, payload);
    }
    ElMessage.success(isEdit.value ? "已更新" : "已创建");
    showDialog.value = false;
    loadData();
  } catch (e) {
    ElMessage.error(errorMessage(e, "操作失败"));
  } finally {
    submitting.value = false;
  }
}

async function handleDelete(row: any) {
  let impact: DeleteImpact | null = null;
  try {
    impact = await techNodesApi.impact(props.cid, row.id);
  } catch {
    impact = null;
  }
  try {
    await confirmDeleteWithImpact(row.name ?? row.id, impact);
  } catch {
    return; // 用户取消
  }
  try {
    await techNodesApi.remove(props.cid, row.id);
    ElMessage.success("已删除");
    loadData();
  } catch (e) {
    ElMessage.error(errorMessage(e, "操作失败"));
  }
}
</script>

<style scoped>
/* ------------------------------------------------------------------
   数据管理统一骨架（9 个管理器共用同一约定）：
   工具条（标题 + 视图切换 + 新建）→ 提示 / 表格（或移动端卡片）；间距统一 16px
   ------------------------------------------------------------------ */
.techtree-manager {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.tt-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 0;
}
.tt-title {
  font-size: 20px;
  font-weight: 500;
  color: #1f1f1f;
  margin: 0;
}
.tt-actions {
  display: flex;
  gap: 8px;
}
/* 关系列为空时的占位「无」：统一弱化色 */
.cell-empty {
  color: var(--color-text-tertiary);
}
.tt-tree-container {
  display: flex;
  gap: 16px;
  height: calc(100vh - 200px); /* 回退 */
  height: calc(100dvh - 200px);
  overflow: hidden;
}
.tt-chart {
  width: 100%;
  height: 100%;
  min-height: 500px;
}
.tt-pan-wrap {
  flex: 1;
  overflow: hidden;
  position: relative;
  min-height: 500px;
  /* 白色背景/边框固定在视口卡片上，不被平移拖动；平移只作用于内部 .tt-chart 图谱内容 */
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  background: #fff;
}
.tt-tree-info {
  width: 260px;
  background: #fff;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.tt-tree-info h4 {
  font-size: 16px;
  font-weight: 500;
  color: #1f1f1f;
  margin: 0 0 12px;
}
.tt-info-row {
  font-size: 13px;
  color: #5c5c5c;
  margin-bottom: 6px;
}
.tt-info-label {
  display: inline-block;
  width: 64px;
  color: #8c8c8c;
  font-size: 12px;
}
.tt-info-actions {
  display: flex;
  gap: 8px;
  margin-top: auto;
  padding-top: 12px;
}
</style>
