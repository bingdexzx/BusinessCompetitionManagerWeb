<script setup lang="ts">
// 学校管理（仅系统超级管理员）：学校主数据维护——账号的「学校」归属即从此处维护。
// 删除学校不删账号（后端 User.school 为 SET_NULL，仅清空归属）。
import { onMounted, reactive, ref } from 'vue'
import TableSkeleton from '@/components/common/TableSkeleton.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Search } from '@element-plus/icons-vue'
import { createSchool, deleteSchool, getSchools, updateSchool } from '@/api'
import type { School } from '@/api/types'
import { errorMessage } from '@/utils/errors'
import { useResourceRefresh } from '@/composables/useNotifications'
const schools = ref<School[]>([])
const loading = ref(false)
/** 首屏骨架 → 之后刷新用 v-loading */
const hasLoaded = ref(false);
const keyword = ref('')
async function load(): Promise<void> {
  loading.value = true
  try {
    schools.value = await getSchools(keyword.value.trim() || undefined)
  } catch (err) {
    ElMessage.error(errorMessage(err, '学校加载失败'))
  } finally {
    loading.value = false;
  hasLoaded.value = true;
  }
}
// 实时同步：其他超级管理员增删改学校后自动刷新（400ms 去抖合并）
useResourceRefresh(['schools'], load)
// ---------- 新建 / 编辑 ----------
const dialogVisible = ref(false)
const submitting = ref(false)
const editingId = ref<number | null>(null)
const form = reactive({ name: '', region: '' })
function openCreate(): void {
  editingId.value = null
  form.name = ''
  form.region = ''
  dialogVisible.value = true
}
function openEdit(row: School): void {
  editingId.value = row.id
  form.name = row.name
  form.region = row.region || ''
  dialogVisible.value = true
}
async function onSubmit(): Promise<void> {
  const name = form.name.trim()
  if (!name) {
    ElMessage.warning('请输入学校名称')
    return
  }
  submitting.value = true
  try {
    const payload = { name, region: form.region.trim() }
    if (editingId.value === null) {
      await createSchool(payload)
      ElMessage.success('学校已创建')
    } else {
      await updateSchool(editingId.value, payload)
      ElMessage.success('学校已更新')
    }
    dialogVisible.value = false
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err, '保存失败'))
  } finally {
    submitting.value = false
  }
}
async function onDelete(row: School): Promise<void> {
  try {
    await ElMessageBox.confirm(
      `确定删除学校「${row.name}」？该学校下的账号会保留，仅清空学校归属。`,
      '删除学校',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return // 用户取消
  }
  try {
    await deleteSchool(row.id)
    ElMessage.success('学校已删除')
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err, '删除失败'))
  }
}
onMounted(() => void load())
</script>
<template>
  <div class="school-view page">
    <PageHeader title="学校管理" />
    <el-card shadow="never" class="school-card anim-fade-in-up">
      <template #header>
        <div class="card-head">
          <div class="card-heading">
            <span class="section-title">学校列表</span>
            <span class="count-tip value-num">共 {{ schools.length }} 所</span>
          </div>
          <div class="filter-bar">
            <el-input
              v-model="keyword"
              placeholder="按名称搜索"
              clearable
              style="width: 200px"
              @keyup.enter="load"
              @clear="load"
            />
            <el-button type="primary" :icon="Search" @click="load">查询</el-button>
            <el-button :icon="Refresh" @click="load">刷新</el-button>
            <el-button type="primary" :icon="Plus" @click="openCreate">新建学校</el-button>
          </div>
        </div>
      </template>
            <TableSkeleton v-if="loading && !hasLoaded" :rows="6" />
<el-table :data="schools" v-loading="loading && hasLoaded" row-key="id" stripe size="small" border>
        <el-table-column prop="name" label="学校名称" min-width="220" show-overflow-tooltip />
        <el-table-column label="地区" min-width="160">
          <template #default="{ row }">{{ row.region || '—' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150" align="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openEdit(row)">编辑</el-button>
            <el-button link type="danger" size="small" class="op-danger" @click="onDelete(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无学校，点击「新建学校」创建" :image-size="72" />
        </template>
      </el-table>
    </el-card>
    <el-dialog
      v-model="dialogVisible"
      :title="editingId === null ? '新建学校' : '编辑学校'"
      width="420px"
    >
      <el-form label-width="96px" @submit.prevent>
        <el-form-item label="名称" required>
          <el-input v-model="form.name" maxlength="120" placeholder="学校名称（唯一）" />
        </el-form-item>
        <el-form-item label="地区">
          <el-input v-model="form.region" maxlength="120" placeholder="可选，如：华东" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="onSubmit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
<style scoped>
.school-view {
  display: flex;
  flex-direction: column;
}
.school-card {
  margin-bottom: 16px;
}
.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
/* 标题 + 数量：标题用统一 section-title，数量弱化为辅助信息 */
.card-heading {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.card-heading .section-title {
  margin-bottom: 0;
}
.count-tip {
  font-size: var(--font-xs);
  color: var(--color-text-tertiary);
}
/* 危险操作视觉降级：平时弱化，悬停才亮起，避免与主操作抢注意力 */
:deep(.op-danger.el-button.is-link) {
  color: var(--color-text-tertiary);
}
:deep(.op-danger.el-button.is-link:hover) {
  color: var(--color-danger);
}
.filter-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
</style>