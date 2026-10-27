<template>
  <div class="fuel-manager">
    <div class="pm-toolbar">
      <h2 class="pm-title">{{ canManage ? "燃料管理" : "燃料" }}</h2>
      <div class="pm-actions">
        <SearchToggle v-model="searchText" placeholder="搜索燃料" />
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
      <el-table-column prop="pricePerLiter" label="每升价格" min-width="120" align="right">
        <template #default="{ row }">
          <span class="value-num">{{ row.pricePerLiter }}</span>
        </template>
      </el-table-column>
      <el-table-column v-if="canManage" label="操作" width="200" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="showDetail(row)">详情</el-button>
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" plain @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty
          v-if="!loading"
          :image-size="72"
          :description="searchText ? '没有匹配的记录' : '暂无燃料数据'"
        />
      </template>
    </el-table>

    <MobileCards
      v-else
      :data="filteredData"
      :columns="fuelColumns"
      :loading="loading"
      :row-key="(row: any) => row.id"
      :empty-text="searchText ? '没有匹配的记录' : '暂无燃料数据'"
      class="anim-fade-in-up"
    >
      <template #actions="{ row }">
        <el-button size="small" @click="showDetail(row)">详情</el-button>
        <el-button v-if="canManage" size="small" @click="openEdit(row)">编辑</el-button>
        <el-button v-if="canManage" size="small" type="danger" plain @click="handleDelete(row)"
          >删除</el-button
        >
      </template>
    </MobileCards>

    <el-dialog append-to-body v-model="detailVisible" title="燃料详情" width="480px">
      <el-descriptions v-if="detailData" :column="1" border>
        <el-descriptions-item label="名称">{{ detailData.name }}</el-descriptions-item>
        <el-descriptions-item label="每升价格">
          <span class="value-num">{{ detailData.pricePerLiter }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ formatDateTime(detailData.createdAt) }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ formatDateTime(detailData.updatedAt) }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>

    <el-dialog
      append-to-body
      v-model="dialogVisible"
      :title="isEdit ? '编辑燃料管理' : '新建燃料管理'"
      width="560px"
      destroy-on-close
      @closed="resetForm"
    >
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="120px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入燃料名称" />
        </el-form-item>
        <el-form-item label="每升价格" prop="pricePerLiter">
          <BigNumberInput v-model="form.pricePerLiter" :min="0" style="width: 100%" />
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
import { fuelsApi } from "@/api/basedataApi";
import { confirmDeleteWithImpact, type DeleteImpact } from "@/utils/deleteConfirm";
import { useAuthStore } from "@/stores/auth";
import { errorMessage } from "@/utils/errors";
import { formatDateTime } from "@/utils/format";
import MobileCards from "@/components/common/MobileCards.vue";
import SearchToggle from "@/components/common/SearchToggle.vue";
import BigNumberInput from "@/components/common/BigNumberInput.vue";
import { useBreakpoint } from "@/composables/useBreakpoint";
import { useResourceRefresh } from "@/composables/useNotifications";

interface FuelItem {
  id: number;
  name: string;
  pricePerLiter?: number;
  createdAt?: string;
  updatedAt?: string;
}

const props = defineProps<{ cid: string }>();
const authStore = useAuthStore();
const { isPhone } = useBreakpoint();
const data = ref<FuelItem[]>([]);
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

const fuelColumns = [
  { prop: "name", label: "名称" },
  { prop: "pricePerLiter", label: "每升价格" },
];
const dialogVisible = ref(false);
const isEdit = ref(false);
const editingId = ref<number | null>(null);
const submitting = ref(false);
const formRef = ref<FormInstance>();
const detailVisible = ref(false);
const detailData = ref<FuelItem | null>(null);

const form = reactive<{ name: string; pricePerLiter: number | string }>({
  name: "",
  pricePerLiter: 0,
});

const formRules: FormRules = {
  name: [{ required: true, message: "请输入燃料名称", trigger: "blur" }],
  pricePerLiter: [{ required: true, message: "请输入每升价格", trigger: "blur" }],
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

onMounted(loadData);

// 资源变更实时刷新：basedata 变更时自动重拉当前列表（保留搜索/选中状态）
useResourceRefresh(["basedata"], loadData);

async function loadData() {
  loading.value = true;
  try {
    if (!props.cid) {
      data.value = [];
      return;
    }
    const res = await fuelsApi.list(props.cid, { page: 1, pageSize: 100 });
    data.value = (res.items || []) as unknown as FuelItem[];
  } catch (e) {
    data.value = [];
    ElMessage.error(errorMessage(e, "操作失败"));
  } finally {
    loading.value = false;
  }
}

function showDetail(row: FuelItem) {
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
  form.pricePerLiter = 0;
  dialogVisible.value = true;
}

function openEdit(row: FuelItem) {
  isEdit.value = true;
  editingId.value = row.id;
  form.name = row.name || "";
  form.pricePerLiter = row.pricePerLiter ?? 0;
  dialogVisible.value = true;
}

async function handleDelete(row: FuelItem) {
  let impact: DeleteImpact | null = null;
  try {
    impact = await fuelsApi.impact(props.cid, row.id);
  } catch {
    // 取级联影响信息失败时不阻塞删除
  }
  try {
    await confirmDeleteWithImpact(row.name, impact, {
      baseMessage: "确定删除该燃料吗？此操作不可恢复。",
    });
  } catch {
    return; // 用户取消
  }
  try {
    await fuelsApi.remove(props.cid, row.id);
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
  const body = {
    name: form.name,
    pricePerLiter: form.pricePerLiter,
  };
  try {
    if (isEdit.value && editingId.value) {
      await fuelsApi.update(props.cid, editingId.value, body);
    } else {
      await fuelsApi.create(props.cid, body);
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
  form.name = "";
  form.pricePerLiter = 0;
}
</script>

<style scoped>
/* ------------------------------------------------------------------
   数据管理统一骨架（9 个管理器共用同一约定）：
   工具条（标题 + 搜索 + 新建）→ 提示 / 表格（或移动端卡片）；间距统一 16px
   ------------------------------------------------------------------ */
.fuel-manager {
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
