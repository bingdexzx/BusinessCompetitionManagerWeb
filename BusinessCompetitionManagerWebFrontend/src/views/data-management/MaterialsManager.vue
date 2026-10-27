<template>
  <div class="materials-manager">
    <div class="mm-toolbar">
      <h2 class="mm-title">{{ canManage ? "原料管理" : "原料" }}</h2>
      <div class="mm-actions">
        <SearchToggle v-model="searchText" placeholder="搜索原料" />
        <el-button v-if="canManage" type="primary" @click="openCreate">+ 新建</el-button>
      </div>
    </div>

    <div v-if="!cid" class="notice notice--warning">
      请先在「比赛管理」中选择一个比赛
    </div>

    <el-table
      v-if="!isPhone"
      v-loading="loading"
      :data="filteredMaterials"
      border
      stripe
      class="anim-fade-in-up"
      style="width: 100%"
    >
      <el-table-column prop="name" label="名称" min-width="160" />
      <el-table-column label="产地" min-width="160">
        <template #default="{ row }">
          <span v-if="!parseOriginToArray(row.origin).length" class="cell-empty">—</span>
          <el-tag
            v-for="origin in parseOriginToArray(row.origin)"
            :key="origin"
            size="small"
            style="margin: 2px"
          >
            {{ origin }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="价格（按地点）" min-width="220">
        <template #default="{ row }">
          <div v-if="!getRowNodePrices(row).length" class="np-none">—</div>
          <div v-for="p in getRowNodePrices(row)" :key="p.nodeId" class="np-line">
            <span class="np-name">{{ p.nodeName }}</span>
            <span class="np-val value-num">{{ formatMoney(p.price) }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column
        prop="carbonEmissionCoefficient"
        label="碳排放系数"
        align="right"
        min-width="130"
      >
        <template #default="{ row }">
          <span class="value-num">{{ row.carbonEmissionCoefficient }}</span>
        </template>
      </el-table-column>
      <el-table-column label="类型">
        <template #default="{ row }">
          <el-tag :type="row.type === 'SPECIAL' ? 'danger' : ''">{{
            row.type === "SPECIAL" ? "特殊原料" : "普通原料"
          }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column v-if="canManage" label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="openDetail(row)">详情</el-button>
          <el-button v-if="canManage" size="small" @click="openEdit(row)">编辑</el-button>
          <el-button v-if="canManage" size="small" type="danger" plain @click="handleDelete(row)"
            >删除</el-button
          >
        </template>
      </el-table-column>
      <template #empty>
        <el-empty
          v-if="!loading"
          :image-size="72"
          :description="searchText ? '没有匹配的记录' : '暂无原料数据'"
        />
      </template>
    </el-table>

    <MobileCards
      v-else
      :data="filteredMaterials"
      :columns="materialColumns"
      :loading="loading"
      :row-key="(row: any) => row.id"
      :empty-text="searchText ? '没有匹配的记录' : '暂无原料数据'"
      class="anim-fade-in-up"
    >
      <template #origin="{ row }">
        <span v-if="!parseOriginToArray(row.origin).length" class="cell-empty">—</span>
        <el-tag
          v-for="origin in parseOriginToArray(row.origin)"
          :key="origin"
          size="small"
          style="margin: 2px"
        >
          {{ origin }}
        </el-tag>
      </template>
      <template #nodePrices="{ row }">
        <div v-if="!getRowNodePrices(row).length" class="np-none">—</div>
        <div v-for="p in getRowNodePrices(row)" :key="p.nodeId" class="np-line">
          <span class="np-name">{{ p.nodeName }}</span>
          <span class="np-val value-num">{{ formatMoney(p.price) }}</span>
        </div>
      </template>
      <template #type="{ row }">
        <el-tag :type="row.type === 'SPECIAL' ? 'danger' : ''">{{
          row.type === "SPECIAL" ? "特殊原料" : "普通原料"
        }}</el-tag>
      </template>
      <template #actions="{ row }">
        <el-button size="small" @click="openDetail(row)">详情</el-button>
        <el-button v-if="canManage" size="small" @click="openEdit(row)">编辑</el-button>
        <el-button v-if="canManage" size="small" type="danger" plain @click="handleDelete(row)"
          >删除</el-button
        >
      </template>
    </MobileCards>

    <el-dialog append-to-body v-model="showDetail" title="原料详情" width="480px">
      <el-descriptions :column="1" border>
        <el-descriptions-item label="名称">{{ detailRow?.name }}</el-descriptions-item>
        <el-descriptions-item label="产地">
          <span v-if="!parseOriginToArray(detailRow?.origin).length" class="cell-empty">—</span>
          <el-tag
            v-for="origin in parseOriginToArray(detailRow?.origin)"
            :key="origin"
            size="small"
            style="margin: 2px"
          >
            {{ origin }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="碳排放系数">{{ detailRow?.carbonEmissionCoefficient }}</el-descriptions-item>
        <el-descriptions-item label="类型">{{
          detailRow?.type === "SPECIAL" ? "特殊原料" : "普通原料"
        }}</el-descriptions-item>
        <el-descriptions-item label="价格">
          <span v-if="!getRowNodePrices(detailRow).length">（无按地点价格）</span>
          <ul v-else class="np-detail">
            <li v-for="p in getRowNodePrices(detailRow)" :key="p.nodeId">
              {{ p.nodeName }}：<span class="value-num">{{ formatMoney(p.price) }}</span>
            </li>
          </ul>
        </el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ formatDateTime(detailRow?.createdAt) }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ formatDateTime(detailRow?.updatedAt) }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>

    <el-dialog append-to-body v-model="showDialog" :title="isEdit ? '编辑原料' : '新建原料'" width="520px">
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="120px">
        <el-form-item label="名称" prop="name"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="产地" prop="origin">
          <el-select
            v-model="form.origin"
            class="origin-select"
            multiple
            filterable
            allow-create
            placeholder="选择地图节点（可多选）"
            style="width: 100%"
          >
            <el-option
              v-for="node in mapNodes"
              :key="node.id"
              :label="`${node.name} (${node.region})`"
              :value="node.name"
            />
          </el-select>
          <div class="origin-hint">未选择产地表示任何节点都没有这种原料，无需填写价格。</div>
        </el-form-item>
        <el-form-item label="碳排放系数" required
          ><el-input-number
            v-model="form.carbonEmissionCoefficient"
            :min="0"
            :precision="2"
            style="width: 100%"
        /></el-form-item>
        <el-form-item label="类型" required>
          <el-select v-model="form.type" style="width: 100%">
            <el-option label="普通原料" value="NORMAL" />
            <el-option label="特殊原料" value="SPECIAL" />
          </el-select>
        </el-form-item>
        <el-form-item label="价格" required>
          <template v-if="hasOrigin">
            <div class="np-editor">
              <div v-if="!originNodes.length" class="np-empty">（所选产地未匹配到地图节点）</div>
              <div v-for="node in originNodes" :key="node.id" class="np-row">
                <span class="np-label">{{ node.name }}<small>（{{ node.region }}）</small></span>
                <BigNumberInput
                  :model-value="form.nodePrices[node.id] ?? ''"
                  :min="0"
                  size="small"
                  style="width: 120px"
                  @update:model-value="(v: string) => onNodePriceChange(node.id, v)"
                />
              </div>
            </div>
            <div class="np-hint">为选中的产地节点分别填写原料价格；计算「原料总价格」时按参与方所在地节点取对应价。</div>
          </template>
          <div v-else class="price-hint">请先在上方选择产地（节点），才会显示对应节点的价格输入框。</div>
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
import { ref, reactive, computed, watch, onMounted } from "vue";
import { ElMessage } from "element-plus";
import type { FormRules } from "element-plus";
import { listMapNodes, materialsApi } from "@/api/basedataApi";
import { confirmDeleteWithImpact, type DeleteImpact } from "@/utils/deleteConfirm";
import { useAuthStore } from "@/stores/auth";
import { errorMessage } from "@/utils/errors";
import { formatDateTime } from "@/utils/format";
import MobileCards from "@/components/common/MobileCards.vue";
import SearchToggle from "@/components/common/SearchToggle.vue";
import BigNumberInput from "@/components/common/BigNumberInput.vue";
import { useBreakpoint } from "@/composables/useBreakpoint";
import { useResourceRefresh } from "@/composables/useNotifications";

interface MapNodeItem {
  id: number;
  name: string;
  region: string;
}

const props = defineProps<{ cid: string }>();
const authStore = useAuthStore();
const { isPhone } = useBreakpoint();
const materials = ref<any[]>([]);
const mapNodes = ref<MapNodeItem[]>([]);
const loading = ref(false);
const searchText = ref("");

/** 系统超管或本比赛超管：可新建/编辑/删除（其余只读） */
const canManage = computed(
  () =>
    authStore.isSuperuser ||
    authStore.memberships.some(
      (m) => String(m.id) === props.cid && m.identity === "COMP_SUPER_ADMIN",
    ),
);

const materialColumns = [
  { prop: "name", label: "名称" },
  { label: "产地", slot: "origin" },
  { label: "价格（按地点）", slot: "nodePrices" },
  { prop: "carbonEmissionCoefficient", label: "碳排放系数" },
  { label: "类型", slot: "type" },
];

const filteredMaterials = computed(() => {
  if (!searchText.value) return materials.value;
  const q = searchText.value.toLowerCase();
  return materials.value.filter(
    (m: any) =>
      m.name?.toLowerCase().includes(q) ||
      formatOrigin(m.origin).toLowerCase().includes(q),
  );
});
const showDialog = ref(false);
const showDetail = ref(false);
const detailRow = ref<any>(null);
const isEdit = ref(false);
const editId = ref(0);
const submitting = ref(false);

/** nodePrices 兼容 JSON 字符串（旧项目形态）与对象两种形态 */
function parseNodePrices(raw: any): Record<string, number | string> {
  if (!raw) return {};
  let p: any = raw;
  if (typeof raw === "string") {
    try {
      p = JSON.parse(raw);
    } catch {
      return {};
    }
  }
  if (p && typeof p === "object" && !Array.isArray(p)) return p;
  return {};
}

// 解析某行原料的按地点价格，关联地图节点名称展示：左节点名、右价格。
function getRowNodePrices(row: any) {
  const parsed = parseNodePrices(row?.nodePrices);
  const nodeNameById = new Map((mapNodes.value || []).map((n: any) => [n.id, n.name]));
  return Object.entries(parsed)
    // 兼容数字与数字字符串（大数安全：新数据以字符串形态存储）
    .filter(([, v]) => typeof v === "number" || (typeof v === "string" && /^[+-]?\d+(\.\d+)?$/.test(v)))
    .map(([k, v]) => ({ nodeId: Number(k), price: v, nodeName: nodeNameById.get(Number(k)) || `节点#${k}` }));
}

const formRef = ref();
const formRules: FormRules = {
  name: [{ required: true, message: "请输入名称", trigger: "blur" }],
  origin: [
    {
      required: true,
      type: "array",
      message: "请选择产地",
      trigger: "change",
    },
  ],
};

const form = reactive<{
  name: string;
  origin: string[];
  carbonEmissionCoefficient: number;
  type: string;
  nodePrices: Record<number, number | string>;
}>({
  name: "",
  origin: [],
  carbonEmissionCoefficient: 0,
  type: "NORMAL",
  nodePrices: {},
});

// 只有选择了产地（节点），该原料才存在于节点上，才允许填写价格。
const hasOrigin = computed(() => (form.origin?.length ?? 0) > 0);

// 产地清空时，价格与按地点价格失去意义，同步清空，避免存下"无产地却有价"的脏数据。
watch(
  () => form.origin,
  (val) => {
    if (!val || val.length === 0) {
      form.nodePrices = {};
    }
  },
);

// 价格（按地点）只针对选中的产地节点展示输入框，而非全部地图节点。
const originNodes = computed(() =>
  (mapNodes.value || []).filter((n: any) => (form.origin || []).includes(n.name)),
);

// 产地可多选：存储为 JSON 数组字符串（如 ["北京","上海"]），
// 兼容旧的单字符串产地与未设置（undefined/空）。
function formatOrigin(origin: any): string {
  if (!origin) return "—";
  let arr: any = origin;
  if (typeof origin === "string") {
    try {
      const p = JSON.parse(origin);
      arr = Array.isArray(p) ? p : [origin];
    } catch {
      arr = [origin];
    }
  }
  if (Array.isArray(arr)) return arr.length ? arr.join("、") : "—";
  return String(origin);
}

// 产地列统一用标签展示（关系列视觉约定）：把存储形态解析为节点名数组。
function parseOriginToArray(origin: any): string[] {
  if (!origin) return [];
  if (Array.isArray(origin)) return origin.map(String);
  if (typeof origin === "string") {
    const s = origin.trim();
    if (!s) return [];
    try {
      const p = JSON.parse(s);
      if (Array.isArray(p)) return p.map(String);
      return [s];
    } catch {
      return [s];
    }
  }
  return [];
}

async function loadMaterials() {
  if (!props.cid) return;
  try {
    const res = await materialsApi.list(props.cid, { page: 1, pageSize: 200 });
    materials.value = res.items || [];
  } catch (e) {
    ElMessage.error(errorMessage(e, "操作失败"));
  }
}

async function loadMapNodes() {
  try {
    const items = await listMapNodes(props.cid);
    mapNodes.value = (items || []).map((n) => ({
      id: Number(n.id),
      name: String(n.name ?? ""),
      region: String(n.region ?? ""),
    }));
  } catch {
    // 地图节点加载失败不阻塞原料列表：产地选择降级为可自由输入（allow-create）
    mapNodes.value = [];
  }
}

async function reloadAll() {
  loading.value = true;
  try {
    await loadMaterials();
    await loadMapNodes();
  } finally {
    loading.value = false;
  }
}

onMounted(reloadAll);

// 资源变更实时刷新：basedata 变更时自动重拉原料列表与地图节点选项
useResourceRefresh(["basedata"], reloadAll);

function openDetail(row: any) {
  detailRow.value = row;
  showDetail.value = true;
}

function onNodePriceChange(nodeId: number, v: string) {
  // 大数安全：价格以字符串保存（BigNumberInput 输出干净数字串），后端按 Decimal 解析
  if (v === "" || Number(v) <= 0) {
    delete form.nodePrices[nodeId];
  } else {
    form.nodePrices[nodeId] = v;
  }
}

function openCreate() {
  if (!props.cid) {
    ElMessage.warning("请先在「比赛管理」中选择一个比赛");
    return;
  }
  isEdit.value = false;
  editId.value = 0;
  form.name = "";
  form.origin = [];
  form.carbonEmissionCoefficient = 0;
  form.type = "NORMAL";
  form.nodePrices = {};
  showDialog.value = true;
}

function openEdit(row: any) {
  isEdit.value = true;
  editId.value = row.id;
  form.name = row.name;
  form.origin = parseOriginToArray(row.origin);
  form.carbonEmissionCoefficient = row.carbonEmissionCoefficient;
  form.type = row.type || "NORMAL";
  const np: Record<number, number | string> = {};
  for (const [k, v] of Object.entries(parseNodePrices(row.nodePrices))) {
    if (typeof v === "number" || (typeof v === "string" && /^[+-]?\d+(\.\d+)?$/.test(v))) {
      np[Number(k)] = v;
    }
  }
  form.nodePrices = np;
  showDialog.value = true;
}

async function handleSubmit() {
  const valid = await formRef.value
    ?.validate()
    .then(() => true)
    .catch(() => false);
  if (!valid) return;

  submitting.value = true;
  try {
    const payload = {
      ...form,
      origin: JSON.stringify(form.origin || []),
      nodePrices: hasOrigin.value ? JSON.stringify(form.nodePrices || {}) : "{}",
    };
    if (isEdit.value) {
      await materialsApi.update(props.cid, editId.value, payload);
    } else {
      await materialsApi.create(props.cid, payload);
    }
    ElMessage.success(isEdit.value ? "已更新" : "已创建");
    showDialog.value = false;
    const res = await materialsApi.list(props.cid, { page: 1, pageSize: 200 });
    materials.value = res.items || [];
  } catch (e) {
    ElMessage.error(errorMessage(e, "操作失败"));
  } finally {
    submitting.value = false;
  }
}

async function handleDelete(row: any) {
  let impact: DeleteImpact | null = null;
  try {
    impact = await materialsApi.impact(props.cid, row.id);
  } catch {
    // 取级联影响信息失败时不阻塞删除，按普通删除提示处理
  }
  try {
    await confirmDeleteWithImpact(row.name, impact, {
      baseMessage: `确定删除 "${row.name}" 吗？此操作不可恢复。删除后将一并清除其零件配比关联。`,
    });
  } catch {
    return; // 用户取消
  }
  try {
    await materialsApi.remove(props.cid, row.id);
    ElMessage.success("已删除");
    const res = await materialsApi.list(props.cid, { page: 1, pageSize: 200 });
    materials.value = res.items || [];
  } catch (e) {
    ElMessage.error(errorMessage(e, "操作失败"));
  }
}

// ---------- 金额展示（照旧 utils/format 的 formatMoney：千分位、最多 2 位小数、大数安全） ----------
const JS_MAX_SAFE = 9007199254740991n; // BigInt(2^53 - 1)

function toBigIntSafe(s: string): bigint | null {
  try {
    const cleaned = s.trim().replace(/,/g, "");
    if (!/^[+-]?\d+(\.\d+)?$/.test(cleaned)) return null;
    // 小数部分截断进 BigInt（千分位只关心整数部分；小数由 frac 通道处理）
    const [intPart] = cleaned.split(".");
    return BigInt(intPart || "0");
  } catch {
    return null;
  }
}

/** 大数安全千分位：整数部分用 BigInt 分组，小数部分原样保留（最多 prec 位）。 */
function groupThousands(s: string, prec: number): string {
  const trimmed = s.trim();
  if (!/^[+-]?\d+(\.\d+)?$/.test(trimmed)) return trimmed;
  const neg = trimmed.startsWith("-");
  const body = neg || trimmed.startsWith("+") ? trimmed.slice(1) : trimmed;
  const [intRaw, fracRaw = ""] = body.split(".");
  const intPart = intRaw || "0";
  // BigInt 分组（避免 Number 化大数）
  const bi = toBigIntSafe(intPart) ?? 0n;
  const grouped = bi.toLocaleString("en-US");
  const frac = prec > 0 && fracRaw ? "." + fracRaw.slice(0, prec) : "";
  return (neg ? "-" : "") + grouped + frac;
}

/**
 * 金额格式化：中文千分位、最多 2 位小数；null/NaN 显示"—"。
 * 大数安全：超过 2^53 的字符串大数走 BigInt 分组（不经 Number，10^23+ 无损，
 * 小数截断到 2 位）；安全范围内的数值保持原有 Number.toLocaleString 行为（含四舍五入）。
 */
function formatMoney(n: number | string | null | undefined): string {
  if (n == null || n === "") return "—";
  const s = String(n).trim();
  if (!/^[+-]?\d+(\.\d+)?$/.test(s)) return "—"; // NaN / 非数字串
  const bi = toBigIntSafe(s);
  const withinSafe =
    bi !== null && bi <= JS_MAX_SAFE && bi >= -JS_MAX_SAFE && !s.includes(".");
  if (withinSafe) {
    return Number(s).toLocaleString("zh-CN", { maximumFractionDigits: 2 });
  }
  // 大数（或大数带小数）：整数部分 BigInt 分组 + 小数最多 2 位（截断，不四舍五入）
  return groupThousands(s, 2);
}
</script>

<style scoped>
/* ------------------------------------------------------------------
   数据管理统一骨架（9 个管理器共用同一约定）：
   工具条（标题 + 搜索 + 新建）→ 提示 / 表格（或移动端卡片）；间距统一 16px
   ------------------------------------------------------------------ */
.materials-manager {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.mm-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 0;
}
.mm-title {
  font-size: 20px;
  font-weight: 500;
  color: #1f1f1f;
  margin: 0;
}
.mm-actions {
  display: flex;
  gap: 8px;
}
/* 关系列为空时的占位「—」：统一弱化色 */
.cell-empty {
  color: var(--color-text-tertiary);
}
.np-editor {
  width: 100%;
  max-height: 220px;
  overflow-y: auto;
  border: 1px solid #dcdfe6;
  border-radius: 6px;
  padding: 6px 8px;
}
/* 产地多选框：取消折叠，让所有已选节点名都能显示（可滚动查看） */
.origin-select :deep(.el-select__wrapper) {
  min-height: 40px;
  align-items: flex-start;
  padding-top: 4px;
  padding-bottom: 4px;
}
.origin-select :deep(.el-select__tags) {
  flex-wrap: wrap;
  max-height: 120px;
  overflow-y: auto;
}
.origin-hint,
.price-hint {
  font-size: 12px;
  color: #909399;
  line-height: 1.5;
  margin-top: 4px;
}
.price-hint {
  color: #c4564d;
}
.np-empty {
  font-size: 12px;
  color: #909399;
}
.np-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 3px 0;
}
.np-label {
  font-size: 13px;
  color: #303133;
}
.np-label small {
  color: #909399;
  margin-left: 4px;
}
.np-hint {
  font-size: 12px;
  color: #909399;
  line-height: 1.5;
  margin-top: 4px;
}
.np-detail {
  margin: 0;
  padding-left: 18px;
}
/* 列表「价格（按地点）」列：左节点名、右价格，逐地点平铺展示 */
.np-none {
  color: var(--color-text-tertiary);
}
.np-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 2px 0;
  line-height: 1.4;
}
.np-name {
  font-size: 13px;
  color: #303133;
  text-align: left;
}
.np-val {
  font-size: 13px;
  color: #303133;
  text-align: right;
  font-variant-numeric: tabular-nums;
}
</style>
