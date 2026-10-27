<template>
  <div class="warehouses-manager">
    <div class="pm-toolbar">
      <h2 class="pm-title">{{ canManage ? "仓库管理" : "仓库" }}</h2>
      <div class="pm-actions">
        <SearchToggle v-model="searchText" placeholder="搜索仓库" />
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
      <el-table-column prop="capacity" label="容量" align="right" min-width="120">
        <template #default="{ row }">
          <span class="value-num">{{ row.capacity }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="price" label="价格" align="right" min-width="120">
        <template #default="{ row }">
          <span class="value-num">{{ row.price }}</span>
        </template>
      </el-table-column>
      <el-table-column label="种类">
        <template #default="{ row }">
          <el-tag :type="typeTag(row.type)">{{ typeLabel(row.type) }}</el-tag>
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
          :description="searchText ? '没有匹配的记录' : '暂无仓库数据'"
        />
      </template>
    </el-table>

    <MobileCards
      v-else
      :data="filteredData"
      :columns="warehouseColumns"
      :loading="loading"
      :row-key="(row: any) => row.id"
      :empty-text="searchText ? '没有匹配的记录' : '暂无仓库数据'"
      class="anim-fade-in-up"
    >
      <template #type="{ row }">
        <el-tag :type="typeTag(row.type)">{{ typeLabel(row.type) }}</el-tag>
      </template>
      <template #actions="{ row }">
        <el-button size="small" @click="showDetail(row)">详情</el-button>
        <el-button v-if="canManage" size="small" @click="openEdit(row)">编辑</el-button>
        <el-button v-if="canManage" size="small" type="danger" plain @click="handleDelete(row)"
          >删除</el-button
        >
      </template>
    </MobileCards>

    <el-dialog append-to-body v-model="detailVisible" title="仓库详情" width="500px">
      <el-descriptions v-if="detailData" :column="1" border>
        <el-descriptions-item label="名称">{{ detailData.name }}</el-descriptions-item>
        <el-descriptions-item label="容量">
          <span class="value-num">{{ detailData.capacity }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="价格">
          <span class="value-num">{{ detailData.price }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="种类">
          <el-tag :type="typeTag(detailData.type)">{{ typeLabel(detailData.type) }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ formatDateTime(detailData.createdAt) }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ formatDateTime(detailData.updatedAt) }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>

    <el-dialog
      append-to-body
      v-model="dialogVisible"
      :title="isEdit ? '编辑仓库管理' : '新建仓库管理'"
      width="480px"
      destroy-on-close
      @closed="resetForm"
    >
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="80px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入仓库名称" />
        </el-form-item>
        <el-form-item label="容量" prop="capacity">
          <BigNumberInput
            v-model="form.capacity"
            :min="0"
            style="width: 100%"
            placeholder="仓库容量"
          />
        </el-form-item>
        <el-form-item label="价格" prop="price">
          <BigNumberInput
            v-model="form.price"
            :min="0"
            style="width: 100%"
            placeholder="仓库价格"
          />
        </el-form-item>
        <el-form-item label="种类" prop="type">
          <el-select v-model="form.type" placeholder="选择仓库种类" style="width: 100%">
            <el-option label="原料仓库" value="MATERIAL" />
            <el-option label="零件仓库" value="PART" />
            <el-option label="成品仓库" value="PRODUCT" />
            <el-option label="燃料仓库" value="FUEL" />
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
import { warehousesApi } from "@/api/basedataApi";
import { confirmDeleteWithImpact, type DeleteImpact } from "@/utils/deleteConfirm";
import { useAuthStore } from "@/stores/auth";
import { errorMessage } from "@/utils/errors";
import { formatDateTime } from "@/utils/format";
import MobileCards from "@/components/common/MobileCards.vue";
import SearchToggle from "@/components/common/SearchToggle.vue";
import BigNumberInput from "@/components/common/BigNumberInput.vue";
import { useBreakpoint } from "@/composables/useBreakpoint";
import { useResourceRefresh } from "@/composables/useNotifications";

interface Warehouse {
  id: number;
  name: string;
  capacity: number;
  price: number;
  type: string;
  createdAt: string;
  updatedAt: string;
}

const props = defineProps<{ cid: string }>();
const authStore = useAuthStore();
const { isPhone } = useBreakpoint();
const data = ref<Warehouse[]>([]);
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

const warehouseColumns = [
  { prop: "name", label: "名称" },
  { prop: "capacity", label: "容量" },
  { prop: "price", label: "价格" },
  { label: "种类", slot: "type" },
];

const filteredData = computed(() => {
  const list = Array.isArray(data.value) ? data.value : [];
  if (!searchText.value) return list;
  const q = searchText.value.toLowerCase();
  return list.filter((w) => String(w?.name ?? "").toLowerCase().includes(q));
});

const detailVisible = ref(false);
const detailData = ref<Warehouse | null>(null);
function showDetail(row: Warehouse) {
  detailData.value = row;
  detailVisible.value = true;
}

const dialogVisible = ref(false);
const isEdit = ref(false);
const editingId = ref(0);
const submitting = ref(false);
const formRef = ref<FormInstance>();

const form = reactive<{
  name: string;
  capacity: number | string;
  price: number | string;
  type: string;
}>({ name: "", capacity: 0, price: 0, type: "MATERIAL" });
const formRules: FormRules = {
  name: [{ required: true, message: "请输入仓库名称", trigger: "blur" }],
  capacity: [{ required: true, message: "请输入容量", trigger: "blur" }],
  price: [{ required: true, message: "请输入价格", trigger: "blur" }],
  type: [{ required: true, message: "请选择种类", trigger: "change" }],
};

onMounted(loadData);

// 资源变更实时刷新：basedata 变更时自动重拉当前列表（保留搜索/选中状态）
useResourceRefresh(["basedata"], loadData);

async function loadData() {
  loading.value = true;
  try {
    if (!props.cid) {
      data.value = [];
      loading.value = false;
      return;
    }
    const res = await warehousesApi.list(props.cid, { page: 1, pageSize: 100 });
    data.value = (res.items || []) as unknown as Warehouse[];
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
  form.capacity = 0;
  form.price = 0;
  form.type = "MATERIAL";
  dialogVisible.value = true;
}
function openEdit(row: Warehouse) {
  isEdit.value = true;
  editingId.value = row.id;
  form.name = row.name;
  form.capacity = row.capacity;
  form.price = row.price;
  form.type = row.type;
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
      await warehousesApi.update(props.cid, editingId.value, body);
      ElMessage.success("已更新");
    } else {
      await warehousesApi.create(props.cid, body);
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

async function handleDelete(row: Warehouse) {
  let impact: DeleteImpact | null = null;
  try {
    impact = await warehousesApi.impact(props.cid, row.id);
  } catch {
    impact = null;
  }
  try {
    await confirmDeleteWithImpact(row.name, impact);
  } catch {
    return; // 用户取消
  }
  try {
    await warehousesApi.remove(props.cid, row.id);
    ElMessage.success("已删除");
    loadData();
  } catch (e) {
    ElMessage.error(errorMessage(e, "操作失败"));
  }
}

function typeLabel(t: string) {
  const map: Record<string, string> = {
    MATERIAL: "原料仓库",
    PART: "零件仓库",
    PRODUCT: "成品仓库",
    FUEL: "燃料仓库",
  };
  return map[t] || t;
}
function typeTag(t: string): "" | "success" | "warning" | "danger" {
  const map: Record<string, "" | "success" | "warning" | "danger"> = {
    MATERIAL: "",
    PART: "success",
    PRODUCT: "warning",
    FUEL: "danger",
  };
  return map[t] ?? "";
}
</script>

<style scoped>
/* ------------------------------------------------------------------
   数据管理统一骨架（9 个管理器共用同一约定）：
   工具条（标题 + 搜索 + 新建）→ 提示 / 表格（或移动端卡片）；间距统一 16px
   ------------------------------------------------------------------ */
.warehouses-manager {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.pm-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 0;
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
</style>
