<template>
  <div class="table-pager">
    <el-pagination
      background
      layout="total, sizes, prev, pager, next, jumper"
      :total="total"
      :current-page="page"
      :page-size="pageSize"
      :page-sizes="pageSizes"
      @update:current-page="(value: number) => emit('update:page', value)"
      @update:page-size="(value: number) => emit('update:pageSize', value)"
    />
  </div>
</template>

<script setup lang="ts">
withDefaults(
  defineProps<{
    total: number
    page: number
    pageSize: number
    pageSizes?: number[]
  }>(),
  { pageSizes: () => [20, 50, 100] },
)
const emit = defineEmits<{
  (event: 'update:page', value: number): void
  (event: 'update:pageSize', value: number): void
}>()
</script>

<style scoped>
.table-pager {
  display: flex;
  justify-content: flex-end;
  padding: 12px 4px 0;
}
</style>
