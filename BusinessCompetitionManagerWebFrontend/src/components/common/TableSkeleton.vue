<script setup lang="ts">
/**
 * 列表首屏骨架（2026-11 统一）：首屏加载显示骨架，二次刷新用 v-loading。
 * 用法：<TableSkeleton v-if="loading && !hasLoaded" :rows="6" />
 */
withDefaults(
  defineProps<{
    /** 骨架行数，默认 6 */
    rows?: number
    /** 列数，默认 5 */
    columns?: number
  }>(),
  { rows: 6, columns: 5 },
)
</script>

<template>
  <div class="table-skeleton" aria-busy="true" aria-label="加载中">
    <div v-for="row in rows" :key="row" class="table-skeleton__row">
      <div
        v-for="col in columns"
        :key="col"
        class="skeleton table-skeleton__cell"
        :class="{ 'table-skeleton__cell--wide': col === 1 }"
      />
    </div>
  </div>
</template>

<style scoped lang="scss">
.table-skeleton {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 4px 0;
}

.table-skeleton__row {
  display: flex;
  gap: 12px;
}

.table-skeleton__cell {
  height: 14px;
  flex: 1;
}

.table-skeleton__cell--wide {
  flex: 2;
}
</style>
