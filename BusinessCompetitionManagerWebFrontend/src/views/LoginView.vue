<script setup lang="ts">
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Lock, User } from '@element-plus/icons-vue'
import type { FormInstance, FormRules } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { errorMessage } from '@/utils/errors'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const formRef = ref<FormInstance>()
const loading = ref(false)
// 服务端失败原因：就地显示在提交按钮上方（ElMessage 同时保留，便于跨页面可见）
const errorText = ref('')

const form = reactive({
  username: '',
  password: '',
})

const rules: FormRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function handleLogin(): Promise<void> {
  if (!formRef.value) return
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  errorText.value = ''
  loading.value = true
  try {
    await auth.login(form.username.trim(), form.password)
    ElMessage.success('登录成功')
    // 优先回跳登录前页面，否则进入比赛列表
    const redirect = route.query.redirect
    void router.push(typeof redirect === 'string' && redirect ? redirect : '/competitions')
  } catch (err) {
    const message = errorMessage(err, '登录失败，请稍后重试')
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
        <h1 class="login-title">商赛办赛管理系统</h1>
        <p class="login-subtitle">Business Competition Manager</p>
      </div>

      <el-form
        ref="formRef"
        class="login-form"
        :model="form"
        :rules="rules"
        label-width="0"
        @keyup.enter="handleLogin"
      >
        <div class="form-group">
          <div class="section-title">账号信息</div>
          <el-form-item prop="username">
            <el-input
              v-model="form.username"
              placeholder="用户名"
              :prefix-icon="User"
              size="large"
              autocomplete="username"
              @input="errorText = ''"
            />
          </el-form-item>
          <el-form-item prop="password">
            <el-input
              v-model="form.password"
              type="password"
              placeholder="密码"
              :prefix-icon="Lock"
              size="large"
              show-password
              autocomplete="current-password"
              @input="errorText = ''"
            />
          </el-form-item>
        </div>

        <!-- 错误就地显示：贴近字段与提交按钮，不用等 toast 消失 -->
        <div v-if="errorText" class="notice notice--danger login-error" role="alert">
          <el-icon class="notice__icon"><WarningFilled /></el-icon>
          <span>{{ errorText }}</span>
        </div>

        <el-form-item>
          <el-button
            type="primary"
            size="large"
            class="login-btn"
            :loading="loading"
            @click="handleLogin"
          >
            登 录
          </el-button>
        </el-form-item>
      </el-form>

      <div class="login-footer">
        还没有账号？
        <RouterLink to="/register">立即注册</RouterLink>
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
  overflow-y: auto; /* 键盘弹起/小屏时允许滚动到登录卡片 */
  -webkit-overflow-scrolling: touch;
}
/* 四角品牌光晕（旧产品同款氛围） */
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
  width: min(400px, calc(100vw - 32px));
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
  padding: 34px 32px 26px;
  text-align: center;
}
.login-logo {
  width: 56px;
  height: 56px;
  margin: 0 auto 12px;
  border-radius: 15px;
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
  letter-spacing: 0.08em;
}
.login-form {
  padding: 24px 32px 4px;
}
/* 字段分组：单列聚焦，账号类字段归为一组 */
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
    padding: 28px 24px 22px;
  }
  .login-form {
    padding: 22px 24px 4px;
  }
}
</style>
