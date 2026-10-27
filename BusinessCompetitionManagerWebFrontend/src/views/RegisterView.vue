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
// 服务端失败原因：就地显示在提交按钮上方（ElMessage 同时保留，便于跨页面可见）
const errorText = ref('')

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
  // 真实姓名（落库到 User.display_name）：必填，全站展示即用这个姓名
  displayName: [
    { required: true, message: '请输入真实姓名', trigger: ['blur', 'change'] },
    { max: 100, message: '真实姓名最长 100 个字符', trigger: 'blur' },
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
  errorText.value = ''
  loading.value = true
  try {
    await api.register({
      username: form.username.trim(),
      password: form.password,
      email: form.email.trim(),
      displayName: form.displayName.trim(), // 真实姓名：必填
      schoolId: form.schoolId,
    })
    ElMessage.success('注册成功，正在登录…')
    // 注册成功后自动登录，进入比赛列表
    await auth.login(form.username.trim(), form.password)
    void router.push('/competitions')
  } catch (err) {
    const message = errorMessage(err, '注册失败，请稍后重试')
    errorText.value = message
    ElMessage.error(message)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-card anim-fade-in-up">
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
        <!-- 字段分组：账号类 / 个人信息类分开，避免 6 个输入框连成一坨 -->
        <div class="form-group">
          <div class="section-title">账号信息</div>
          <el-form-item prop="username">
            <el-input
              v-model="form.username"
              placeholder="用户名（3-32 位）"
              size="large"
              autocomplete="username"
              @input="errorText = ''"
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
              @input="errorText = ''"
            />
          </el-form-item>
        </div>

        <div class="form-group">
          <div class="section-title">个人信息</div>
          <el-form-item prop="email">
            <el-input
              v-model="form.email"
              type="email"
              placeholder="邮箱"
              size="large"
              autocomplete="email"
              @input="errorText = ''"
            />
          </el-form-item>
          <el-form-item prop="displayName">
            <el-input
              v-model="form.displayName"
              placeholder="真实姓名"
              size="large"
              maxlength="100"
              autocomplete="name"
              @input="errorText = ''"
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
              @change="errorText = ''"
            >
              <el-option v-for="school in schoolOptions" :key="school.id" :label="school.name" :value="school.id">
                <span>{{ school.name }}</span>
                <span class="school-region">{{ school.region }}</span>
              </el-option>
            </el-select>
          </el-form-item>
        </div>

        <!-- 错误就地显示：贴近提交按钮，不用等 toast 消失 -->
        <div v-if="errorText" class="notice notice--danger login-error" role="alert">
          <el-icon class="notice__icon"><WarningFilled /></el-icon>
          <span>{{ errorText }}</span>
        </div>

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
  background: var(--color-surface);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  border: 1px solid var(--color-border);
  overflow: hidden;
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
  padding: 24px 32px 4px;
}
/* 字段分组：每组一个轻标题，组内保持单列聚焦 */
.form-group + .form-group {
  margin-top: 4px;
}
.login-form .section-title {
  margin-bottom: 10px;
  font-size: var(--font-sm);
  font-weight: 600;
  color: var(--color-text-secondary);
}
.login-error {
  margin-bottom: 16px;
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
