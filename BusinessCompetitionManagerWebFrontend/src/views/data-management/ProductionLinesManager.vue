<template>
  <div class="production-lines-manager">
    <div class="pm-toolbar">
      <h2 class="pm-title">{{ canManage ? "生产线管理" : "生产线" }}</h2>
      <div class="pm-actions">
        <SearchToggle v-model="searchText" placeholder="搜索生产线" />
        <el-button v-if="canManage" type="primary" @click="openCreate">+ 新建</el-button>
      </div>
    </div>

    <div v-if="!cid" class="no-comp-warning">
      请先在「比赛管理」中选择一个比赛
    </div>

    <el-table v-if="!isPhone" v-loading="loading" :data="filteredData" border stripe style="width: 100%">
      <el-table-column prop="name" label="名称" />
      <el-table-column prop="price" label="价格" />
      <el-table-column prop="laborCount" label="劳动力" />
      <el-table-column prop="maxPerYear" label="年加工上限" />
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
      :columns="productionLineColumns"
      :loading="loading"
      :row-key="(row: any) => row.id"
    >
      <template #actions="{ row }">
        <el-button size="small" @click="showDetail(row)">详情</el-button>
        <el-button v-if="canManage" size="small" @click="openEdit(row)">编辑</el-button>
        <el-button v-if="canManage" size="small" type="danger" @click="handleDelete(row)">删除</el-button>
      </template>
    </MobileCards>

    <el-dialog append-to-body v-model="detailVisible" title="生产线详情" width="500px">
      <el-descriptions v-if="detailData" :column="1" border>
        <el-descriptions-item label="名称">{{ detailData.name }}</el-descriptions-item>
        <el-descriptions-item label="价格">{{ detailData.price }}</el-descriptions-item>
        <el-descriptions-item label="劳动力">{{ detailData.laborCount }}</el-descriptions-item>
        <el-descriptions-item label="年加工上限">{{ detailData.maxPerYear }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ formatDateTime(detailData.createdAt) }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ formatDateTime(detailData.updatedAt) }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>

    <el-dialog
      append-to-body
      v-model="dialogVisible"
      :title="isEdit ? '编辑' : '新建'"
      width="480px"
      destroy-on-close
      @closed="resetForm"
    >
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="110px">
        <el-form-item label="名称" prop="name"
          ><el-input v-model="form.name" placeholder="生产线名称"
        /></el-form-item>
        <el-form-item label="价格" prop="price">
          <BigNumberInput v-model="form.price" :min="0" style="width: 100%" />
        </el-form-item>
        <el-form-item label="劳动力数量" prop="laborCount">
          <el-input-number v-model="form.laborCount" :min="1" :step="1" style="width: 100%" />
        </el-form-item>
        <el-form-item label="年加工上限" prop="maxPerYear">
          <BigNumberInput v-model="form.maxPerYear" :min="0" style="width: 100%" />
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
import { productionLinesApi } from "@/api/basedataApi";
import { confirmDeleteWithImpact, type DeleteImpact } from "@/utils/deleteConfirm";
import { useAuthStore } from "@/stores/auth";
import { errorMessage } from "@/utils/errors";
import { formatDateTime } from "@/utils/format";
import MobileCards from "@/components/common/MobileCards.vue";
import SearchToggle from "@/components/common/SearchToggle.vue";
import BigNumberInput from "@/components/common/BigNumberInput.vue";
import { useBreakpoint } from "@/composables/useBreakpoint";

interface ProductionLineItem {
  id: number;
  name: string;
  price?: number | string;
  laborCount?: number;
  maxPerYear?: number | string;
  createdAt?: string;
  updatedAt?: string;
}

const props = defineProps<{ cid: string }>();
const authStore = useAuthStore();
const { isPhone } = useBreakpoint();
const data = ref<ProductionLineItem[]>([]);
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

const productionLineColumns = [
  { prop: "name", label: "名称" },
  { prop: "price", label: "价格" },
  { prop: "laborCount", label: "劳动力" },
  { prop: "maxPerYear", label: "年加工上限" },
];
const filteredData = computed(() => {
  const list = Array.isArray(data.value) ? data.value : [];
  if (!searchText.value) return list;
  const q = searchText.value.toLowerCase();
  return list.filter((p) => String(p?.name ?? "").toLowerCase().includes(q));
});

const detailVisible = ref(false),
  detailData = ref<ProductionLineItem | null>(null);
function showDetail(row: ProductionLineItem) {
  detailData.value = row;
  detailVisible.value = true;
}

const dialogVisible = ref(false),
  isEdit = ref(false),
  editingId = ref(0);
const submitting = ref(false),
  formRef = ref<FormInstance>();

const form = reactive<{
  name: string;
  price: number | string;
  laborCount: number;
  maxPerYear: number | string;
}>({ name: "", price: 0, laborCount: 1, maxPerYear: 0 });
const formRules: FormRules = {
  name: [{ required: true, message: "请输入名称", trigger: "blur" }],
  price: [{ required: true, message: "请输入价格", trigger: "blur" }],
  laborCount: [{ required: true, message: "请输入劳动力数量", trigger: "blur" }],
  maxPerYear: [{ required: true, message: "请输入年加工上限", trigger: "blur" }],
};

onMounted(loadData);

async function loadData() {
  loading.value = true;
  if (!props.cid) {
    data.value = [];
    loading.value = false;
    return;
  }
  try {
    const res = await productionLinesApi.list(props.cid, { page: 1, pageSize: 100 });
    data.value = (res.items || []) as unknown as ProductionLineItem[];
  } catch (e) {
    data.value = [];
    ElMessage.error(errorMessage(e, "操作失败"));
  } finally {
    loading.value = false;
  }
}
function openCreate() {
  if (!props.cid) {
    ElMessage.warning("请先在「比赛管理」中选择一个比赛");
    return;
  }
  isEdit.value = false;
  editingId.value = 0;
  form.name = "";
  form.price = 0;
  form.laborCount = 1;
  form.maxPerYear = 0;
  dialogVisible.value = true;
}
function openEdit(row: ProductionLineItem) {
  isEdit.value = true;
  editingId.value = row.id;
  form.name = row.name;
  form.price = row.price ?? 0;
  form.laborCount = row.laborCount ?? 1;
  form.maxPerYear = row.maxPerYear ?? 0;
  dialogVisible.value = true;
}
function resetForm() {
  formRef.value?.resetFields();
}

async function handleSubmit() {
  const valid = await formRef.value
    ?.validate()
    .then(() => true)
    .catch(() => false);
  if (!valid) return;
  submitting.value = true;
  try {
    const body = { ...form };
    if (isEdit.value) {
      await productionLinesApi.update(props.cid, editingId.value, body);
      ElMessage.success("已更新");
    } else {
      await productionLinesApi.create(props.cid, body);
      ElMessage.success("已创建");
    }
    dialogVisible.value = false;
    loadData();
  } catch (e) {
    ElMessage.error(errorMessage(e, "操作失败"));
  } finally {
    submitting.value = false;
  }
}
async function handleDelete(row: ProductionLineItem) {
  let impact: DeleteImpact | null = null;
  try {
    impact = await productionLinesApi.impact(props.cid, row.id);
  } catch {
    impact = null;
  }
  try {
    await confirmDeleteWithImpact(row.name, impact);
  } catch {
    return; // 用户取消
  }
  try {
    await productionLinesApi.remove(props.cid, row.id);
    ElMessage.success("已删除");
    loadData();
  } catch (e) {
    ElMessage.error(errorMessage(e, "操作失败"));
  }
}
</script>

<style scoped>
.production-lines-manager {
  padding: 0;
}
.pm-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
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
