<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import * as api from '@/api'
import type { School } from '@/api/types'
import { useAuthStore } from '@/stores/auth'
import { errorMessage } from '@/utils/errors'

const router = useRouter()
const auth = useAuthStore()

const formRef = ref<FormInstance>()
const loading = ref(false)

const form = reactive({
  username: '',
  password: '',
  email: '',
  displayName: '',
  schoolId: null as number | null,
})

const rules: FormRules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 32, message: '用户名长度为 3-32 个字符', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 8, max: 64, message: '密码至少 8 位', trigger: 'blur' },
  ],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { type: 'email', message: '请输入有效的邮箱地址', trigger: ['blur', 'change'] },
  ],
}

// ---------- 学校选择：远程搜索（仅搜索，不允许自建） ----------
const schoolOptions = ref<School[]>([])
const schoolsLoading = ref(false)

async function searchSchools(query: string): Promise<void> {
  schoolsLoading.value = true
  try {
    schoolOptions.value = await api.getSchools(query.trim() || undefined)
  } catch (err) {
    ElMessage.error(errorMessage(err, '学校搜索失败'))
  } finally {
    schoolsLoading.value = false
  }
}

// 下拉展开时补一次列表，避免初始为空
function onSchoolVisibleChange(visible: boolean): void {
  if (visible && schoolOptions.value.length === 0) {
    void searchSchools('')
  }
}

// ---------- 提交注册 ----------
async function onSubmit(): Promise<void> {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    await api.register({
      username: form.username.trim(),
      password: form.password,
      email: form.email.trim(),
      displayName: form.displayName.trim() || undefined,
      schoolId: form.schoolId,
    })
    ElMessage.success('注册成功，正在登录…')
    // 注册成功后自动登录，进入比赛列表
    await auth.login(form.username.trim(), form.password)
    void router.push('/competitions')
  } catch (err) {
    ElMessage.error(errorMessage(err, '注册失败，请稍后重试'))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card">
      <!-- 品牌渐变头部 -->
      <div class="login-header">
        <img class="login-logo" src="@/assets/logo.svg" alt="logo" />
        <h1 class="login-title">创建账号</h1>
        <p class="login-subtitle">注册后自动登录商赛办赛管理系统</p>
      </div>

      <el-form
        ref="formRef"
        class="login-form"
        :model="form"
        :rules="rules"
        label-width="0"
        @keyup.enter="onSubmit"
      >
        <el-form-item prop="username">
          <el-input
            v-model="form.username"
            placeholder="用户名（3-32 位）"
            size="large"
            autocomplete="username"
          />
        </el-form-item>
        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="密码（至少 8 位）"
            size="large"
            show-password
            autocomplete="new-password"
          />
        </el-form-item>
        <el-form-item prop="email">
          <el-input
            v-model="form.email"
            type="email"
            placeholder="邮箱"
            size="large"
            autocomplete="email"
          />
        </el-form-item>
        <el-form-item prop="displayName">
          <el-input
            v-model="form.displayName"
            placeholder="显示名（可选）"
            size="large"
            autocomplete="nickname"
          />
        </el-form-item>
        <el-form-item prop="schoolId">
          <el-select
            v-model="form.schoolId"
            class="school-select"
            placeholder="所在学校（可选，输入搜索）"
            size="large"
            filterable
            remote
            clearable
            :remote-method="searchSchools"
            :loading="schoolsLoading"
            @visible-change="onSchoolVisibleChange"
          >
            <el-option v-for="school in schoolOptions" :key="school.id" :label="school.name" :value="school.id">
              <span>{{ school.name }}</span>
              <span class="school-region">{{ school.region }}</span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" size="large" class="login-btn" :loading="loading" @click="onSubmit">
            注册并登录
          </el-button>
        </el-form-item>
      </el-form>

      <div class="login-footer">
        已有账号？
        <RouterLink to="/login">返回登录</RouterLink>
      </div>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  height: 100vh; /* 回退 */
  height: 100dvh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #eef1fe 0%, #f6f7fb 55%, #e9f6fb 100%);
  position: relative;
  overflow-y: auto; /* 键盘弹起/小屏时允许滚动到注册卡片 */
  -webkit-overflow-scrolling: touch;
  padding: 24px 0;
}
/* 四角品牌光晕（与登录页一致的氛围） */
.login-page::before {
  content: "";
  position: absolute;
  width: 540px;
  height: 540px;
  top: -180px;
  left: -140px;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.18), rgba(99, 102, 241, 0) 70%);
}
.login-page::after {
  content: "";
  position: absolute;
  width: 480px;
  height: 480px;
  bottom: -170px;
  right: -120px;
  background: radial-gradient(circle, rgba(6, 182, 212, 0.16), rgba(6, 182, 212, 0) 70%);
}
.login-card {
  position: relative;
  z-index: 1;
  width: min(420px, calc(100vw - 32px));
  padding-bottom: 28px;
  background: #fff;
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  border: 1px solid var(--color-border);
  overflow: hidden;
  animation: cardFloat 0.5s var(--ease-spring) both;
}
@keyframes cardFloat {
  from {
    opacity: 0;
    transform: translateY(16px) scale(0.98);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}
/* 品牌渐变头部 */
.login-header {
  background: var(--gradient-brand);
  padding: 30px 32px 24px;
  text-align: center;
}
.login-logo {
  width: 52px;
  height: 52px;
  margin: 0 auto 12px;
  border-radius: 14px;
  object-fit: cover;
  display: block;
  background: #fff;
  box-shadow: 0 8px 20px rgba(15, 23, 42, 0.22);
}
.login-title {
  font-size: 21px;
  font-weight: 700;
  color: #fff;
  margin: 0;
  letter-spacing: 0.5px;
}
.login-subtitle {
  margin: 4px 0 0;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.82);
}
.login-form {
  padding: 26px 32px 4px;
}
.school-select {
  width: 100%;
}
.school-region {
  float: right;
  font-size: 12px;
  color: var(--color-text-tertiary);
}
.login-btn {
  width: 100%;
}
.login-footer {
  text-align: center;
  font-size: 13px;
  color: var(--color-text-secondary);
}
.login-footer a {
  color: var(--color-primary);
  font-weight: 600;
  text-decoration: none;
}
.login-footer a:hover {
  text-decoration: underline;
}
@media (max-width: 640px) {
  .login-card {
    border-radius: var(--radius-md);
  }
  .login-header {
    padding: 26px 24px 20px;
  }
  .login-form {
    padding: 22px 24px 4px;
  }
}
</style>
