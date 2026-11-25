<template>
  <!--
    append-to-body 必须开：本组件挂在顶栏（.topbar）内，而 .topbar 用了
    backdrop-filter，会把它变成 position:fixed 后代的**包含块**；
    el-dialog 的 .el-overlay 是 position:fixed（top/bottom/left/right:0），
    不开启时会被压在顶栏那条 ~56px 的横条里并被外层 overflow:hidden 裁掉，
    表现就是「点了修改密码但窗口不出现」。（MapsManager 等处同理。）
  -->
  <el-dialog
    v-model="visible"
    title="修改密码"
    width="420px"
    :close-on-click-modal="false"
    append-to-body
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="96px" @submit.prevent>
      <el-form-item label="原密码" prop="oldPassword">
        <el-input
          v-model="form.oldPassword"
          type="password"
          show-password
          autocomplete="current-password"
          placeholder="请输入原密码"
        />
      </el-form-item>
      <el-form-item label="新密码" prop="newPassword">
        <el-input
          v-model="form.newPassword"
          type="password"
          show-password
          autocomplete="new-password"
          placeholder="8-128 位"
        />
      </el-form-item>
      <el-form-item label="确认新密码" prop="confirmPassword">
        <el-input
          v-model="form.confirmPassword"
          type="password"
          show-password
          autocomplete="new-password"
          placeholder="再次输入新密码"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">确认修改</el-button>
    </template>
  </el-dialog>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, type FormInstance, type FormRules } from 'element-plus'
import * as api from '@/api'
import { useAuthStore } from '@/stores/auth'
import { errorMessage } from '@/utils/errors'

const props = defineProps<{ modelValue: boolean }>()
const emit = defineEmits<{ (e: 'update:modelValue', value: boolean): void }>()

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const router = useRouter()
const auth = useAuthStore()
const formRef = ref<FormInstance>()
const submitting = ref(false)
const form = reactive({ oldPassword: '', newPassword: '', confirmPassword: '' })

const rules: FormRules = {
  oldPassword: [{ required: true, message: '请输入原密码', trigger: 'blur' }],
  newPassword: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 8, max: 128, message: '密码长度需为 8-64 位', trigger: 'blur' },
  ],
  confirmPassword: [
    // 必填（表单会显示红星）：为空时给出「请再次输入新密码」而不是"不一致"
    { required: true, message: '请再次输入新密码', trigger: ['blur', 'change'] },
    {
      validator: (_rule, value, callback) => {
        if (!value) callback(new Error('请再次输入新密码'))
        else if (value !== form.newPassword) callback(new Error('两次输入的新密码不一致'))
        else callback()
      },
      trigger: ['blur', 'change'],
    },
  ],
}

// 新密码改动后重新校验「确认新密码」：避免先填确认、后改新密码时校验状态过期
watch(
  () => form.newPassword,
  () => {
    if (form.confirmPassword) {
      void formRef.value?.validateField('confirmPassword').catch(() => undefined)
    }
  },
)

async function submit(): Promise<void> {
  const ok = await formRef.value?.validate().catch(() => false)
  if (!ok) return
  submitting.value = true
  try {
    await api.changePassword(form.oldPassword, form.newPassword)
    ElMessage.success('密码已修改，请重新登录')
    visible.value = false
    // 后端已顶号（tokenVersion+1）：清会话并回登录页
    auth.clearSession()
    void router.push({ name: 'login' })
  } catch (err) {
    ElMessage.error(errorMessage(err))
  } finally {
    submitting.value = false
  }
}
</script>
