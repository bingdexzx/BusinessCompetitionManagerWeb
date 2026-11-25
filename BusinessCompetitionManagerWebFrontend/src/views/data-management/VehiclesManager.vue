<template>
  <div class="vehicles-manager page">
    <PageHeader :title="canManage ? '载具管理' : '载具'">
      <template #actions>
      <div class="dm-actions">
        <SearchToggle v-model="searchText" placeholder="搜索载具" />
        <el-button v-if="canManage" type="primary" @click="openCreate">新建</el-button>
      </div>
      </template>
    </PageHeader>

    <el-card shadow="never" class="dm-card">

    <div v-if="!cid" class="notice notice--warning">
      请先在「比赛列表」中选择一个比赛
    </div>

        <TableSkeleton v-if="loading && !hasLoaded" :rows="6" />
<el-table
      v-if="!isPhone"
      v-loading="loading && hasLoaded"
      :data="pagedRows"
      border
      stripe
      class="anim-fade-in-up"
      style="width: 100%"
     size="small">
      <el-table-column prop="name" label="名称" min-width="160" />
      <el-table-column prop="fuelConsumptionPerKm" label="每公里油耗" align="right" min-width="120">
        <template #default="{ row }">
          <span class="value-num">{{ row.fuelConsumptionPerKm }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="maxMaterialCargo" label="最大原料载货量" align="right" min-width="140">
        <template #default="{ row }">
          <span class="value-num">{{ row.maxMaterialCargo }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="maxPartCargo" label="最大零件载货量" align="right" min-width="140">
        <template #default="{ row }">
          <span class="value-num">{{ row.maxPartCargo }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="maxProductCargo" label="最大产品载货量" align="right" min-width="140">
        <template #default="{ row }">
          <span class="value-num">{{ row.maxProductCargo }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="price" label="价格" align="right" min-width="120">
        <template #default="{ row }">
          <span class="value-num">{{ row.price }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="carbonEmission" label="碳排放系数" align="right" min-width="120">
        <template #default="{ row }">
          <span class="value-num">{{ row.carbonEmission }}</span>
        </template>
      </el-table-column>
      <el-table-column v-if="canManage" label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="showDetail(row)" link type="primary">详情</el-button>
          <el-button v-if="canManage" size="small" @click="openEdit(row)" link type="primary">编辑</el-button>
          <el-button v-if="canManage" size="small" type="danger" @click="handleDelete(row)" link>删除</el-button
          >
        </template>
      </el-table-column>
      <template #empty>
        <el-empty
          v-if="!loading"
          :image-size="72"
          :description="searchText ? '暂无匹配记录' : '暂无载具数据'"
        />
      </template>
    </el-table>


    <MobileCards
      v-else
      :data="pagedRows"
      :columns="vehicleColumns"
      :loading="loading"
      :row-key="(row: any) => row.id"
      :empty-text="searchText ? '暂无匹配记录' : '暂无载具数据'"
      class="anim-fade-in-up"
    >
      <template #actions="{ row }">
        <el-button size="small" @click="showDetail(row)">详情</el-button>
        <el-button v-if="canManage" size="small" @click="openEdit(row)">编辑</el-button>
        <el-button v-if="canManage" size="small" type="danger" @click="handleDelete(row)" link>删除</el-button
        >
      </template>
    </MobileCards>
    <TablePager v-model:page="page" v-model:page-size="pageSize" :total="totalRows" />

    <el-drawer direction="rtl" append-to-body v-model="detailVisible" title="载具详情" size="480px">
      <el-descriptions v-if="detailData" :column="1" border>
        <el-descriptions-item label="名称">{{ detailData.name }}</el-descriptions-item>
        <el-descriptions-item label="每公里油耗">
          <span class="value-num">{{ detailData.fuelConsumptionPerKm }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="最大原料载货量">
          <span class="value-num">{{ detailData.maxMaterialCargo }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="最大零件载货量">
          <span class="value-num">{{ detailData.maxPartCargo }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="最大产品载货量">
          <span class="value-num">{{ detailData.maxProductCargo }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="价格">
          <span class="value-num">{{ (detailData as any).price }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="碳排放系数">
          <span class="value-num">{{ (detailData as any).carbonEmission }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="燃料">
          <el-tag v-if="detailData.fuelId" size="small">{{
            getFuelName(detailData.fuelId)
          }}</el-tag>
          <span v-else class="cell-empty">-</span>
        </el-descriptions-item>
        <el-descriptions-item label="可通过路径类型">
          <template v-if="(detailData as any).vehiclePathTypes?.length">
            <el-tag
              v-for="vpt in (detailData as any).vehiclePathTypes"
              :key="vpt.pathTypeId ?? vpt.pathType?.id"
              size="small"
              style="margin: 2px"
            >
              {{ vpt.pathType?.name || getPathTypeNameById(vpt.pathTypeId) }}
            </el-tag>
          </template>
          <span v-else class="cell-empty">-</span>
        </el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ formatDateTime((detailData as any).createdAt) }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ formatDateTime((detailData as any).updatedAt) }}</el-descriptions-item>
      </el-descriptions>
    </el-drawer>

    <el-dialog
      append-to-body
      v-model="dialogVisible"
      :title="isEdit ? '编辑载具管理' : '新建载具管理'"
      width="560px"
      destroy-on-close
      @closed="resetForm"
    >
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="96px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入载具名称" />
        </el-form-item>

        <el-form-item label="燃料" prop="fuelId" required>
          <el-select v-model="form.fuelId" placeholder="选择燃料" filterable style="width: 100%">
            <el-option v-for="f in fuelOptions" :key="f.value" :label="f.label" :value="f.value" />
          </el-select>
        </el-form-item>

        <el-form-item label="每公里油耗" prop="fuelConsumptionPerKm">
          <el-input-number
            v-model="form.fuelConsumptionPerKm"
            :min="0"
            :precision="2"
            placeholder="每公里油耗"
            style="width: 100%"
          />
        </el-form-item>

        <el-form-item label="最大原料载货量" prop="maxMaterialCargo">
          <BigNumberInput
            v-model="form.maxMaterialCargo"
            :min="0"
            placeholder="最大原料载货量"
            style="width: 100%"
          />
        </el-form-item>

        <el-form-item label="最大零件载货量" prop="maxPartCargo">
          <BigNumberInput
            v-model="form.maxPartCargo"
            :min="0"
            placeholder="最大零件载货量"
            style="width: 100%"
          />
        </el-form-item>

        <el-form-item label="最大产品载货量" prop="maxProductCargo">
          <BigNumberInput
            v-model="form.maxProductCargo"
            :min="0"
            placeholder="最大产品载货量"
            style="width: 100%"
          />
        </el-form-item>

        <el-form-item label="价格" prop="price">
          <BigNumberInput v-model="form.price" :min="0" placeholder="价格" style="width: 100%" />
        </el-form-item>

        <el-form-item label="碳排放系数" prop="carbonEmission">
          <el-input-number
            v-model="form.carbonEmission"
            :min="0"
            :precision="4"
            placeholder="碳排放系数"
            style="width: 100%"
          />
        </el-form-item>

        <el-form-item label="可通过路径类型" required>
          <el-select
            v-model="form.pathTypeIds"
            multiple
            filterable
            placeholder="请选择路径类型"
            style="width: 100%"
          >
            <el-option
              v-for="pt in pathTypeOptions"
              :key="pt.value"
              :label="pt.label"
              :value="pt.value"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">保存</el-button>
      </template>
    </el-dialog>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import TablePager from '@/components/common/TablePager.vue'
/* eslint-disable @typescript-eslint/no-explicit-any -- 基础数据行/画布事件字段动态变化，逐字段建模收益低 */
import { ref, reactive, computed, onMounted } from "vue";
import TableSkeleton from '@/components/common/TableSkeleton.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import { ElMessage } from "element-plus";
import type { FormInstance, FormRules } from "element-plus";
import { fuelsApi, pathTypesApi, vehiclesApi } from "@/api/basedataApi";
import { confirmDeleteWithImpact, type DeleteImpact } from "@/utils/deleteConfirm";
import { useAuthStore } from "@/stores/auth";
import { errorMessage } from "@/utils/errors";
import { formatDateTime } from "@/utils/format";
import MobileCards from "@/components/common/MobileCards.vue";
import SearchToggle from "@/components/common/SearchToggle.vue";
import BigNumberInput from "@/components/common/BigNumberInput.vue";
import { useBreakpoint } from "@/composables/useBreakpoint";
import { useResourceRefresh } from "@/composables/useNotifications";

interface VehicleItem {
  id: number;
  name: string;
  fuelConsumptionPerKm: number;
  maxMaterialCargo?: number;
  maxPartCargo?: number;
  maxProductCargo?: number;
  fuelId?: number;
  pathTypeIds?: number[];
  [key: string]: any;
}

const props = defineProps<{ cid: string }>();
const authStore = useAuthStore();
const { isPhone } = useBreakpoint();
const data = ref<VehicleItem[]>([]);
const loading = ref(false);
/** 首屏骨架 → 之后刷新用 v-loading */
const hasLoaded = ref(false);
const searchText = ref("");

/** 系统超级管理员或本比赛超级管理员：可新建/编辑/删除（其余只读） */
const canManage = computed(() => authStore.isSuperuser);

const vehicleColumns = [
  { prop: "name", label: "名称" },
  { prop: "fuelConsumptionPerKm", label: "每公里油耗" },
  { prop: "maxMaterialCargo", label: "最大原料载货量" },
  { prop: "maxPartCargo", label: "最大零件载货量" },
  { prop: "maxProductCargo", label: "最大产品载货量" },
  { prop: "price", label: "价格" },
  { prop: "carbonEmission", label: "碳排放系数" },
];
const dialogVisible = ref(false);
const isEdit = ref(false);
const editingId = ref<number | null>(null);
const submitting = ref(false);
const formRef = ref<FormInstance>();
const detailVisible = ref(false);
const detailData = ref<VehicleItem | null>(null);

const fuelOptions = ref<{ label: string; value: number }[]>([]);
const pathTypeOptions = ref<{ label: string; value: number }[]>([]);

const form = reactive<{
  name: string;
  fuelId: number | null;
  fuelConsumptionPerKm: number;
  // ★ 原 maxCargo 拆分为三类载货量（D16）
  maxMaterialCargo: number | string;
  maxPartCargo: number | string;
  maxProductCargo: number | string;
  price: number | string;
  carbonEmission: number;
  pathTypeIds: number[];
}>({
  name: "",
  fuelId: null,
  fuelConsumptionPerKm: 0,
  // ★ 原 maxCargo 拆分为三类载货量（D16）
  maxMaterialCargo: 0,
  maxPartCargo: 0,
  maxProductCargo: 0,
  price: 0,
  carbonEmission: 0,
  pathTypeIds: [],
});

const formRules: FormRules = {
  name: [{ required: true, message: "请输入载具名称", trigger: "blur" }],
  fuelConsumptionPerKm: [{ required: true, message: "请输入每公里油耗", trigger: "blur" }],
  maxMaterialCargo: [{ required: true, message: "请输入最大原料载货量", trigger: "blur" }],
  maxPartCargo: [{ required: true, message: "请输入最大零件载货量", trigger: "blur" }],
  maxProductCargo: [{ required: true, message: "请输入最大产品载货量", trigger: "blur" }],
  price: [{ required: true, message: "请输入价格", trigger: "blur" }],
  carbonEmission: [{ required: true, message: "请输入碳排放系数", trigger: "blur" }],
};

const filteredData = computed(() => {
  const list = Array.isArray(data.value) ? data.value : [];
  if (!searchText.value) return list;
  const q = searchText.value.toLowerCase();
  return list.filter(
    (item) =>
      String(item?.name ?? "")
        .toLowerCase()
        .includes(q) || String(item?.fuelConsumptionPerKm ?? "").includes(q),
  );
});

onMounted(() => {
  loadData();
  loadFuelOptions();
  loadPathTypeOptions();
});

// 资源变更实时刷新：basedata 变更时自动重拉当前列表（保留搜索/选中状态）

// 分页（客户端分页：数据量 ≤ 数百行，服务端分页留给合同/日志等大表）
const page = ref(1)
const pageSize = ref(20)
const totalRows = computed(() => filteredData.value.length)
const pagedRows = computed(() => {
  const maxPage = Math.max(1, Math.ceil(totalRows.value / pageSize.value))
  const current = Math.min(page.value, maxPage)
  const start = (current - 1) * pageSize.value
  return filteredData.value.slice(start, start + pageSize.value)
})

useResourceRefresh(["basedata"], loadData);

/**
 * 行内路径类型归一化：新契约 relations.pathTypes = [{ id, pathTypeId, pathTypeName }]
 * （join 行 id 用于 upsert）；展示层沿用旧页面的 vehiclePathTypes / pathType.name 结构。
 */
function normalizeVehicle(row: any): VehicleItem {
  const rel = row?.relations ?? {};
  const raw = rel.pathTypes ?? row?.vehiclePathTypes ?? row?.pathTypeIds ?? [];
  const list: any[] = Array.isArray(raw) ? raw : [];
  const vehiclePathTypes = list.map((v: any) => {
    const id = Number(
      typeof v === "number" || typeof v === "string"
        ? v
        : (v?.pathTypeId ?? v?.pathType?.id ?? v?.id ?? 0),
    );
    const name =
      (typeof v === "object" ? (v?.pathTypeName ?? v?.pathType?.name ?? v?.name) : "") || "";
    return {
      id: typeof v === "object" ? v?.id : undefined,
      pathTypeId: id,
      pathType: { id, name },
    };
  });
  return { ...(row as any), vehiclePathTypes } as VehicleItem;
}

async function loadData() {
  loading.value = true;
  try {
    if (!props.cid) {
      data.value = [];
      return;
    }
    const res = await vehiclesApi.list(props.cid, { page: 1, pageSize: 100 });
    data.value = (res.items || []).map((r) => normalizeVehicle(r));
  } catch (e) {
    data.value = [];
    ElMessage.error(errorMessage(e, "操作失败"));
  } finally {
    loading.value = false;
  hasLoaded.value = true;
  }
}

async function loadFuelOptions() {
  try {
    const res = await fuelsApi.list(props.cid, { page: 1, pageSize: 200 });
    fuelOptions.value = (res.items || []).map((f: any) => ({
      label: String(f.name ?? ""),
      value: Number(f.id),
    }));
  } catch {
    /* 加载选项失败不阻塞列表 */
  }
}

async function loadPathTypeOptions() {
  try {
    const res = await pathTypesApi.list(props.cid, { page: 1, pageSize: 200 });
    pathTypeOptions.value = (res.items || []).map((pt: any) => ({
      label: String(pt.name ?? ""),
      value: Number(pt.id),
    }));
  } catch {
    /* 加载选项失败不阻塞列表 */
  }
}

function showDetail(row: VehicleItem) {
  detailData.value = row;
  detailVisible.value = true;
}

function getFuelName(id: number | null | undefined): string {
  if (!id) return "-";
  const f = fuelOptions.value.find((o) => o.value === id);
  return f?.label || "-";
}

function getPathTypeNameById(id: number): string {
  const pt = pathTypeOptions.value.find((o) => o.value === id);
  return pt?.label || `#${id}`;
}

function openCreate() {
  if (!props.cid) {
    ElMessage.warning("请先在「比赛列表」中选择一个比赛");
    return;
  }
  isEdit.value = false;
  editingId.value = null;
  form.name = "";
  form.fuelId = null;
  form.fuelConsumptionPerKm = 0;
  // ★ 原 maxCargo 拆分为三类载货量（D16）
  form.maxMaterialCargo = 0;
  form.maxPartCargo = 0;
  form.maxProductCargo = 0;
  form.price = 0;
  form.carbonEmission = 0;
  form.pathTypeIds = [];
  dialogVisible.value = true;
}

function openEdit(row: VehicleItem) {
  isEdit.value = true;
  editingId.value = row.id;
  form.name = row.name || "";
  form.fuelId = row.fuelId ?? null;
  form.fuelConsumptionPerKm = row.fuelConsumptionPerKm ?? 0;
  // ★ 原 maxCargo 拆分为三类载货量（D16）——兼容旧数据：若无新字段则回读旧 maxCargo
  form.maxMaterialCargo = row.maxMaterialCargo ?? row.maxCargo ?? 0;
  form.maxPartCargo = row.maxPartCargo ?? 0;
  form.maxProductCargo = row.maxProductCargo ?? 0;
  form.price = row.price ?? 0;
  form.carbonEmission = row.carbonEmission ?? 0;
  form.pathTypeIds = (row.vehiclePathTypes || row.pathTypeIds || [])
    .map((v: any) =>
      typeof v === "number" || typeof v === "string"
        ? Number(v)
        : Number(v?.pathTypeId ?? v?.pathType?.id ?? v?.id ?? 0),
    )
    .filter((n: number) => Number.isFinite(n) && n > 0);
  dialogVisible.value = true;
}

async function handleDelete(row: VehicleItem) {
  let impact: DeleteImpact | null = null;
  try {
    impact = await vehiclesApi.impact(props.cid, row.id);
  } catch {
    impact = null;
  }
  try {
    await confirmDeleteWithImpact(row.name ?? `载具#${row.id}`, impact);
  } catch {
    return; // 用户取消
  }
  try {
    await vehiclesApi.remove(props.cid, row.id);
    ElMessage.success("载具已删除");
    loadData();
  } catch (e) {
    ElMessage.error(errorMessage(e, "操作失败"));
  }
}

async function handleSubmit() {
  const valid = await formRef.value
    ?.validate()
    .then(() => true)
    .catch(() => false);
  if (!valid) return;
  submitting.value = true;
  const body = {
    name: form.name,
    fuelId: form.fuelId,
    fuelConsumptionPerKm: form.fuelConsumptionPerKm,
    // ★ 原 maxCargo 拆分为三类载货量（D16）
    maxMaterialCargo: form.maxMaterialCargo,
    maxPartCargo: form.maxPartCargo,
    maxProductCargo: form.maxProductCargo,
    price: form.price,
    carbonEmission: form.carbonEmission,
    // 可通行路径类型：relations.pathTypes 整体替换（[{ pathTypeId }]）
    relations: {
      pathTypes: (form.pathTypeIds || []).map((id: number) => ({ pathTypeId: id })),
    },
  };
  try {
    if (isEdit.value && editingId.value) {
      await vehiclesApi.update(props.cid, editingId.value, body);
    } else {
      await vehiclesApi.create(props.cid, body);
    }
    ElMessage.success(isEdit.value ? "载具已更新" : "载具已创建");
    dialogVisible.value = false;
    loadData();
  } catch (e) {
    ElMessage.error(errorMessage(e, "操作失败"));
  } finally {
    submitting.value = false;
  }
}

function resetForm() {
  formRef.value?.resetFields();
  form.pathTypeIds = [];
}
</script>

<style scoped>
/* ------------------------------------------------------------------
   数据管理统一骨架（9 个管理器共用同一约定）：
   工具条（标题 + 搜索 + 新建）→ 提示 / 表格（或移动端卡片）；间距统一 16px
   ------------------------------------------------------------------ */
.vehicles-manager {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.vm-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 0;
}
.vm-title {
  margin: 0;
}
.vm-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
  flex-shrink: 0;
}
/* 关系列为空时的占位「-」：统一弱化色（不再写死 #c0c4cc） */
.cell-empty {
  color: var(--color-text-tertiary);
}
</style>
