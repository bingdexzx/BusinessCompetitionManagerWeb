<template>
  <div class="region-overview">
    <div class="page-header">
      <h2 class="page-title">区域总览</h2>
      <el-button
        size="small"
        :loading="loading"
        @click="refreshAll"
      >
        <el-icon v-if="!loading"><Refresh /></el-icon>
        刷新
      </el-button>
    </div>

    <el-empty v-if="regions.length === 0 && !loading" description="地图中暂无区域，请在地图管理中为节点设置所属区域" />
    <!-- 首屏加载：骨架占位，避免整块空白；文案保留 -->
    <div v-else-if="regions.length === 0 && loading" class="ro-loading">
      <div class="ro-skeleton">
        <div v-for="i in 2" :key="i" class="skeleton ro-skeleton-band" />
      </div>
      <p class="ro-loading-text">正在加载区域数据…</p>
    </div>

    <div v-else class="region-list anim-stagger">
      <div v-for="region in regions" :key="region.region" class="region-band">
        <div class="band-header">
          <div class="band-title">
            <span class="band-name">{{ region.region }}</span>
          </div>
        </div>

        <!-- 上半部分：消费者需求 + 上半区数据框 -->
        <div class="band-section">
          <div class="section-head">
            <span class="section-title">消费者需求</span>
            <div class="section-actions">
              <el-button v-if="canEdit" size="small" type="success" plain @click="openAddDemand(region)">
                + 添加需求
              </el-button>
              <el-button v-if="canEdit" size="small" type="primary" plain @click="openAddFrame(region, 'top')">
                + 添加数据框
              </el-button>
            </div>
          </div>

          <div v-if="demandsOf(region).length === 0 && topCards(region).length === 0" class="band-empty">暂无需求与数据</div>

          <div class="band-frames">
            <div v-for="d in demandsOf(region)" :key="d.id" class="frame demand-frame hover-lift">
              <div class="frame-top">
                <span class="frame-name" :title="d.productName">{{ d.productName }}</span>
                <div v-if="canEdit" class="frame-actions">
                  <el-icon class="fa-edit" title="编辑" @click="openEditDemand(region, d)"><Edit /></el-icon>
                  <el-icon class="fa-del" title="删除" @click="removeDemand(region, d)"><Close /></el-icon>
                </div>
              </div>
              <div class="frame-value value-num">
                {{ d.quantity }}<span class="frame-unit"> 件</span>
              </div>
              <div class="frame-meta" v-if="d.note">备注：{{ d.note }}</div>
            </div>
            <div v-for="card in topCards(region)" :key="card.id" class="frame hover-lift" :class="{ invalid: card.valid === false }">
              <div class="frame-top">
                <span class="frame-name" :title="card.displayName">{{ card.displayName }}</span>
                <div v-if="canEdit" class="frame-actions">
                  <el-icon class="fa-edit" title="编辑" @click="openEditFrame(region, card)"><Edit /></el-icon>
                  <el-icon class="fa-del" title="移除" @click="removeFrame(region, card)"><Close /></el-icon>
                </div>
              </div>
              <div class="frame-value value-num">{{ formatValue(card) }}</div>
              <div class="frame-meta" v-if="card.valid === false">字段已失效</div>
            </div>
          </div>
        </div>

        <!-- 下半部分：区域数据（数据框，下方） -->
        <div class="band-section">
          <div class="section-head">
            <span class="section-title">区域数据</span>
            <el-button v-if="canEdit" size="small" type="primary" plain @click="openAddFrame(region, 'bottom')">
              + 添加数据框
            </el-button>
          </div>

          <div v-if="bottomCards(region).length === 0" class="band-empty">暂无数据</div>

          <div class="band-frames">
            <div v-for="card in bottomCards(region)" :key="card.id" class="frame hover-lift" :class="{ invalid: card.valid === false }">
              <div class="frame-top">
                <span class="frame-name" :title="card.displayName">{{ card.displayName }}</span>
                <div v-if="canEdit" class="frame-actions">
                  <el-icon class="fa-edit" title="编辑" @click="openEditFrame(region, card)"><Edit /></el-icon>
                  <el-icon class="fa-del" title="移除" @click="removeFrame(region, card)"><Close /></el-icon>
                </div>
              </div>
              <div class="frame-value value-num">{{ formatValue(card) }}</div>
              <div class="frame-meta" v-if="card.valid === false">字段已失效</div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 添加 / 编辑数据框 -->
    <el-dialog append-to-body v-model="showFrame" :title="editingCard ? '编辑数据框' : '添加数据框'" width="480px">
      <el-form label-width="92px">
        <el-form-item label="数据来源公司" required>
          <el-select
            v-model="frameCompanyId"
            placeholder="选择本区域内的公司"
            filterable
            style="width: 100%"
            :disabled="!!editingCard"
            @change="onCompanyChange"
          >
            <el-option
              v-for="c in regionCompanies"
              :key="c.id"
              :label="c.name"
              :value="c.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="产业字段" required>
          <el-select
            v-model="frameFieldId"
            placeholder="选择该公司的一个产业字段"
            style="width: 100%"
            :disabled="!frameCompanyId"
            @change="onFieldChange"
          >
            <el-option
              v-for="f in companyFields"
              :key="f.id"
              :label="`${f.name}（${fieldTypeLabel(f.fieldType)}${f.visible === false ? '·隐藏' : ''}）`"
              :value="f.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="展示名称" required>
          <el-input v-model="frameDisplayName" placeholder="如：本月产量 / 现金余额" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showFrame = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveFrame">保存</el-button>
      </template>
    </el-dialog>

    <!-- 添加 / 编辑消费者需求 -->
    <el-dialog append-to-body v-model="showDemand" :title="editingDemand ? '编辑需求' : '添加需求'" width="480px">
      <el-form label-width="92px">
        <el-form-item label="产品" required>
          <el-select
            v-model="demandForm.productId"
            placeholder="选择产品"
            filterable
            style="width: 100%"
          >
            <el-option
              v-for="p in productOptions"
              :key="p.id"
              :label="p.name"
              :value="p.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="产品数量" required>
          <BigNumberInput v-model="demandForm.quantity" :min="0" style="width: 100%" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="demandForm.note" type="textarea" :rows="2" placeholder="可选" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showDemand = false">取消</el-button>
        <el-button type="success" :loading="savingDemand" @click="saveDemand">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
// 区域总览（与旧项目同版式）：每个区域一张白色卡片 = 上半段「消费者需求」+ 下半段「区域数据」。
// 区域本身由「地图管理」的节点 region 字段决定，本页不再新建/重命名/删除区域。
import { ref, computed, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { Edit, Close, Refresh } from "@element-plus/icons-vue";
import { useAuthStore } from "@/stores/auth";
import {
  createConsumerDemand,
  deleteConsumerDemand,
  getBasedata,
  getCompanyIndustryFields,
  getConsumerDemands,
  getRegionMapOverview,
  saveRegionCardsByName,
  updateConsumerDemand,
} from "@/api";
import type {
  CompanyIndustryField,
  ConsumerDemandItem,
  RegionMapOverview,
  RegionOverviewCard,
} from "@/api";
import BigNumberInput from "@/components/common/BigNumberInput.vue";
import { useResourceRefresh } from "@/composables/useNotifications";
import { errorMessage } from "@/utils/errors";

const props = defineProps<{ cid: string }>();
const auth = useAuthStore();

/** 权限口径：系统超管 / 本比赛超管（与结算页一致） */
const canEdit = computed(
  () =>
    auth.isSuperuser ||
    auth.memberships.some((m) => String(m.id) === props.cid && m.identity === "COMP_SUPER_ADMIN"),
);

const regions = ref<RegionMapOverview[]>([]);
const demands = ref<ConsumerDemandItem[]>([]);
const loading = ref(false);

// 产品下拉选项（来自产品库，关联真实产品）
const productOptions = ref<{ id: number; name: string }[]>([]);

function demandsOf(region: RegionMapOverview): ConsumerDemandItem[] {
  return (demands.value || []).filter((d) => (d.regionName || "") === region.region);
}

// ===== 数据框编辑对话框 =====
const showFrame = ref(false);
const frameZone = ref<"top" | "bottom">("bottom");
const saving = ref(false);
const activeRegion = ref<RegionMapOverview | null>(null);
const editingCard = ref<RegionOverviewCard | null>(null);
const regionCompanies = ref<RegionMapOverview["companies"]>([]);
const companyFields = ref<CompanyIndustryField[]>([]);
const frameCompanyId = ref<number | null>(null);
const frameFieldId = ref<number | null>(null);
const frameDisplayName = ref("");

// ===== 消费者需求编辑对话框 =====
const showDemand = ref(false);
const savingDemand = ref(false);
const editingDemand = ref<ConsumerDemandItem | null>(null);
const demandForm = ref<{ productId: number | null; quantity: string | number; note: string }>({
  productId: null,
  quantity: 0,
  note: "",
});

/** 产业字段类型标签（兼容旧值 STRING/BOOLEAN/DICTIONARY/LIST 与新值 TEXT/BOOL/REF/DATE） */
const fieldTypeLabel = (t: string) =>
  ({
    NUMBER: "数值",
    TEXT: "文本",
    BOOL: "布尔",
    REF: "引用",
    DATE: "日期",
    STRING: "文本",
    BOOLEAN: "布尔",
    DICTIONARY: "字典",
    LIST: "列表",
  } as Record<string, string>)[t] || t;

async function loadRegions() {
  if (!props.cid) {
    regions.value = [];
    return;
  }
  loading.value = true;
  try {
    const list = (await getRegionMapOverview(props.cid)) || [];
    regions.value = list.map((r) => ({ ...r }));
  } catch (err) {
    ElMessage.error(errorMessage(err, "区域数据加载失败"));
  } finally {
    loading.value = false;
  }
}

async function loadDemands() {
  if (!props.cid) {
    demands.value = [];
    return;
  }
  try {
    const list = (await getConsumerDemands(props.cid)) || [];
    demands.value = list;
  } catch (err) {
    ElMessage.error(errorMessage(err, "消费者需求加载失败"));
  }
}

async function loadProducts() {
  if (!props.cid) {
    productOptions.value = [];
    return;
  }
  try {
    const res = await getBasedata(props.cid, "products", { page: 1, pageSize: 200 });
    // 后端列表接口返回分页对象 {items,total,...} 或直接数组，做兼容
    const list = Array.isArray(res) ? res : res?.items || [];
    productOptions.value = list
      .map((p) => ({ id: p.id, name: p.name ?? "" }))
      .filter((p) => p.id != null);
  } catch (err) {
    productOptions.value = [];
    ElMessage.error(errorMessage(err, "产品列表加载失败"));
  }
}

// ===== 数据框 =====
function topCards(region: RegionMapOverview): RegionOverviewCard[] {
  return (region.cards || []).filter((c) => c.zone === "top");
}
function bottomCards(region: RegionMapOverview): RegionOverviewCard[] {
  return (region.cards || []).filter((c) => c.zone !== "top");
}

/** 写回卡片：只提交契约字段（卡片的值由服务端按公司/字段实时计算） */
function toCardPayload(card: RegionOverviewCard): RegionOverviewCard {
  return {
    id: String(card.id),
    displayName: card.displayName,
    companyId: card.companyId,
    industryFieldId: card.industryFieldId ?? null,
    zone: card.zone === "top" ? "top" : "bottom",
  };
}

function openAddFrame(region: RegionMapOverview, zone: "top" | "bottom" = "bottom") {
  if (!props.cid) return;
  activeRegion.value = region;
  frameZone.value = zone;
  editingCard.value = null;
  frameCompanyId.value = null;
  frameFieldId.value = null;
  frameDisplayName.value = "";
  companyFields.value = [];
  // 本区「当地公司」直接来自地图区域总览返回，无需额外请求
  regionCompanies.value = region.companies || [];
  showFrame.value = true;
}

async function openEditFrame(region: RegionMapOverview, card: RegionOverviewCard) {
  activeRegion.value = region;
  editingCard.value = card;
  frameZone.value = card.zone === "top" ? "top" : "bottom";
  regionCompanies.value = region.companies || [];
  frameCompanyId.value = card.companyId;
  await onCompanyChange(card.companyId);
  frameFieldId.value = card.industryFieldId;
  frameDisplayName.value = card.displayName;
  showFrame.value = true;
}

async function onCompanyChange(companyId: number) {
  frameFieldId.value = null;
  frameDisplayName.value = "";
  if (!companyId) {
    companyFields.value = [];
    return;
  }
  try {
    companyFields.value = (await getCompanyIndustryFields(props.cid, companyId)) || [];
  } catch (err) {
    companyFields.value = [];
    ElMessage.error(errorMessage(err, "产业字段加载失败"));
  }
}

function onFieldChange(fieldId: number) {
  const f = companyFields.value.find((x) => x.id === fieldId);
  if (f && !editingCard.value) frameDisplayName.value = f.name;
}

async function saveFrame() {
  if (!activeRegion.value) return;
  if (!frameCompanyId.value || !frameFieldId.value || !frameDisplayName.value.trim()) {
    ElMessage.warning("请完整填写公司、产业字段与展示名称");
    return;
  }
  saving.value = true;
  try {
    const cards = activeRegion.value.cards || [];
    const newCard: RegionOverviewCard = {
      id:
        editingCard.value?.id ||
        `c-${Date.now()}-${Math.floor(Math.random() * 1000)}`,
      displayName: frameDisplayName.value.trim(),
      companyId: frameCompanyId.value,
      industryFieldId: frameFieldId.value,
      zone: frameZone.value,
    };
    let next: RegionOverviewCard[];
    if (editingCard.value) {
      next = cards.map((c) => (c.id === editingCard.value?.id ? newCard : toCardPayload(c)));
    } else {
      next = [...cards.map((c) => toCardPayload(c)), newCard];
    }
    await saveRegionCardsByName(props.cid, activeRegion.value.region, next);
    // 重新拉取区域总览（实时值需服务端重算）
    await loadRegions();
    ElMessage.success("已保存");
    showFrame.value = false;
  } catch (err) {
    ElMessage.error(errorMessage(err, "保存失败"));
  } finally {
    saving.value = false;
  }
}

async function removeFrame(region: RegionMapOverview, card: RegionOverviewCard) {
  try {
    await ElMessageBox.confirm(`移除数据框「${card.displayName}」？`, { type: "warning" });
  } catch {
    return; // 用户取消
  }
  try {
    const next = (region.cards || [])
      .filter((c) => c.id !== card.id)
      .map((c) => toCardPayload(c));
    await saveRegionCardsByName(props.cid, region.region, next);
    await loadRegions();
    ElMessage.success("已移除");
  } catch (err) {
    ElMessage.error(errorMessage(err, "移除失败"));
  }
}

// ===== 消费者需求 =====
function openAddDemand(region: RegionMapOverview) {
  if (!props.cid) return;
  activeRegion.value = region;
  editingDemand.value = null;
  demandForm.value = { productId: null, quantity: 0, note: "" };
  showDemand.value = true;
}

function openEditDemand(region: RegionMapOverview, d: ConsumerDemandItem) {
  activeRegion.value = region;
  editingDemand.value = d;
  demandForm.value = {
    productId: d.productId ?? null,
    quantity: d.quantity ?? 0,
    note: d.note || "",
  };
  showDemand.value = true;
}

async function saveDemand() {
  if (!activeRegion.value) return;
  if (demandForm.value.productId == null) {
    ElMessage.warning("请选择产品");
    return;
  }
  savingDemand.value = true;
  try {
    const payload = {
      region: activeRegion.value.region,
      productId: demandForm.value.productId as number,
      // BigNumberInput 回传数字字符串（大数不丢精度）；清空时按 0 处理，
      // 否则空字符串会被后端判为非法整数。
      quantity: demandForm.value.quantity === "" ? 0 : demandForm.value.quantity ?? 0,
      // 始终携带 note 字段：清空备注时传空字符串而非 undefined，
      // 否则请求体里会丢字段，导致后端 update 不清除备注（备注无法删除）。
      note: (demandForm.value.note ?? "").trim(),
    };
    if (editingDemand.value) {
      await updateConsumerDemand(props.cid, editingDemand.value.id, payload);
    } else {
      await createConsumerDemand(props.cid, payload);
    }
    await loadDemands();
    ElMessage.success("已保存");
    showDemand.value = false;
  } catch (err) {
    ElMessage.error(errorMessage(err, "保存失败"));
  } finally {
    savingDemand.value = false;
  }
}

async function removeDemand(_region: RegionMapOverview, d: ConsumerDemandItem) {
  try {
    await ElMessageBox.confirm(`删除需求「${d.productName}（${d.quantity} 件）」？`, {
      type: "warning",
    });
  } catch {
    return; // 用户取消
  }
  try {
    await deleteConsumerDemand(props.cid, d.id);
    await loadDemands();
    ElMessage.success("已删除");
  } catch (err) {
    ElMessage.error(errorMessage(err, "删除失败"));
  }
}

function formatValue(card: RegionOverviewCard) {
  if (card.valid === false) return "字段已失效";
  const v = card.value;
  if (v == null || v === "") return "—";
  if (card.fieldType === "BOOL" || card.fieldType === "BOOLEAN") {
    return v === true || v === "true" || v === 1 ? "是" : "否";
  }
  if (card.fieldType === "NUMBER") return String(v);
  if (card.fieldType === "DICTIONARY" || card.fieldType === "LIST") {
    try {
      return JSON.stringify(JSON.parse(String(v)));
    } catch {
      return String(v);
    }
  }
  return String(v);
}

// 重拉本页全部数据（区域带 + 消费者需求 + 产品下拉）
async function reloadAll() {
  if (!props.cid) {
    regions.value = [];
    demands.value = [];
    productOptions.value = [];
    return;
  }
  await Promise.all([loadRegions(), loadDemands(), loadProducts()]);
}

// 手动刷新所有数据
async function refreshAll() {
  await reloadAll();
  ElMessage.success("数据已刷新");
}

// 切换比赛时重新拉取：先清空本地数据，等网络确认后再渲染，避免停留在上一个比赛的旧数据（错误内容）。
watch(
  () => props.cid,
  (newId, oldId) => {
    if (newId !== oldId) {
      regions.value = [];
      demands.value = [];
      productOptions.value = [];
      companyFields.value = [];
      regionCompanies.value = [];
      activeRegion.value = null;
      editingCard.value = null;
      editingDemand.value = null;
      showFrame.value = false;
      showDemand.value = false;
    }
    void reloadAll();
  },
  { immediate: true },
);

// 资源变更广播（400ms 去抖合并）：区域/需求/公司/合同/基础数据/地图节点任一变更后自动重拉
useResourceRefresh(
  ["regions", "consumer-demands", "companies", "contracts", "basedata", "map_nodes"],
  () => {
    void reloadAll();
  },
);
</script>

<style scoped>
.region-overview {
}
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}
.page-title {
  font-size: 20px;
  font-weight: 600;
  color: var(--color-text-primary, #1f1f1f);
  margin: 0;
}
.no-comp-warning {
  text-align: center;
  padding: 12px;
  margin-bottom: 12px;
  background: var(--color-warning-soft);
  border: 1px solid rgba(var(--color-warning-soft-rgb), 0.3);
  border-radius: 6px;
  color: #b45309;
  font-size: 13px;
}

/* 区域条：条与条之间统一留白，入场错峰 */
.region-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.region-band {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-md);
  padding: 16px 18px;
  box-shadow: var(--shadow-xs);
  transition:
    border-color var(--dur-base) var(--ease-standard),
    box-shadow var(--dur-base) var(--ease-out-expo);
}
.region-band:hover {
  border-color: var(--color-border-strong);
  box-shadow: var(--shadow-sm);
}
/* 区域标题独立成一条：与下方内容之间有明确分隔 */
.band-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--color-border);
}
.band-title {
  display: flex;
  align-items: baseline;
  gap: 10px;
}
.band-name {
  font-size: 17px;
  font-weight: 700;
  color: var(--color-text-primary);
  letter-spacing: -0.01em;
}

/* 大框内的两个分区：上=消费者需求，下=区域数据 */
.band-section {
  padding: 12px 0;
  border-top: 1px dashed var(--color-border);
}
/* 紧跟区域标题的第一段不再重复画分隔线 */
.band-header + .band-section {
  border-top: none;
  padding-top: 4px;
}
.section-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}
.section-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
.section-title {
  display: flex;
  align-items: center;
  margin-bottom: 0;
  font-size: var(--font-sm);
  font-weight: 600;
  color: var(--color-text-secondary);
  letter-spacing: 0.3px;
}
.section-title::before {
  content: "";
  display: inline-block;
  width: 3px;
  height: 12px;
  background: var(--color-text-tertiary);
  border-radius: 2px;
  margin-right: 7px;
}
/* 「消费者需求」用绿色语义、「区域数据」用蓝色语义，与下方卡片配色呼应 */
.band-header + .band-section .section-title::before {
  background: var(--color-success);
}
.band-section + .band-section .section-title::before {
  background: rgb(var(--color-info-soft-rgb));
}
.band-empty {
  font-size: var(--font-sm);
  color: var(--color-text-tertiary);
  padding: 16px 14px;
  background: var(--color-surface-2);
  border: 1px dashed var(--color-border);
  border-radius: var(--radius-sm);
}
.ro-loading {
  padding: 4px 0;
}
.ro-skeleton {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.ro-skeleton-band {
  height: 200px;
  border-radius: var(--radius-md);
}
.ro-loading-text {
  margin-top: 12px;
  text-align: center;
  color: var(--color-text-tertiary);
  font-size: var(--font-sm);
}
.band-frames {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

/* 区域数据框（蓝） */
.frame {
  min-width: 180px;
  flex: 0 0 auto;
  background: linear-gradient(180deg, #f7f9ff 0%, #eef3ff 100%);
  border: 1px solid #d6e2ff;
  border-radius: var(--radius-sm);
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  box-shadow: var(--shadow-xs);
}
.frame.invalid {
  background: #fafafa;
  border-color: #e4e7ed;
}
/* 悬停时保留蓝色/绿色语义边（hover-lift 默认会把边框改成灰色） */
.frame.hover-lift:hover {
  border-color: #d6e2ff;
}
.frame.invalid.hover-lift:hover {
  border-color: #e4e7ed;
}

/* 消费者需求框（绿，与数据框区分） */
.demand-frame {
  background: linear-gradient(180deg, #f0faf5 0%, #e6f7ef 100%);
  border-color: #c8ecd9;
}
.demand-frame .frame-value {
  color: #1a7f4f;
}
.demand-frame.hover-lift:hover {
  border-color: #c8ecd9;
}
.demand-frame.invalid {
  background: #fafafa;
  border-color: #e4e7ed;
}

.frame-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.frame-name {
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 130px;
}
.frame-actions {
  display: flex;
  gap: 2px;
  flex-shrink: 0;
}
.fa-edit,
.fa-del {
  cursor: pointer;
  font-size: 14px;
  color: var(--color-text-tertiary);
  padding: 3px;
  border-radius: 50%;
  transition:
    background-color var(--dur-fast) var(--ease-standard),
    color var(--dur-fast) var(--ease-standard);
}
.fa-edit:hover {
  color: var(--color-primary);
  background: rgba(var(--color-primary-rgb), 0.1);
}
.demand-frame .fa-edit:hover {
  color: var(--color-success);
  background: rgba(var(--color-success-soft-rgb), 0.14);
}
.fa-del:hover {
  color: var(--color-danger);
  background: rgba(var(--color-danger-soft-rgb), 0.14);
}
/* 数值是这块卡的主角：更大、等宽数字 */
.frame-value {
  font-size: 26px;
  font-weight: 700;
  color: var(--color-text-primary);
  line-height: 1.15;
  word-break: break-all;
}
.frame-unit {
  font-size: var(--font-xs);
  font-weight: 500;
  color: var(--color-text-tertiary);
}
.frame.invalid .frame-value {
  font-size: var(--font-sm);
  font-weight: 500;
  color: var(--color-text-tertiary);
}
.frame-meta {
  font-size: 12px;
  color: var(--color-text-tertiary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
