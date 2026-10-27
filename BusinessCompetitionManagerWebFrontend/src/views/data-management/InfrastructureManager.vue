<template>
  <div class="infra-manager">
    <div class="pm-toolbar">
      <h2 class="pm-title">{{ canManage ? "基建管理" : "基建" }}</h2>
      <div class="pm-actions">
        <SearchToggle v-model="searchText" placeholder="搜索基建" />
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
      <el-table-column
        v-for="f in fields"
        :key="f.prop"
        :prop="f.prop"
        :label="f.label"
        align="right"
        min-width="110"
      >
        <template #default="{ row }">
          <span class="value-num">{{ row[f.prop] }}</span>
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
          :description="searchText ? '没有匹配的记录' : '暂无基建数据'"
        />
      </template>
    </el-table>

    <MobileCards
      v-else
      :data="filteredData"
      :columns="infraColumns"
      :loading="loading"
      :row-key="(row: any) => row.id"
      :empty-text="searchText ? '没有匹配的记录' : '暂无基建数据'"
      class="anim-fade-in-up"
    >
      <template #actions="{ row }">
        <template v-if="canManage">
          <el-button size="small" @click="showDetail(row)">详情</el-button>
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" plain @click="handleDelete(row)">删除</el-button>
        </template>
      </template>
    </MobileCards>

    <el-dialog append-to-body v-model="detailVisible" title="基建详情" width="560px">
      <el-descriptions v-if="detailData" :column="1" border>
        <el-descriptions-item label="名称">{{ detailData.name }}</el-descriptions-item>
        <el-descriptions-item v-for="f in fields" :key="f.prop" :label="f.label">
          <span class="value-num">{{ (detailData as any)[f.prop] }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ formatDateTime(detailData.createdAt) }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ formatDateTime(detailData.updatedAt) }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>

    <el-dialog
      append-to-body
      v-model="dialogVisible"
      :title="isEdit ? '编辑基建管理' : '新建基建管理'"
      width="640px"
      destroy-on-close
      @closed="resetForm"
    >
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="140px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入基建名称" />
        </el-form-item>
        <el-form-item v-for="f in fields" :key="f.prop" :label="f.label" :prop="f.prop">
          <BigNumberInput v-model="(form as any)[f.prop]" :min="0" style="width: 100%" />
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
import { infrastructuresApi } from "@/api/basedataApi";
import { confirmDeleteWithImpact, type DeleteImpact } from "@/utils/deleteConfirm";
import { useAuthStore } from "@/stores/auth";
import { errorMessage } from "@/utils/errors";
import { formatDateTime } from "@/utils/format";
import MobileCards from "@/components/common/MobileCards.vue";
import SearchToggle from "@/components/common/SearchToggle.vue";
import BigNumberInput from "@/components/common/BigNumberInput.vue";
import { useBreakpoint } from "@/composables/useBreakpoint";
import { useResourceRefresh } from "@/composables/useNotifications";

interface InfraItem {
  id: number;
  name: string;
  footprint?: number;
  employmentRateBonus?: number;
  populationBonus?: number;
  highQualityPopulationBonus?: number;
  price?: number;
  happinessIndexBonus?: number;
  perCapitaIncomeBonus?: number;
  carbonReductionBonus?: number;
  activationPrice?: number;
  createdAt?: string;
  updatedAt?: string;
}

const FIELD_DEFS = [
  { prop: "footprint", label: "占地面积" },
  { prop: "employmentRateBonus", label: "就业率加成" },
  { prop: "populationBonus", label: "人口加成" },
  { prop: "highQualityPopulationBonus", label: "高素质人口加成" },
  { prop: "price", label: "价格" },
  { prop: "happinessIndexBonus", label: "幸福度加成" },
  { prop: "perCapitaIncomeBonus", label: "人均收益加成" },
  { prop: "carbonReductionBonus", label: "减碳排放加成" },
  { prop: "activationPrice", label: "启用价格" },
];
const fields = FIELD_DEFS;
const infraColumns = [{ prop: "name", label: "名称" }, ...fields];

const props = defineProps<{ cid: string }>();
const authStore = useAuthStore();
const { isPhone } = useBreakpoint();
const data = ref<InfraItem[]>([]);
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

const dialogVisible = ref(false);
const isEdit = ref(false);
const editingId = ref<number | null>(null);
const submitting = ref(false);
const formRef = ref<FormInstance>();
const detailVisible = ref(false);
const detailData = ref<InfraItem | null>(null);

const form = reactive<Record<string, any>>({
  name: "",
  footprint: 0,
  employmentRateBonus: 0,
  populationBonus: 0,
  highQualityPopulationBonus: 0,
  price: 0,
  happinessIndexBonus: 0,
  perCapitaIncomeBonus: 0,
  carbonReductionBonus: 0,
  activationPrice: 0,
});

const formRules: FormRules = {
  name: [{ required: true, message: "请输入基建名称", trigger: "blur" }],
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
    const res = await infrastructuresApi.list(props.cid, { page: 1, pageSize: 100 });
    data.value = (res.items || []) as unknown as InfraItem[];
  } catch (e) {
    data.value = [];
    ElMessage.error(errorMessage(e, "操作失败"));
  } finally {
    loading.value = false;
  }
}

function showDetail(row: InfraItem) {
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
  for (const key of Object.keys(form)) form[key] = key === "name" ? "" : 0;
  dialogVisible.value = true;
}

function openEdit(row: InfraItem) {
  isEdit.value = true;
  editingId.value = row.id;
  form.name = row.name || "";
  for (const f of fields) form[f.prop] = (row as any)[f.prop] ?? 0;
  dialogVisible.value = true;
}

async function handleDelete(row: InfraItem) {
  let impact: DeleteImpact | null = null;
  try {
    impact = await infrastructuresApi.impact(props.cid, row.id);
  } catch {
    // 取级联影响信息失败时不阻塞删除
  }
  try {
    await confirmDeleteWithImpact(row.name, impact, {
      baseMessage: "确定删除该基建吗？此操作不可恢复。",
    });
  } catch {
    return; // 用户取消
  }
  try {
    await infrastructuresApi.remove(props.cid, row.id);
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
  const body: Record<string, any> = { name: form.name };
  for (const f of fields) body[f.prop] = form[f.prop];
  try {
    if (isEdit.value && editingId.value) {
      await infrastructuresApi.update(props.cid, editingId.value, body);
    } else {
      await infrastructuresApi.create(props.cid, body);
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
  for (const key of Object.keys(form)) form[key] = key === "name" ? "" : 0;
}
</script>

<style scoped>
/* ------------------------------------------------------------------
   数据管理统一骨架（9 个管理器共用同一约定）：
   工具条（标题 + 搜索 + 新建）→ 提示 / 表格（或移动端卡片）；间距统一 16px
   ------------------------------------------------------------------ */
.infra-manager {
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
