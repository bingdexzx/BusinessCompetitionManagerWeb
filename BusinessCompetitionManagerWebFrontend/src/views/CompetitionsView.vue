<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { getCompetitions, type Competition } from '@/services/api'

const competitions = ref<Competition[]>([])
const loading = ref(true)
const error = ref('')

onMounted(async () => {
  try {
    competitions.value = await getCompetitions()
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <main>
    <h1>竞赛列表</h1>
    <p v-if="loading">加载中…</p>
    <p v-else-if="error" class="error">{{ error }}</p>
    <ul v-else>
      <li v-for="item in competitions" :key="item.id">
        {{ item.name }} —— {{ item.description }}
      </li>
      <li v-if="competitions.length === 0">暂无竞赛数据</li>
    </ul>
  </main>
</template>

<style scoped>
.error {
  color: red;
}
</style>
