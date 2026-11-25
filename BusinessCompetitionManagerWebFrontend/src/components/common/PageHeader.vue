<script setup lang="ts">
/**
 * 页面头部（2026-11 统一骨架）：左侧 h1 标题 + 可选说明，右侧动作区。
 * 所有列表/详情页统一用它，不再各写 page-toolbar / page-head / mm-toolbar。
 */
withDefaults(
  defineProps<{
    title: string
    /** 标题下的一行说明（可选，例如「共 3 个账号 · 全量」） */
    hint?: string
  }>(),
  { hint: '' },
)
</script>

<template>
  <header class="page-header">
    <div class="page-header__main">
      <h1 class="page-title">{{ title }}</h1>
      <p v-if="hint" class="page-header__hint">{{ hint }}</p>
      <!-- 状态标签 / 徽标等（详情页把状态放在标题旁） -->
      <slot name="meta" />
    </div>
    <div v-if="$slots.actions" class="page-actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<style scoped lang="scss">
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.page-header__main {
  display: flex;
  align-items: baseline;
  gap: 10px;
  min-width: 0;
}

.page-header__hint {
  margin: 0;
  color: var(--color-text-tertiary);
  font-size: var(--font-xs);
}

/* 右侧动作区：global.scss 已把相邻按钮的 margin-left 归零，
   这里必须用 gap 提供间距，否则按钮会贴在一起。 */
.page-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
  flex-shrink: 0;
}
</style>
