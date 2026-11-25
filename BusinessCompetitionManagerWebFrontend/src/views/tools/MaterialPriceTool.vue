<template>
  <div class="tool-page page">
    <header class="tool-head">
      <PageHeader title="原料价格工具" />
    </header>

    <el-card shadow="never" class="tool-card">
      <el-form label-width="96px" :disabled="!cid">
        <el-form-item label="原料">
          <el-select
            v-model="pickedIds"
            multiple
            collapse-tags
            collapse-tags-tooltip
            filterable
            placeholder="选择一个或多个原料"
            style="width: 100%"
            :loading="loading"
          >
            <el-option v-for="m in materials" :key="m.id" :label="m.name" :value="m.id" />
          </el-select>
        </el-form-item>
      </el-form>

      <el-table :data="rows" border stripe class="tool-table" size="small">
        <template #empty>
          <el-empty :description="emptyText" :image-size="72" />
        </template>
        <el-table-column label="原料" min-width="130">
          <template #default="{ row }">{{ materialName(row.materialId) }}</template>
        </el-table-column>
        <el-table-column label="产地" min-width="170">
          <template #default="{ row }">
            <el-select v-model="row.originName" size="small" style="width: 100%" filterable>
              <el-option
                v-for="name in originsOf(row.materialId)"
                :key="name"
                :label="name"
                :value="name"
              />
            </el-select>
          </template>
        </el-table-column>
        <el-table-column label="单价" align="right" min-width="110">
          <template #default="{ row }">
            <span v-if="unitPrice(row) === 0" class="cell-empty">未填价</span>
            <span v-else class="value-num">{{ formatNumber(unitPrice(row)) }}</span>
          </template>
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
        <el-table-column label="小计" align="right" min-width="120">
          <template #default="{ row }">
            <span class="value-num">{{ formatNumber(rowTotal(row)) }}</span>
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
      <div class="tool-result">
        <div class="tool-result-row">
          <span class="tool-result-label">原料种类</span>
          <span class="value-num">{{ rows.length }}</span>
        </div>
        <div class="tool-result-row">
          <span class="tool-result-label">总数量</span>
          <span class="value-num">{{ formatNumber(totalQuantity) }}</span>
        </div>
        <div class="tool-result-row tool-result-total">
          <span class="tool-result-label">总价</span>
          <span class="value-num">{{ formatNumber(total) }}</span>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import PageHeader from '@/components/common/PageHeader.vue';
import { ElMessage } from "element-plus";
import { listMapNodes, materialsApi, type BasedataRow } from "@/api/basedataApi";
import { errorMessage } from "@/utils/errors";
import { formatNumber, parseJsonObject, parseOriginList } from "./toolUtils";

const props = defineProps<{ cid: string }>();

interface MaterialRow {
  materialId: number;
  originName: string;
  quantity: number;
}

const materials = ref<BasedataRow[]>([]);
const mapNodes = ref<BasedataRow[]>([]);
const loading = ref(false);
const rows = ref<MaterialRow[]>([]);

const nodeByName = computed(() => {
  const map = new Map<string, BasedataRow>();
  for (const node of mapNodes.value) {
    const name = String(node.name ?? "");
    if (name && !map.has(name)) map.set(name, node);
  }
  return map;
});

function materialById(id: number): BasedataRow | undefined {
  return materials.value.find((m) => m.id === id);
}

function materialName(id: number): string {
  return String(materialById(id)?.name ?? `原料#${id}`);
}

/** 某原料可选的产地（与地图城市节点对得上的才算） */
function originsOf(id: number): string[] {
  const list = parseOriginList(materialById(id)?.origin);
  const known = nodeByName.value;
  return list.filter((name) => known.has(name));
}

/** 多选框：按 id 维护已选行，新增的默认取第一个产地、数量 1 */
const pickedIds = computed<number[]>({
  get: () => rows.value.map((row) => row.materialId),
  set: (ids) => {
    const next: MaterialRow[] = [];
    for (const id of ids) {
      const existing = rows.value.find((row) => row.materialId === id);
      if (existing) {
        next.push(existing);
        continue;
      }
      next.push({ materialId: id, originName: originsOf(id)[0] ?? "", quantity: 1 });
    }
    rows.value = next;
  },
});

function removeRow(index: number): void {
  rows.value = rows.value.filter((_, i) => i !== index);
}

function nodeIdOf(originName: string): number | null {
  if (!originName) return null;
  const node = nodeByName.value.get(originName);
  return node ? Number(node.id) : null;
}

function unitPrice(row: MaterialRow): number {
  const nodeId = nodeIdOf(row.originName);
  if (nodeId === null) return 0;
  const prices = parseJsonObject(materialById(row.materialId)?.nodePrices);
  const value = Number(prices[String(nodeId)]);
  return Number.isFinite(value) ? value : 0;
}

function rowTotal(row: MaterialRow): number {
  return unitPrice(row) * (row.quantity || 0);
}

const total = computed(() => rows.value.reduce((sum, row) => sum + rowTotal(row), 0));
const totalQuantity = computed(() => rows.value.reduce((sum, row) => sum + (row.quantity || 0), 0));

const emptyText = computed(() => {
  if (!props.cid) return "请先在「比赛列表」中选择一个比赛";
  return "暂无记录";
});


async function load() {
  if (!props.cid) return;
  loading.value = true;
  try {
    const res = await materialsApi.list(props.cid, { page: 1, pageSize: 500 });
    materials.value = res.items ?? [];
    mapNodes.value = await listMapNodes(props.cid);
  } catch (error) {
    ElMessage.error(errorMessage(error, "加载原料失败"));
  } finally {
    loading.value = false;
  }
}

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
.tool-result {
  display: flex;
  flex-wrap: wrap;
  gap: 32px;
  align-items: baseline;
}
.tool-result-row {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.tool-result-label {
  font-size: var(--font-xs);
  color: var(--color-text-secondary);
}
.tool-result-total .value-num {
  font-size: var(--font-xl);
  font-weight: 700;
  color: var(--color-primary);
}</style>
