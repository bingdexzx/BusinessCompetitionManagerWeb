<template>
  <div class="tool-page page">
    <header class="tool-head">
      <PageHeader title="产品用量" />
    </header>
    <el-card shadow="never" class="tool-card">
      <el-form label-width="96px" :disabled="!cid">
        <el-form-item label="商品">
          <el-select
            v-model="pickedIds"
            multiple
            collapse-tags
            collapse-tags-tooltip
            filterable
            placeholder="选择一个或多个商品"
            style="width: 100%"
            :loading="loading"
          >
            <el-option v-for="p in products" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <el-table :data="rows" border stripe class="tool-table" size="small">
        <template #empty>
          <el-empty :description="emptyText" :image-size="72" />
        </template>
        <el-table-column label="商品" min-width="150">
          <template #default="{ row }">{{ productName(row.productId) }}</template>
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
        <el-table-column label="需要的零件" min-width="260">
          <template #default="{ row }">
            <span v-if="!relationsOf(row.productId).length" class="cell-empty">未配置配比</span>
            <span v-for="item in relationsOf(row.productId)" :key="item.partId" class="req-chip">
              {{ item.partName || `零件#${item.partId}` }}
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
      <div class="tool-subtitle">零件需求汇总</div>
      <el-table :data="summary" border size="small" stripe>
        <template #empty>
          <el-empty :description="summaryEmptyText" :image-size="72" />
        </template>
        <el-table-column prop="partName" label="零件" min-width="180" />
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
import { productsApi, type BasedataRow } from "@/api/basedataApi";
import { errorMessage } from "@/utils/errors";
import { formatNumber } from "./toolUtils";
const props = defineProps<{ cid: string }>();
interface ProductPartRelation {
  partId?: number;
  partName?: string;
  ratio?: number;
}
interface ProductRow {
  productId: number;
  quantity: number;
}
const products = ref<BasedataRow[]>([]);
const loading = ref(false);
const rows = ref<ProductRow[]>([]);
const relationsByProduct = ref<Record<number, ProductPartRelation[]>>({});
const pickedIds = computed<number[]>({
  get: () => rows.value.map((row) => row.productId),
  set: (ids) => {
    const next: ProductRow[] = [];
    for (const id of ids) {
      const existing = rows.value.find((row) => row.productId === id);
      next.push(existing ?? { productId: id, quantity: 1 });
    }
    rows.value = next;
    void ensureRelations(ids);
  },
});
function productName(id: number): string {
  return String(products.value.find((p) => p.id === id)?.name ?? `商品#${id}`);
}
function relationsOf(id: number): ProductPartRelation[] {
  return relationsByProduct.value[id] ?? [];
}
function requiredOf(item: ProductPartRelation, quantity: number): number {
  return (Number(item.ratio) || 0) * (quantity || 0);
}
const summary = computed(() => {
  const totals = new Map<string, number>();
  for (const row of rows.value) {
    for (const item of relationsOf(row.productId)) {
      const key = item.partName || `零件#${item.partId}`;
      totals.set(key, (totals.get(key) ?? 0) + requiredOf(item, row.quantity));
    }
  }
  return [...totals.entries()].map(([partName, required]) => ({ partName, required }));
});
const emptyText = computed(() => {
  if (!props.cid) return "请先在「比赛列表」中选择一个比赛";
  return "暂无记录";
});
const summaryEmptyText = computed(() =>
  rows.value.length ? "所选商品还没有零件配比（在「数据管理 → 产品」里配置）" : "还没有选商品",
);
function removeRow(index: number): void {
  rows.value = rows.value.filter((_, i) => i !== index);
}
async function ensureRelations(ids: number[]): Promise<void> {
  if (!props.cid) return;
  const missing = ids.filter((id) => !relationsByProduct.value[id]);
  if (!missing.length) return;
  try {
    const details = await Promise.all(missing.map((id) => productsApi.get(props.cid, id)));
    const next = { ...relationsByProduct.value };
    missing.forEach((id, i) => {
      next[id] = (details[i]?.relations?.parts ?? []) as ProductPartRelation[];
    });
    relationsByProduct.value = next;
  } catch (error) {
    ElMessage.error(errorMessage(error, "加载商品配比失败"));
  }
}
async function load() {
  if (!props.cid) return;
  loading.value = true;
  try {
    const res = await productsApi.list(props.cid, { page: 1, pageSize: 500 });
    products.value = res.items ?? [];
  } catch (error) {
    ElMessage.error(errorMessage(error, "加载商品失败"));
  } finally {
    loading.value = false;
  }
}
watch(
  () => rows.value.map((row) => row.productId),
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