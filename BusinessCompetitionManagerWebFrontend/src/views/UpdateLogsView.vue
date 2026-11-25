<template>
  <div class="update-logs-view anim-stagger page">
    <PageHeader title="更新日志" />
    <el-card shadow="never" class="section-card">
      <template #header>
        <div class="card-head">
          <div class="card-heading">
            <span class="section-title">已发布更新</span>
            <span class="count-tip value-num">共 {{ logs.length }} 条</span>
          </div>
          <div class="head-actions">
            <el-button :icon="Refresh" @click="load">刷新</el-button>
            <el-button type="primary" :icon="Plus" @click="openCreate">发布更新</el-button>
          </div>
        </div>
      </template>
            <TableSkeleton v-if="loading && !hasLoaded" :rows="6" />
<el-table v-loading="loading && hasLoaded" :data="logs" stripe size="small" border>
        <template #empty>
          <el-empty description="暂无更新日志" :image-size="72" />
        </template>
        <el-table-column label="版本" width="150">
          <template #default="{ row }">
            <el-tag size="small" effect="plain">{{ row.version }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="title" label="标题" min-width="200" show-overflow-tooltip />
        <el-table-column label="发布时间" width="180">
          <template #default="{ row }">
            <span class="value-num">{{ formatDateTime(row.publishedAt) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="createdByUsername" label="发布人" width="140" show-overflow-tooltip />
        <el-table-column label="内容" min-width="260">
          <template #default="{ row }">
            <span class="log-preview">{{ row.content }}</span>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
    <el-dialog v-model="dialogVisible" title="发布更新" width="560px" destroy-on-close>
      <el-form ref="formRef" :model="form" :rules="rules" label-width="96px">
        <el-form-item label="版本号" prop="version">
          <el-input v-model="form.version" placeholder="如 2026.11.23" maxlength="40" />
        </el-form-item>
        <el-form-item label="标题" prop="title">
          <el-input v-model="form.title" placeholder="本次更新的一句话说明" maxlength="120" />
        </el-form-item>
        <el-form-item label="更新内容" prop="content">
          <el-input
            v-model="form.content"
            type="textarea"
            :rows="10"
            placeholder="按条目填写本次更新内容，用户弹窗会原样展示换行"
            maxlength="5000"
            show-word-limit
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="publishing" @click="publish">发布</el-button>
      </template>
    </el-dialog>
  </div>
</template>
<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import TableSkeleton from '@/components/common/TableSkeleton.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import { Plus, Refresh } from '@element-plus/icons-vue'
import { createUpdateLog, getUpdateLogs } from '@/api'
import type { UpdateLog } from '@/api/types'
import { errorMessage } from '@/utils/errors'
import { formatDateTime } from '@/utils/format'
const logs = ref<UpdateLog[]>([])
const loading = ref(false)
/** 首屏骨架 → 之后刷新用 v-loading */
const hasLoaded = ref(false);
const dialogVisible = ref(false)
const publishing = ref(false)
const formRef = ref<FormInstance>()
const form = reactive({ version: '', title: '', content: '' })
const rules: FormRules = {
  version: [{ required: true, message: '请填写版本号', trigger: 'blur' }],
  title: [{ required: true, message: '请填写更新标题', trigger: 'blur' }],
  content: [{ required: true, message: '请填写更新内容', trigger: 'blur' }],
}
async function load(): Promise<void> {
  loading.value = true
  try {
    logs.value = await getUpdateLogs()
  } catch (err) {
    ElMessage.error(errorMessage(err, '更新日志加载失败'))
  } finally {
    loading.value = false;
  hasLoaded.value = true;
  }
}
function openCreate(): void {
  form.version = ''
  form.title = ''
  form.content = ''
  dialogVisible.value = true
}
async function publish(): Promise<void> {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }
  publishing.value = true
  try {
    await createUpdateLog({
      version: form.version.trim(),
      title: form.title.trim(),
      content: form.content.trim(),
    })
    ElMessage.success('更新日志已发布')
    dialogVisible.value = false
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err, '发布失败'))
  } finally {
    publishing.value = false
  }
}
onMounted(() => void load())
</script>
<style scoped>
.section-card {
  margin-bottom: 16px;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.card-heading {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.card-heading .section-title {
  margin-bottom: 0;
}
.head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.log-preview {
  display: -webkit-box;
  overflow: hidden;
  color: var(--color-text-secondary);
  font-size: 13px;
  line-height: 1.5;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}
</style>