<template>
  <div class="infra-manager page">
    <PageHeader :title="canManage ? '基建管理' : '基建'">
      <template #actions>
      <div class="dm-actions">
        <SearchToggle v-model="searchText" placeholder="搜索基建" />
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
          <el-button size="small" @click="showDetail(row)" link type="primary">详情</el-button>
          <el-button size="small" @click="openEdit(row)" link type="primary">编辑</el-button>
          <el-button size="small" type="danger" @click="handleDelete(row)" link>删除</el-button>
        </template>
      </el-table-column>
      <template #empty>
        <el-empty
          v-if="!loading"
          :image-size="72"
          :description="searchText ? '暂无匹配记录' : '暂无基建数据'"
        />
      </template>
    </el-table>


    <MobileCards
      v-else
      :data="pagedRows"
      :columns="infraColumns"
      :loading="loading"
      :row-key="(row: any) => row.id"
      :empty-text="searchText ? '暂无匹配记录' : '暂无基建数据'"
      class="anim-fade-in-up"
    >
      <template #actions="{ row }">
        <template v-if="canManage">
          <el-button size="small" @click="showDetail(row)">详情</el-button>
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" @click="handleDelete(row)" link>删除</el-button>
        </template>
      </template>
    </MobileCards>
    <TablePager v-model:page="page" v-model:page-size="pageSize" :total="totalRows" />

    <el-drawer direction="rtl" append-to-body v-model="detailVisible" title="基建详情" size="480px">
      <el-descriptions v-if="detailData" :column="1" border>
        <el-descriptions-item label="名称">{{ detailData.name }}</el-descriptions-item>
        <el-descriptions-item v-for="f in fields" :key="f.prop" :label="f.label">
          <span class="value-num">{{ (detailData as any)[f.prop] }}</span>
        </el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ formatDateTime(detailData.createdAt) }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ formatDateTime(detailData.updatedAt) }}</el-descriptions-item>
      </el-descriptions>
    </el-drawer>

    <el-dialog
      append-to-body
      v-model="dialogVisible"
      :title="isEdit ? '编辑基建管理' : '新建基建管理'"
      width="720px"
      destroy-on-close
      @closed="resetForm"
    >
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="96px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="form.name" placeholder="请输入基建名称" />
        </el-form-item>
        <el-form-item v-for="f in fields" :key="f.prop" :label="f.label" :prop="f.prop">
          <BigNumberInput v-model="(form as any)[f.prop]" :min="0" style="width: 100%" />
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
/* eslint-disable @typescript-eslint/no-explicit-any -- 基础数据行字段随表/插件动态变化，逐字段建模收益低 */
import { ref, reactive, computed, onMounted } from "vue";
import TableSkeleton from '@/components/common/TableSkeleton.vue'
import PageHeader from '@/components/common/PageHeader.vue'
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
/** 首屏骨架 → 之后刷新用 v-loading */
const hasLoaded = ref(false);
const searchText = ref("");

/** 系统超级管理员或本比赛超级管理员：可新建/编辑/删除（其余只读） */
const canManage = computed(() => authStore.isSuperuser);

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
  hasLoaded.value = true;
  }
}

function showDetail(row: InfraItem) {
  detailData.value = row;
  detailVisible.value = true;
}

function openCreate() {
  if (!props.cid) {
    ElMessage.warning("请先在「比赛列表」中选择一个比赛");
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
      baseMessage: "确定删除该基建？此操作不可恢复。",
    });
  } catch {
    return; // 用户取消
  }
  try {
    await infrastructuresApi.remove(props.cid, row.id);
    ElMessage.success("基建已删除");
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
    ElMessage.success(isEdit.value ? "基建已更新" : "基建已创建");
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
  margin: 0;
}
.pm-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
  flex-shrink: 0;
}
</style>
