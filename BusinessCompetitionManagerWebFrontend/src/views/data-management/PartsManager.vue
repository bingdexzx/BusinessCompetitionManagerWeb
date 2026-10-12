<template>
  <div class="parts-manager">
    <div class="pm-toolbar">
      <h2 class="pm-title">{{ canManage ? "零件管理" : "零件" }}</h2>
      <div class="pm-actions">
        <SearchToggle v-model="searchText" placeholder="搜索零件" />
        <el-button v-if="canManage" type="primary" @click="openCreate">+ 新建</el-button>
      </div>
    </div>

    <div v-if="!cid" class="no-comp-warning">
      请先在「比赛管理」中选择一个比赛
    </div>

    <el-table v-if="!isPhone" v-loading="loading" :data="filteredData" border stripe style="width: 100%">
      <el-table-column prop="name" label="名称" min-width="160" />
      <el-table-column label="原料配比" min-width="200">
        <template #default="{ row }">
          <span v-if="!row._materials?.length && !row.partMaterials?.length" style="color: #c0c4cc"
            >-</span
          >
          <el-tag
            v-for="pm in row.partMaterials || row._materials || []"
            :key="pm.id || pm.materialId"
            size="small"
            style="margin: 2px"
          >
            {{ pm.material?.name || pm.materialName }}x{{ pm.ratio }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column v-if="canManage" label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="showDetail(row)">详情</el-button>
          <el-button v-if="canManage" size="small" @click="openEdit(row)">编辑</el-button>
          <el-button v-if="canManage" size="small" type="danger" @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <MobileCards
      v-else
      :data="filteredData"
      :columns="partColumns"
      :loading="loading"
      :row-key="(row: any) => row.id"
    >
      <template #materials="{ row }">
        <span v-if="!row._materials?.length && !row.partMaterials?.length" style="color: #c0c4cc"
          >-</span
        >
        <el-tag
          v-for="pm in row.partMaterials || row._materials || []"
          :key="pm.id || pm.materialId"
          size="small"
          style="margin: 2px"
        >
          {{ pm.material?.name || pm.materialName }}x{{ pm.ratio }}
        </el-tag>
      </template>
      <template #actions="{ row }">
        <el-button size="small" @click="showDetail(row)">详情</el-button>
        <el-button v-if="canManage" size="small" @click="openEdit(row)">编辑</el-button>
        <el-button v-if="canManage" size="small" type="danger" @click="handleDelete(row)">删除</el-button>
      </template>
    </MobileCards>

    <el-dialog append-to-body v-model="detailVisible" title="零件详情" width="560px">
      <el-descriptions v-if="detailData" :column="1" border>
        <el-descriptions-item label="名称">{{ detailData.name }}</el-descriptions-item>
        <el-descriptions-item label="原料配比">
          <span
            v-if="!detailData.partMaterials?.length && !detailData._materials?.length"
            style="color: #c0c4cc"
            >无</span
          >
          <el-tag
            v-for="pm in detailData.partMaterials || detailData._materials || []"
            :key="pm.id || pm.materialId"
            size="small"
            style="margin: 2px"
          >
            {{ pm.material?.name || pm.materialName }}x{{ pm.ratio }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ formatDateTime(detailData.createdAt) }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ formatDateTime(detailData.updatedAt) }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>

    <el-dialog
      append-to-body
      v-model="dialogVisible"
      :title="isEdit ? '编辑零件管理' : '新建零件管理'"
      width="640px"
      destroy-on-close
      @closed="resetForm"
    >
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="100px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入零件名称" />
        </el-form-item>

        <el-form-item label="原料配比" prop="partMaterials">
          <div class="sub-table-wrap">
            <div class="sub-table-header">
              <span class="sub-table-col" style="flex: 1">原料</span>
              <span class="sub-table-col" style="width: 140px">比率</span>
              <span class="sub-table-col" style="width: 60px">操作</span>
            </div>
            <div v-for="(item, idx) in form.partMaterials" :key="idx" class="sub-table-row">
              <el-select
                v-model="item.materialId"
                placeholder="选择原料"
                filterable
                style="flex: 1"
                size="default"
              >
                <el-option
                  v-for="m in materialOptions"
                  :key="m.value"
                  :label="m.label"
                  :value="m.value"
                />
              </el-select>
              <el-input-number
                v-model="item.ratio"
                :min="0"
                :precision="2"
                placeholder="比率"
                style="width: 130px"
                size="default"
              />
              <el-button
                type="danger"
                :icon="Delete"
                circle
                size="small"
                style="margin-left: 8px"
                @click="removeMaterial(idx)"
              />
            </div>
          </div>
          <el-button type="primary" plain size="small" style="margin-top: 8px" @click="addMaterial">
            添加原料
          </el-button>
        </el-form-item>

        <el-form-item label="科技需求">
          <el-select
            v-model="form.techRequirements"
            multiple
            filterable
            placeholder="选择科技节点"
            style="width: 100%"
          >
            <el-option v-for="t in techOptions" :key="t.value" :label="t.label" :value="t.value" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted } from "vue";
import { ElMessage } from "element-plus";
import type { FormInstance, FormRules } from "element-plus";
import { Delete } from "@element-plus/icons-vue";
import {
  materialsApi,
  partsApi,
  techNodesApi,
  type BasedataRow,
} from "@/api/basedataApi";
import { confirmDeleteWithImpact, type DeleteImpact } from "@/utils/deleteConfirm";
import { useAuthStore } from "@/stores/auth";
import { errorMessage } from "@/utils/errors";
import { formatDateTime } from "@/utils/format";
import MobileCards from "@/components/common/MobileCards.vue";
import SearchToggle from "@/components/common/SearchToggle.vue";
import { useBreakpoint } from "@/composables/useBreakpoint";

interface MaterialRow {
  materialId: number | null;
  ratio: number;
}

interface PartMaterialView {
  id?: number;
  materialId: number | null;
  ratio: number;
  material?: { id: number; name: string };
  materialName?: string;
}

interface PartItem {
  id: number;
  name: string;
  partMaterials?: PartMaterialView[];
  _materials?: PartMaterialView[];
  techRequirements?: { techNodeId: number }[];
  relations?: Record<string, any> | null;
  createdAt?: string;
  updatedAt?: string;
}

const props = defineProps<{ cid: string }>();
const authStore = useAuthStore();
const { isPhone } = useBreakpoint();
const data = ref<PartItem[]>([]);
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

const partColumns = [
  { prop: "name", label: "名称" },
  { label: "原料配比", slot: "materials" },
];
const dialogVisible = ref(false);
const isEdit = ref(false);
const editingId = ref<number | null>(null);
const submitting = ref(false);
const formRef = ref<FormInstance>();
const detailVisible = ref(false);
const detailData = ref<PartItem | null>(null);

const materialOptions = ref<{ label: string; value: number }[]>([]);
const techOptions = ref<{ label: string; value: number }[]>([]);

const form = reactive({
  name: "",
  partMaterials: [] as MaterialRow[],
  techRequirements: [] as number[],
});

const formRules: FormRules = {
  name: [{ required: true, message: "请输入零件名称", trigger: "blur" }],
  partMaterials: [
    {
      required: true,
      validator: (_rule: any, _value: any, callback: any) => {
        const has = form.partMaterials.some((pm) => pm.materialId && pm.ratio > 0);
        has ? callback() : callback(new Error("请至少添加一项原料配比（选择原料且比率>0）"));
      },
      trigger: "change",
    },
  ],
};

const filteredData = computed(() => {
  const list = Array.isArray(data.value) ? data.value : [];
  if (!searchText.value) return list;
  const q = searchText.value.toLowerCase();
  return list.filter((item) =>
    String(item?.name ?? "")
      .toLowerCase()
      .includes(q),
  );
});

onMounted(() => {
  loadData();
  loadMaterialOptions();
  loadTechOptions();
});

/**
 * 行内关联归一化：新契约 parts 行带 relations.materials / relations.techRequirements
 * （items 形如 [{ id, materialId, materialName, ratio }] / [{ id, techNodeId, techNodeName }]）；
 * 展示层沿用旧页面的 partMaterials / techRequirements 结构。
 */
function normalizePart(row: BasedataRow): PartItem {
  const rel = (row?.relations ?? {}) as Record<string, any>;
  const rawMaterials: any[] =
    rel.materials ?? (row as any)?.partMaterials ?? (row as any)?._materials ?? [];
  const partMaterials: PartMaterialView[] = (Array.isArray(rawMaterials) ? rawMaterials : []).map(
    (pm: any) => {
      const materialId =
        pm?.materialId ?? pm?.material?.id ?? (typeof pm === "number" ? pm : null);
      const name =
        pm?.materialName ?? pm?.material?.name ?? pm?.name ?? materialNameById(materialId);
      return {
        id: pm?.id,
        materialId: materialId ?? null,
        ratio: pm?.ratio ?? 0,
        material: { id: Number(materialId ?? 0), name },
        materialName: name,
      };
    },
  );
  const rawTech: any[] = rel.techRequirements ?? (row as any)?.techRequirements ?? [];
  const techRequirements = (Array.isArray(rawTech) ? rawTech : []).map((tr: any) => ({
    techNodeId: Number(
      typeof tr === "number" || typeof tr === "string"
        ? tr
        : (tr?.techNodeId ?? tr?.techNode?.id ?? tr?.id ?? 0),
    ),
  }));
  return { ...(row as any), partMaterials, techRequirements } as PartItem;
}

function materialNameById(id: number | null): string {
  if (!id) return "";
  const m = materialOptions.value.find((o) => o.value === Number(id));
  return m?.label ?? "";
}

/** 列表行可能不含 relations：编辑/详情前补拉单行（GET /{id} 保证含 relations），避免整体替换时丢关联 */
async function withRelations(row: PartItem): Promise<PartItem> {
  if (row.relations) return row;
  try {
    return normalizePart(await partsApi.get(props.cid, row.id));
  } catch {
    return row;
  }
}

async function loadData() {
  loading.value = true;
  try {
    if (!props.cid) {
      data.value = [];
      return;
    }
    const res = await partsApi.list(props.cid, { page: 1, pageSize: 100 });
    data.value = (res.items || []).map((r) => normalizePart(r));
  } catch (e) {
    data.value = [];
    ElMessage.error(errorMessage(e, "操作失败"));
  } finally {
    loading.value = false;
  }
}

async function loadMaterialOptions() {
  try {
    const res = await materialsApi.list(props.cid, { page: 1, pageSize: 200 });
    materialOptions.value = (res.items || []).map((m: any) => ({
      label: String(m.name ?? ""),
      value: Number(m.id),
    }));
  } catch {
    /* 加载选项失败不阻塞列表 */
  }
}

async function loadTechOptions() {
  try {
    const res = await techNodesApi.list(props.cid, { page: 1, pageSize: 200 });
    techOptions.value = (res.items || []).map((t: any) => ({
      label: String(t.name ?? ""),
      value: Number(t.id),
    }));
  } catch {
    /* 加载选项失败不阻塞列表 */
  }
}

function showDetail(row: PartItem) {
  detailData.value = row;
  detailVisible.value = true;
}

function openCreate() {
  if (!props.cid) {
    ElMessage.warning("请先在「比赛管理」中选择一个比赛");
    return;
  }
  isEdit.value = false;
  editingId.value = null;
  form.name = "";
  form.partMaterials = [];
  form.techRequirements = [];
  dialogVisible.value = true;
}

async function openEdit(row: PartItem) {
  const full = await withRelations(row);
  isEdit.value = true;
  editingId.value = full.id;
  form.name = full.name || "";
  form.partMaterials = (full.partMaterials || []).map((pm: any) => ({
    materialId: pm.materialId ?? pm.material?.id ?? null,
    ratio: pm.ratio ?? 0,
  }));
  form.techRequirements = (full.techRequirements || []).map(
    (tr: any) => tr.techNodeId ?? tr.id,
  );
  dialogVisible.value = true;
}

function addMaterial() {
  form.partMaterials.push({ materialId: null, ratio: 0 });
  formRef.value?.validateField("partMaterials");
}

function removeMaterial(idx: number) {
  form.partMaterials.splice(idx, 1);
  formRef.value?.validateField("partMaterials");
}

async function handleDelete(row: PartItem) {
  let impact: DeleteImpact | null = null;
  try {
    impact = await partsApi.impact(props.cid, row.id);
  } catch {
    // 取级联影响信息失败时不阻塞删除，按普通删除提示处理
  }
  try {
    await confirmDeleteWithImpact(row.name, impact, {
      baseMessage: "确定删除该零件吗？此操作不可恢复。删除后将一并清除其配比与科技需求关联。",
    });
  } catch {
    return; // 用户取消
  }
  try {
    await partsApi.remove(props.cid, row.id);
    ElMessage.success("已删除");
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
  // relations 同名数组整体替换（嵌套在 relations 下，与 GET 对称）
  const body = {
    name: form.name,
    relations: {
      materials: form.partMaterials.map((pm) => ({
        materialId: pm.materialId,
        ratio: pm.ratio,
      })),
      techRequirements: form.techRequirements.map((id) => ({ techNodeId: id })),
    },
  };
  try {
    if (isEdit.value && editingId.value) {
      await partsApi.update(props.cid, editingId.value, body);
    } else {
      await partsApi.create(props.cid, body);
    }
    ElMessage.success(isEdit.value ? "已更新" : "已创建");
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
  form.partMaterials = [];
  form.techRequirements = [];
}
</script>

<style scoped>
.parts-manager {
  padding: 0;
}
.pm-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.pm-title {
  font-size: 20px;
  font-weight: 500;
  color: #1f1f1f;
  margin: 0;
}
.pm-actions {
  display: flex;
  gap: 8px;
}
.sub-table-wrap {
  width: 100%;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  overflow: hidden;
}
.sub-table-header {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  background: #f5f7fa;
  font-size: 13px;
  color: #606266;
  font-weight: 500;
}
.sub-table-col {
  padding: 0 4px;
}
.sub-table-row {
  display: flex;
  align-items: center;
  padding: 8px 12px;
  border-top: 1px solid #ebeef5;
  gap: 8px;
}
.no-comp-warning {
  text-align: center;
  padding: 12px;
  margin-bottom: 12px;
  background: var(--color-warning-soft);
  border: 1px solid rgba(var(--color-warning-soft-rgb), 0.3);
  border-radius: 6px;
  color: #b45309;
  font-size: 13px;
}
</style>
