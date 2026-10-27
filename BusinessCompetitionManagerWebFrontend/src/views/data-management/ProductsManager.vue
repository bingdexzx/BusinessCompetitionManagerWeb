<template>
  <div class="products-manager">
    <div class="prm-toolbar">
      <h2 class="prm-title">{{ canManage ? "产品管理" : "产品" }}</h2>
      <div class="prm-actions">
        <SearchToggle v-model="searchText" placeholder="搜索产品" />
        <el-button v-if="canManage" type="primary" @click="openCreate">+ 新建</el-button>
      </div>
    </div>

    <div v-if="!cid" class="notice notice--warning">
      请先在「比赛管理」中选择一个比赛
    </div>

    <el-table
      v-if="!isPhone"
      v-loading="loading"
      :data="filteredData"
      border
      stripe
      class="anim-fade-in-up"
      style="width: 100%"
    >
      <el-table-column prop="name" label="名称" min-width="160" />
      <el-table-column label="零件配比" min-width="200">
        <template #default="{ row }">
          <span v-if="!row._parts?.length && !row.productParts?.length" class="cell-empty">-</span>
          <el-tag
            v-for="pp in row.productParts || row._parts || []"
            :key="pp.id || pp.partId"
            size="small"
            style="margin: 2px"
          >
            {{ pp.part?.name || pp.partName }}x{{ pp.ratio }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column v-if="canManage" label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="showDetail(row)">详情</el-button>
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
          :description="searchText ? '没有匹配的记录' : '暂无产品数据'"
        />
      </template>
    </el-table>

    <MobileCards
      v-else
      :data="filteredData"
      :columns="productColumns"
      :loading="loading"
      :row-key="(row: any) => row.id"
      :empty-text="searchText ? '没有匹配的记录' : '暂无产品数据'"
      class="anim-fade-in-up"
    >
      <template #parts="{ row }">
        <span v-if="!row._parts?.length && !row.productParts?.length" class="cell-empty">-</span>
        <el-tag
          v-for="pp in row.productParts || row._parts || []"
          :key="pp.id || pp.partId"
          size="small"
          style="margin: 2px"
        >
          {{ pp.part?.name || pp.partName }}x{{ pp.ratio }}
        </el-tag>
      </template>
      <template #actions="{ row }">
        <el-button size="small" @click="showDetail(row)">详情</el-button>
        <el-button v-if="canManage" size="small" @click="openEdit(row)">编辑</el-button>
        <el-button v-if="canManage" size="small" type="danger" plain @click="handleDelete(row)"
          >删除</el-button
        >
      </template>
    </MobileCards>

    <el-dialog append-to-body v-model="detailVisible" title="产品详情" width="560px">
      <el-descriptions v-if="detailData" :column="1" border>
        <el-descriptions-item label="名称">{{ detailData.name }}</el-descriptions-item>
        <el-descriptions-item label="零件配比">
          <span
            v-if="!detailData.productParts?.length && !detailData._parts?.length"
            class="cell-empty"
            >无</span
          >
          <el-tag
            v-for="pp in detailData.productParts || detailData._parts || []"
            :key="pp.id || pp.partId"
            size="small"
            style="margin: 2px"
          >
            {{ pp.part?.name || pp.partName }}x{{ pp.ratio }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ formatDateTime(detailData.createdAt) }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ formatDateTime(detailData.updatedAt) }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>

    <el-dialog
      append-to-body
      v-model="dialogVisible"
      :title="isEdit ? '编辑产品管理' : '新建产品管理'"
      width="640px"
      destroy-on-close
      @closed="resetForm"
    >
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="100px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入产品名称" />
        </el-form-item>

        <el-form-item label="零件配比" prop="productParts">
          <div class="sub-table-wrap">
            <div class="sub-table-header">
              <span class="sub-table-col" style="flex: 1">零件</span>
              <span class="sub-table-col" style="width: 140px">比率</span>
              <span class="sub-table-col" style="width: 60px">操作</span>
            </div>
            <div v-for="(item, idx) in form.productParts" :key="idx" class="sub-table-row">
              <el-select
                v-model="item.partId"
                placeholder="选择零件"
                filterable
                style="flex: 1"
                size="default"
              >
                <el-option
                  v-for="p in partOptions"
                  :key="p.value"
                  :label="p.label"
                  :value="p.value"
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
                @click="removePart(idx)"
              />
            </div>
          </div>
          <el-button type="primary" plain size="small" style="margin-top: 8px" @click="addPart">
            添加零件
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
  partsApi,
  productsApi,
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
import { useResourceRefresh } from "@/composables/useNotifications";

interface PartRow {
  partId: number | null;
  ratio: number;
}

interface ProductPartView {
  id?: number;
  partId: number | null;
  ratio: number;
  part?: { id: number; name: string };
  partName?: string;
}

interface ProductItem {
  id: number;
  name: string;
  productParts?: ProductPartView[];
  _parts?: ProductPartView[];
  techRequirements?: { techNodeId: number }[];
  relations?: Record<string, any> | null;
  createdAt?: string;
  updatedAt?: string;
}

const props = defineProps<{ cid: string }>();
const authStore = useAuthStore();
const { isPhone } = useBreakpoint();
const data = ref<ProductItem[]>([]);
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

const productColumns = [
  { prop: "name", label: "名称" },
  { label: "零件配比", slot: "parts" },
];
const dialogVisible = ref(false);
const isEdit = ref(false);
const editingId = ref<number | null>(null);
const submitting = ref(false);
const formRef = ref<FormInstance>();
const detailVisible = ref(false);
const detailData = ref<ProductItem | null>(null);

const partOptions = ref<{ label: string; value: number }[]>([]);
const techOptions = ref<{ label: string; value: number }[]>([]);

const form = reactive({
  name: "",
  productParts: [] as PartRow[],
  techRequirements: [] as number[],
});

const formRules: FormRules = {
  name: [{ required: true, message: "请输入产品名称", trigger: "blur" }],
  productParts: [
    {
      required: true,
      validator: (_rule: any, _value: any, callback: any) => {
        const has = form.productParts.some((pp) => pp.partId && pp.ratio > 0);
        has ? callback() : callback(new Error("请至少添加一项零件配比（选择零件且比率>0）"));
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
  loadPartOptions();
  loadTechOptions();
});

// 资源变更实时刷新：basedata 变更时自动重拉当前列表（保留搜索/选中状态）
useResourceRefresh(["basedata"], loadData);

/**
 * 行内关联归一化：新契约 products 行带 relations.parts / relations.techRequirements
 * （items 形如 [{ id, partId, partName, ratio }] / [{ id, techNodeId, techNodeName }]）；
 * 展示层沿用旧页面的 productParts / techRequirements 结构。
 */
function normalizeProduct(row: BasedataRow): ProductItem {
  const rel = (row?.relations ?? {}) as Record<string, any>;
  const rawParts: any[] =
    rel.parts ?? (row as any)?.productParts ?? (row as any)?._parts ?? [];
  const productParts: ProductPartView[] = (Array.isArray(rawParts) ? rawParts : []).map(
    (pp: any) => {
      const partId = pp?.partId ?? pp?.part?.id ?? (typeof pp === "number" ? pp : null);
      const name = pp?.partName ?? pp?.part?.name ?? pp?.name ?? partNameById(partId);
      return {
        id: pp?.id,
        partId: partId ?? null,
        ratio: pp?.ratio ?? 0,
        part: { id: Number(partId ?? 0), name },
        partName: name,
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
  return { ...(row as any), productParts, techRequirements } as ProductItem;
}

function partNameById(id: number | null): string {
  if (!id) return "";
  const p = partOptions.value.find((o) => o.value === Number(id));
  return p?.label ?? "";
}

/** 列表行可能不含 relations：编辑前补拉单行（GET /{id} 保证含 relations），避免整体替换时丢关联 */
async function withRelations(row: ProductItem): Promise<ProductItem> {
  if (row.relations) return row;
  try {
    return normalizeProduct(await productsApi.get(props.cid, row.id));
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
    const res = await productsApi.list(props.cid, { page: 1, pageSize: 100 });
    data.value = (res.items || []).map((r) => normalizeProduct(r));
  } catch (e) {
    data.value = [];
    ElMessage.error(errorMessage(e, "操作失败"));
  } finally {
    loading.value = false;
  }
}

async function loadPartOptions() {
  try {
    const res = await partsApi.list(props.cid, { page: 1, pageSize: 200 });
    partOptions.value = (res.items || []).map((p: any) => ({
      label: String(p.name ?? ""),
      value: Number(p.id),
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

function showDetail(row: ProductItem) {
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
  form.productParts = [];
  form.techRequirements = [];
  dialogVisible.value = true;
}

async function openEdit(row: ProductItem) {
  const full = await withRelations(row);
  isEdit.value = true;
  editingId.value = full.id;
  form.name = full.name || "";
  form.productParts = (full.productParts || []).map((pp: any) => ({
    partId: pp.partId ?? pp.part?.id ?? null,
    ratio: pp.ratio ?? 0,
  }));
  form.techRequirements = (full.techRequirements || []).map(
    (tr: any) => tr.techNodeId ?? tr.id,
  );
  dialogVisible.value = true;
}

function addPart() {
  form.productParts.push({ partId: null, ratio: 0 });
  formRef.value?.validateField("productParts");
}

function removePart(idx: number) {
  form.productParts.splice(idx, 1);
  formRef.value?.validateField("productParts");
}

async function handleDelete(row: ProductItem) {
  let impact: DeleteImpact | null = null;
  try {
    impact = await productsApi.impact(props.cid, row.id);
  } catch {
    // 取级联影响信息失败时不阻塞删除，按普通删除提示处理
  }
  try {
    await confirmDeleteWithImpact(row.name, impact, {
      baseMessage: "确定删除该产品吗？此操作不可恢复。删除后将一并清除其配比与科技需求关联。",
    });
  } catch {
    return; // 用户取消
  }
  try {
    await productsApi.remove(props.cid, row.id);
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
      parts: form.productParts.map((pp) => ({ partId: pp.partId, ratio: pp.ratio })),
      techRequirements: form.techRequirements.map((id) => ({ techNodeId: id })),
    },
  };
  try {
    if (isEdit.value && editingId.value) {
      await productsApi.update(props.cid, editingId.value, body);
    } else {
      await productsApi.create(props.cid, body);
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
  form.productParts = [];
  form.techRequirements = [];
}
</script>

<style scoped>
/* ------------------------------------------------------------------
   数据管理统一骨架（9 个管理器共用同一约定）：
   工具条（标题 + 搜索 + 新建）→ 提示 / 表格（或移动端卡片）；间距统一 16px
   ------------------------------------------------------------------ */
.products-manager {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.prm-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 0;
}
.prm-title {
  font-size: 20px;
  font-weight: 500;
  color: #1f1f1f;
  margin: 0;
}
.prm-actions {
  display: flex;
  gap: 8px;
}
/* 关系列为空时的占位「-」/「无」：统一弱化色（不再写死 #c0c4cc） */
.cell-empty {
  color: var(--color-text-tertiary);
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
</style>
