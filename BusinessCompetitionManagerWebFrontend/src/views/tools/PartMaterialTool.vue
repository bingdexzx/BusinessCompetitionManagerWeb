<template>
  <div class="tool-page page">
    <header class="tool-head">
      <PageHeader title="零件用量" />
    </header>
    <el-card shadow="never" class="tool-card">
      <el-form label-width="96px" :disabled="!cid">
        <el-form-item label="零件">
          <el-select
            v-model="pickedIds"
            multiple
            collapse-tags
            collapse-tags-tooltip
            filterable
            placeholder="选择一个或多个零件"
            style="width: 100%"
            :loading="loading"
          >
            <el-option v-for="p in parts" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <el-table :data="rows" border stripe class="tool-table" size="small">
        <template #empty>
          <el-empty :description="emptyText" :image-size="72" />
        </template>
        <el-table-column label="零件" min-width="150">
          <template #default="{ row }">{{ partName(row.partId) }}</template>
        </el-table-column>
        <el-table-column label="数量" align="right" min-width="130">
          <template #default="{ row }">
            <el-input-number
              v-model="row.quantity"
              :min="0"
              :step="1"
              :precision="0"
              size="small"
              controls-position="right"
              style="width: 110px"
            />
          </template>
        </el-table-column>
        <el-table-column label="需要的原料" min-width="260">
          <template #default="{ row }">
            <span v-if="!relationsOf(row.partId).length" class="cell-empty">
              未配置配比
            </span>
            <span v-for="item in relationsOf(row.partId)" :key="item.materialId" class="req-chip">
              {{ item.materialName || `原料#${item.materialId}` }}
              <span class="value-num">{{ formatNumber(requiredOf(item, row.quantity)) }}</span>
            </span>
          </template>
        </el-table-column>
        <el-table-column label="操作" align="center" width="80">
          <template #default="{ $index }">
            <el-button link type="danger" size="small" @click="removeRow($index)">移除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
    <el-card shadow="never" class="tool-card">
      <div class="tool-subtitle">原料需求汇总</div>
      <el-table :data="summary" border size="small" stripe>
        <template #empty>
          <el-empty :description="summaryEmptyText" :image-size="72" />
        </template>
        <el-table-column prop="materialName" label="原料" min-width="180" />
        <el-table-column label="合计需求量" align="right" min-width="150">
          <template #default="{ row }">
            <span class="value-num">{{ formatNumber(row.required) }}</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
  </div>
</template>
<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import PageHeader from '@/components/common/PageHeader.vue';
import { ElMessage } from "element-plus";
import { partsApi, type BasedataRow } from "@/api/basedataApi";
import { errorMessage } from "@/utils/errors";
import { formatNumber } from "./toolUtils";
const props = defineProps<{ cid: string }>();
interface PartMaterialRelation {
  materialId?: number;
  materialName?: string;
  ratio?: number;
}
interface PartRow {
  partId: number;
  quantity: number;
}
const parts = ref<BasedataRow[]>([]);
const loading = ref(false);
const rows = ref<PartRow[]>([]);
const relationsByPart = ref<Record<number, PartMaterialRelation[]>>({});
const pickedIds = computed<number[]>({
  get: () => rows.value.map((row) => row.partId),
  set: (ids) => {
    const next: PartRow[] = [];
    for (const id of ids) {
      const existing = rows.value.find((row) => row.partId === id);
      next.push(existing ?? { partId: id, quantity: 1 });
    }
    rows.value = next;
    void ensureRelations(ids);
  },
});
function partName(id: number): string {
  return String(parts.value.find((p) => p.id === id)?.name ?? `零件#${id}`);
}
function relationsOf(id: number): PartMaterialRelation[] {
  return relationsByPart.value[id] ?? [];
}
function requiredOf(item: PartMaterialRelation, quantity: number): number {
  return (Number(item.ratio) || 0) * (quantity || 0);
}
const summary = computed(() => {
  const totals = new Map<string, number>();
  for (const row of rows.value) {
    for (const item of relationsOf(row.partId)) {
      const key = item.materialName || `原料#${item.materialId}`;
      totals.set(key, (totals.get(key) ?? 0) + requiredOf(item, row.quantity));
    }
  }
  return [...totals.entries()].map(([materialName, required]) => ({ materialName, required }));
});
const emptyText = computed(() => {
  if (!props.cid) return "请先在「比赛列表」中选择一个比赛";
  return "暂无记录";
});
const summaryEmptyText = computed(() =>
  rows.value.length ? "所选零件还没有配比原料（在「数据管理 → 零件」里配置）" : "还没有选零件",
);
function removeRow(index: number): void {
  rows.value = rows.value.filter((_, i) => i !== index);
}
async function ensureRelations(ids: number[]): Promise<void> {
  if (!props.cid) return;
  const missing = ids.filter((id) => !relationsByPart.value[id]);
  if (!missing.length) return;
  try {
    const details = await Promise.all(missing.map((id) => partsApi.get(props.cid, id)));
    const next = { ...relationsByPart.value };
    missing.forEach((id, i) => {
      next[id] = (details[i]?.relations?.materials ?? []) as PartMaterialRelation[];
    });
    relationsByPart.value = next;
  } catch (error) {
    ElMessage.error(errorMessage(error, "加载零件配比失败"));
  }
}
async function load() {
  if (!props.cid) return;
  loading.value = true;
  try {
    const res = await partsApi.list(props.cid, { page: 1, pageSize: 500 });
    parts.value = res.items ?? [];
  } catch (error) {
    ElMessage.error(errorMessage(error, "加载零件失败"));
  } finally {
    loading.value = false;
  }
}
watch(
  () => rows.value.map((row) => row.partId),
  (ids) => void ensureRelations(ids),
);
onMounted(load);
</script>
<style scoped>
.tool-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}.tool-card {
  border: 1px solid var(--color-border);
}
.tool-table {
  margin-top: 4px;
}
.tool-subtitle {
  margin-bottom: 12px;
  font-size: var(--font-sm);
  font-weight: 600;
}
.req-chip {
  display: inline-block;
  margin: 2px 10px 2px 0;
  padding: 0 8px;
  font-size: var(--font-xs);
  line-height: 22px;
  color: var(--color-text-secondary);
  background: var(--surface-sunken);
  border-radius: var(--radius-xs);
}</style>