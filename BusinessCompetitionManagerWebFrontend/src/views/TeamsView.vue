<script setup lang="ts">
// 组队管理页：队伍列表 + 创建队伍 / 加入队伍 + 组队码 + 管理员调整产业
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import type { FormInstance, FormRules } from 'element-plus'
import * as api from '@/api'
import type { Team, TeamJoinCode } from '@/api/types'
import { useAuthStore } from '@/stores/auth'
import { formatDateTime } from '@/utils/format'
import { errorMessage } from '@/utils/errors'

const props = defineProps<{ cid: string }>()
const auth = useAuthStore()

const teams = ref<Team[]>([])
const loading = ref(false)

// ---------- 创建队伍 ----------
const showCreate = ref(false)
const creating = ref(false)
const createRef = ref<FormInstance>()
const createForm = ref({
  name: '',
  industryChoice: [] as string[],
  industryAdjustAccepted: [] as string[],
})
const createRules: FormRules = {
  name: [{ required: true, message: '请填写队伍名称', trigger: 'blur' }],
}

// ---------- 加入队伍 ----------
const showJoin = ref(false)
const joining = ref(false)
const joinCode = ref('')

// ---------- 调整产业（管理员） ----------
const showAdjust = ref(false)
const adjusting = ref(false)
const adjustTarget = ref<Team | null>(null)
const adjustForm = ref({
  industryFinal: '',
  industryChoice: [] as string[],
  industryAdjustAccepted: [] as string[],
})

/** 系统超管或本比赛超管：可调整产业 */
const canAdjust = computed(() => {
  if (auth.isSuperuser) return true
  return auth.memberships.some(
    (m) => String(m.id) === props.cid && m.identity === 'COMP_SUPER_ADMIN',
  )
})

/** 是否为该队队长 */
function isCaptain(team: Team): boolean {
  return team.captainId === auth.user?.id
}

async function load(): Promise<void> {
  loading.value = true
  try {
    teams.value = await api.getTeams(props.cid)
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    loading.value = false
  }
}

async function submitCreate(): Promise<void> {
  try {
    await createRef.value?.validate()
  } catch {
    return
  }
  creating.value = true
  try {
    await api.createTeam(props.cid, {
      name: createForm.value.name.trim(),
      industryChoice: createForm.value.industryChoice,
      industryAdjustAccepted: createForm.value.industryAdjustAccepted,
    })
    ElMessage.success('队伍创建成功')
    showCreate.value = false
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    creating.value = false
  }
}

async function submitJoin(): Promise<void> {
  const code = joinCode.value.trim()
  if (!code) {
    ElMessage.warning('请输入组队码')
    return
  }
  joining.value = true
  try {
    const team = await api.joinTeam(props.cid, code)
    ElMessage.success(`已加入队伍「${team.name}」`)
    showJoin.value = false
    joinCode.value = ''
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    joining.value = false
  }
}

/** 队长生成组队码，弹窗展示 */
async function genJoinCode(team: Team): Promise<void> {
  let joinCodeInfo: TeamJoinCode
  try {
    joinCodeInfo = await api.createTeamJoinCode(props.cid, team.id)
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
    return
  }
  try {
    await ElMessageBox.alert(
      `组队码：<strong>${joinCodeInfo.code}</strong><br/>` +
        `有效期至：${joinCodeInfo.expiresAt ? formatDateTime(joinCodeInfo.expiresAt) : '永久'}<br/>` +
        `可用次数：${joinCodeInfo.maxUses}，已用：${joinCodeInfo.usedCount}`,
      '组队码生成成功',
      {
        dangerouslyUseHTMLString: true,
        confirmButtonText: '关闭',
      },
    )
  } catch {
    // 用户关闭弹窗，忽略
  }
}

/** 管理员打调整产业弹窗 */
function openAdjust(team: Team): void {
  adjustTarget.value = team
  adjustForm.value = {
    industryFinal: team.industryFinal,
    industryChoice: [...team.industryChoice],
    industryAdjustAccepted: [...team.industryAdjustAccepted],
  }
  showAdjust.value = true
}

async function submitAdjust(): Promise<void> {
  const target = adjustTarget.value
  if (!target) return
  const final = adjustForm.value.industryFinal.trim()
  if (!final) {
    ElMessage.warning('请填写最终产业')
    return
  }
  adjusting.value = true
  try {
    await api.adjustTeamIndustry(props.cid, target.id, {
      industryFinal: final,
      industryChoice: adjustForm.value.industryChoice,
      industryAdjustAccepted: adjustForm.value.industryAdjustAccepted,
    })
    ElMessage.success('产业已调整，公司已同步创建/更新')
    showAdjust.value = false
    await load()
  } catch (err) {
    ElMessage.error(errorMessage(err, '操作失败'))
  } finally {
    adjusting.value = false
  }
}

onMounted(() => void load())
</script>

<template>
  <div class="teams-page">
    <!-- 标题栏 -->
    <div class="page-toolbar">
      <h2 class="page-title">组队管理</h2>
      <div class="page-actions">
        <el-button @click="showJoin = true">
          <el-icon><Link /></el-icon>
          <span>加入队伍</span>
        </el-button>
        <el-button type="primary" @click="showCreate = true">
          <el-icon><Plus /></el-icon>
          <span>创建队伍</span>
        </el-button>
      </div>
    </div>

    <!-- 队伍表格 -->
    <el-card shadow="never">
      <el-table v-loading="loading" :data="teams" border empty-text="暂无队伍">
        <el-table-column label="队伍名称" min-width="130">
          <template #default="{ row }">
            <span class="team-name">{{ row.name }}</span>
            <el-tag v-if="isCaptain(row)" size="small" type="warning" class="mini-tag">我是队长</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="captainName" label="队长" width="110" />
        <el-table-column label="成员" min-width="150">
          <template #default="{ row }">
            <template v-if="row.members?.length">
              <el-tag
                v-for="m in row.members"
                :key="m.userId"
                size="small"
                class="mini-tag"
                :type="m.userId === row.captainId ? 'warning' : 'info'"
              >
                {{ m.displayName || m.username }}
              </el-tag>
            </template>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="产业志愿" min-width="130">
          <template #default="{ row }">
            <template v-if="row.industryChoice?.length">
              <el-tag v-for="c in row.industryChoice" :key="c" size="small" class="mini-tag">
                {{ c }}
              </el-tag>
            </template>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="接受调剂" min-width="130">
          <template #default="{ row }">
            <template v-if="row.industryAdjustAccepted?.length">
              <el-tag
                v-for="c in row.industryAdjustAccepted"
                :key="c"
                size="small"
                type="info"
                class="mini-tag"
              >
                {{ c }}
              </el-tag>
            </template>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="最终产业" width="110">
          <template #default="{ row }">
            <el-tag v-if="row.industryFinal" size="small" type="success">
              {{ row.industryFinal }}
            </el-tag>
            <span v-else class="muted">未定</span>
          </template>
        </el-table-column>
        <el-table-column label="公司" width="90">
          <template #default="{ row }">{{ row.companyId ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">{{ formatDateTime(row.createdAt) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="isCaptain(row)"
              size="small"
              link
              type="primary"
              @click="genJoinCode(row)"
            >
              生成组队码
            </el-button>
            <el-button v-if="canAdjust" size="small" link type="warning" @click="openAdjust(row)">
              调整产业
            </el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 创建队伍弹窗 -->
    <el-dialog v-model="showCreate" title="创建队伍" width="520px" destroy-on-close>
      <el-alert
        type="info"
        :closable="false"
        show-icon
        title="输入产业 key，回车添加"
        class="dialog-tip"
      />
      <el-form
        ref="createRef"
        :model="createForm"
        :rules="createRules"
        label-width="110px"
        @submit.prevent
      >
        <el-form-item label="队伍名称" prop="name">
          <el-input v-model="createForm.name" placeholder="例如：星辰队" maxlength="60" />
        </el-form-item>
        <el-form-item label="产业志愿">
          <el-select
            v-model="createForm.industryChoice"
            multiple
            filterable
            allow-create
            default-first-option
            :reserve-keyword="false"
            placeholder="输入产业 key 后回车，可多个"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="接受调剂">
          <el-select
            v-model="createForm.industryAdjustAccepted"
            multiple
            filterable
            allow-create
            default-first-option
            :reserve-keyword="false"
            placeholder="可接受的调剂产业 key，可多个"
            style="width: 100%"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreate = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="submitCreate">创建</el-button>
      </template>
    </el-dialog>

    <!-- 加入队伍弹窗 -->
    <el-dialog v-model="showJoin" title="加入队伍" width="420px" destroy-on-close>
      <el-form label-width="80px" @submit.prevent>
        <el-form-item label="组队码">
          <el-input
            v-model="joinCode"
            placeholder="请输入队长提供的组队码"
            clearable
            @keyup.enter="submitJoin"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showJoin = false">取消</el-button>
        <el-button type="primary" :loading="joining" @click="submitJoin">加入</el-button>
      </template>
    </el-dialog>

    <!-- 调整产业弹窗（管理员） -->
    <el-dialog v-model="showAdjust" title="调整产业" width="520px" destroy-on-close>
      <el-alert
        type="warning"
        :closable="false"
        show-icon
        title="保存后同步创建/更新对应公司"
        class="dialog-tip"
      />
      <el-form :model="adjustForm" label-width="110px" @submit.prevent>
        <el-form-item label="最终产业">
          <el-select
            v-model="adjustForm.industryFinal"
            filterable
            allow-create
            default-first-option
            :reserve-keyword="false"
            placeholder="该队伍最终确定的产业 key"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="产业志愿">
          <el-select
            v-model="adjustForm.industryChoice"
            multiple
            filterable
            allow-create
            default-first-option
            :reserve-keyword="false"
            placeholder="可一并修订产业志愿"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="接受调剂">
          <el-select
            v-model="adjustForm.industryAdjustAccepted"
            multiple
            filterable
            allow-create
            default-first-option
            :reserve-keyword="false"
            placeholder="可一并修订接受调剂范围"
            style="width: 100%"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showAdjust = false">取消</el-button>
        <el-button type="primary" :loading="adjusting" @click="submitAdjust">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped lang="scss">
.page-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.page-actions {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

.team-name {
  font-weight: 600;
  color: var(--color-text-primary);
}

.mini-tag {
  margin: 2px 4px 2px 0;
}

.muted {
  color: var(--color-text-tertiary);
  font-size: var(--font-sm);
}

.dialog-tip {
  margin-bottom: 16px;
}
</style>
