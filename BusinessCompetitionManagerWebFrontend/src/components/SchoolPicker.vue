<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { getSchools } from '@/api'
import type { School } from '@/api/types'

const props = defineProps<{
  modelValue: number | null
  /** 选中学校的展示名（回显用） */
  initialName?: string | null
  placeholder?: string
}>()

const emit = defineEmits<{
  'update:modelValue': [value: number | null]
}>()

const query = ref(props.initialName ?? '')
const options = ref<School[]>([])
const open = ref(false)
const loading = ref(false)
let timer: ReturnType<typeof setTimeout> | null = null

watch(
  () => props.initialName,
  (name) => {
    if (props.modelValue !== null) query.value = name ?? ''
  },
)

async function search(): Promise<void> {
  loading.value = true
  try {
    options.value = await getSchools(query.value.trim() || undefined)
    open.value = true
  } catch {
    options.value = []
    open.value = true
  } finally {
    loading.value = false
  }
}

function onInput(event: Event): void {
  query.value = (event.target as HTMLInputElement).value
  // 输入即清空已选
  if (props.modelValue !== null) emit('update:modelValue', null)
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => void search(), 300)
}

function onFocus(): void {
  void search()
}

function pick(school: School): void {
  query.value = school.name
  open.value = false
  emit('update:modelValue', school.id)
}

function clear(): void {
  query.value = ''
  emit('update:modelValue', null)
  void search()
}

function onBlur(): void {
  // 延迟关闭，保证 click 先触发
  setTimeout(() => {
    open.value = false
  }, 150)
}

onBeforeUnmount(() => {
  if (timer) clearTimeout(timer)
})
</script>

<template>
  <div class="school-picker">
    <input
      class="input"
      type="text"
      :value="query"
      :placeholder="placeholder ?? '搜索学校名称…'"
      autocomplete="off"
      @input="onInput"
      @focus="onFocus"
      @blur="onBlur"
    />
    <button
      v-if="props.modelValue !== null"
      class="btn btn-sm"
      type="button"
      style="margin-top: 4px"
      @click="clear"
    >
      清除选择
    </button>
    <div v-if="open" class="school-options">
      <div v-if="loading" class="school-option muted">搜索中…</div>
      <template v-else>
        <div
          v-for="school in options"
          :key="school.id"
          class="school-option"
          @mousedown.prevent="pick(school)"
        >
          {{ school.name }}
          <span class="muted">（{{ school.region }}）</span>
        </div>
        <div v-if="options.length === 0" class="school-option muted">无匹配学校</div>
      </template>
    </div>
  </div>
</template>
