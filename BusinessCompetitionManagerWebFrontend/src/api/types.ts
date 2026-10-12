// 后端 API 数据结构（对齐 docs/API契约.md，camelCase）

export type MemberIdentity = 'COMP_SUPER_ADMIN' | 'ADMIN' | 'PLAYER'

export const MEMBER_IDENTITIES: MemberIdentity[] = ['COMP_SUPER_ADMIN', 'ADMIN', 'PLAYER']

export const MEMBER_IDENTITY_LABELS: Record<MemberIdentity, string> = {
  COMP_SUPER_ADMIN: '比赛超管',
  ADMIN: '管理员（主席团）',
  PLAYER: '参赛代表',
}

/** 生命周期状态链 */
export const COMPETITION_STATUS_CHAIN = [
  'CREATED',
  'PACKAGE_IMPORTED',
  'ENROLLING',
  'RUNNING',
  'SETTLING',
  'CLOSED',
] as const

/** 统一错误响应：{ code, message, details } */
export interface ApiErrorBody {
  code: number
  message: string
  details: unknown
}

// ---------- 认证 / 账号 ----------

export interface Membership {
  id: number
  competitionName: string
  competitionStatus: string
  identity: string
  identityLabel: string
  managedCompanies: number[]
}

export interface User {
  id: number
  username: string
  email: string | null
  displayName: string
  school: number | null
  schoolName: string | null
  isActive: boolean
  isSuperuser: boolean
  dateJoined: string
  memberships: Membership[]
}

export interface LoginResponse {
  access: string
  refresh: string
  user: User
}

export interface RefreshResponse {
  access: string
}

export interface RegisterPayload {
  username: string
  password: string
  email: string
  displayName?: string
  schoolId?: number | null
}

export interface UpdateMePayload {
  displayName?: string
  email?: string
  schoolId?: number | null
}

export interface MyDevice {
  id: number
  os: string
  browser: string
  screen: string
  ip: string | null
  ua: string
  firstLoginAt: string
  lastLoginAt: string
}

// ---------- 学校 / 比赛 ----------

export interface School {
  id: number
  name: string
  region: string
}

export interface CreateSchoolPayload {
  name: string
  region?: string
}

export interface Competition {
  id: number
  name: string
  code: string
  coverImage: string
  hostSchoolId: number | null
  hostSchoolName: string | null
  location: string
  staffingInfo: string
  status: string
  statusLabel: string
  dbName: string
  createdBy: number | null
  createdAt: string
}

export interface CreateCompetitionPayload {
  name: string
  code?: string
  coverImage?: string
  hostSchoolId?: number | null
  location?: string
  staffingInfo?: string
}

export type CompetitionMetaPayload = Partial<CreateCompetitionPayload>

export interface CompetitionMember {
  id: number
  userId: number
  username: string
  displayName: string
  identity: string
  identityLabel: string
  managedCompanies: number[]
  isActive: boolean
}

export interface AssignMemberPayload {
  username: string
  identity: string
  managedCompanies?: number[]
}

export interface UpdateMemberPayload {
  identity?: string
  managedCompanies?: number[]
  isActive?: boolean
}

// ---------- 组队 / 激活码 ----------

export interface TeamMemberInfo {
  userId: number
  username: string
  displayName: string
  role: string
}

export interface Team {
  id: number
  competitionId: number
  name: string
  captainId: number
  captainName: string
  industryChoice: string[]
  industryAdjustAccepted: string[]
  industryFinal: string
  companyId: number | null
  members: TeamMemberInfo[]
  createdAt: string
}

export interface CreateTeamPayload {
  name: string
  industryChoice?: string[]
  industryAdjustAccepted?: string[]
}

export interface TeamJoinCode {
  id: number
  code: string
  expiresAt: string | null
  maxUses: number
  usedCount: number
}

export interface InviteCode {
  id: number
  competitionId: number
  code: string
  identity: string
  identityLabel: string
  expiresAt: string | null
  maxUses: number
  usedCount: number
  note: string
  createdAt: string
}

export interface CreateInvitePayload {
  identity?: string
  maxUses?: number
  validDays?: number
  note?: string
}

export interface InviteRedeemResult {
  competitionId: number
  competitionName: string
  identity: string
  identityLabel: string
}

// ---------- 比赛包 / 合同类型 / 插件 ----------

export interface ImportReport {
  status: string
  startedAt: string
  finishedAt: string | null
  files: Array<{ file: string; stage: string; rows: number; errors: string[]; warnings: string[] }>
  plugins: Array<{ file: string; key: string; kind: string; version: string; sha256: string }>
  createdDatabase: string | null
  fieldMigrations: Array<{ industryKey: string; added: number; updated: number; total: number }>
  basedataRows: Record<string, number>
  contractsCreated: number
  errors: string[]
  warnings: string[]
}

export interface PackageRecord {
  id: number
  fileName: string
  sha256: string
  status: 'SUCCESS' | 'FAILED'
  report: ImportReport
  createdBy: number | null
  createdByUsername: string
  createdAt: string
}

export interface ContractType {
  key: string
  name: string
  version: string
  numberPrefix?: string
  partyRoles: Array<{ role: string; label: string; optional?: boolean }>
  inputSchema: Array<{ key: string; label: string; type: string; min?: number; required?: boolean }>
  errors?: string[]
}

export type PluginKind = 'CONTRACT' | 'INDUSTRY'

export interface PluginRecord {
  id: number
  kind: PluginKind
  key: string
  name: string
  version: string
  sha256: string
  fileName: string
  numberPrefix: string
  uploadedBy: number | null
  uploadedByUsername: string
  auditTrail: Array<{ event: string; actor: string; detail: Record<string, unknown> }>
  createdAt: string
}

// ---------- 合同 ----------

export type ContractStatus =
  | 'BACKFILL_REVIEW'
  | 'DRAFT'
  | 'PENDING_PARTY'
  | 'PENDING_EXEC'
  | 'EXECUTED'
  | 'POSTED'
  | 'MOD_APPLYING'
  | 'MOD_EDITING'
  | 'EXEC_FAILED'
  | 'CANCELLED'

export interface ContractParty {
  role: string
  companyId: number | null
  companyName: string
  confirmOrder: number
  confirmAt?: string | null
  confirmedBy?: string | null
}

export interface TimelineNode {
  type: string
  at: string
  title: string
  actor: string
  detail: string
  traceId?: string
}

export interface Contract {
  id: number
  contractTypeKey: string
  pluginVersion: string
  name: string
  status: ContractStatus
  statusLabel: string
  pendingPartyIndex: number
  parties: ContractParty[]
  inputs: Record<string, unknown>
  unifiedNumber: string
  numberedAt: string | null
  executedAt: string | null
  postedAt: string | null
  roundNo: number
  isBackfill: boolean
  fiscalYearId: number | null
  fiscalYear: number | null
  createdBy: number
  createdAt: string
  timeline?: TimelineNode[]
  /** 检查记录（§7.3 四检查点落库；修改后按轮次回放当时的检查内容） */
  checks?: ContractCheck[]
}

/** 检查记录条目（roundStatus：ACTIVE=当前生效轮次；HISTORY=历史轮次） */
export interface ContractCheck {
  id: number
  roundNo: number
  checkpoint: 'SUBMIT' | 'RECHECK' | 'MODIFY' | 'BACKFILL'
  checkpointLabel: string
  problems: string[]
  passed: boolean
  checkedBy: string
  checkedAt: string
  roundStatus: 'ACTIVE' | 'HISTORY'
  /** 检查依据快照（当时的字段值）：{"buyer": {"cash": 1000}} */
  basis?: Record<string, Record<string, unknown>>
  /** 依据重演值（账本链重算，上游合同修改后自动同步）：{"buyer": {"cash": 900}} */
  replayBasis?: Record<string, Record<string, unknown>>
}

export interface ContractEffect {
  id: number
  companyId: number
  fieldKey: string
  op: 'ADD' | 'SUB' | 'SET'
  value: unknown
  before: unknown
  after: unknown
  roundNo: number
  createdAt: string
  /** ACTIVE=当前生效轮次；ROLLED_BACK=已回滚（合同修改后旧轮效果成为审计历史） */
  roundStatus: 'ACTIVE' | 'ROLLED_BACK'
  isCurrent: boolean
  /** 重演值（按当前内容重算的链条值；与当时值不一致说明上游被修改过） */
  replayBefore?: unknown
  replayAfter?: unknown
}

/** 资金账本链节点（当时值=审计；重演值=按当前内容重算，自动同步） */
export interface LedgerNode {
  effectId: number
  contractId: number
  contractName: string
  unifiedNumber: string
  roundNo: number
  op: string
  value: unknown
  auditBefore: unknown
  auditAfter: unknown
  replayBefore: unknown
  replayAfter: unknown
}

export interface LedgerChain {
  companyId: number
  fieldKey: string
  initialValue: unknown
  currentValue: unknown
  nodes: LedgerNode[]
}

export interface ContractLedger {
  chains: LedgerChain[]
  checks: ContractCheck[]
}

export interface ContractListPage {
  items: Contract[]
  total: number
  page: number
  pageSize: number
}

export interface ContractSyncPage {
  items: Contract[]
  /** 服务端时间（下次增量游标，避免客户端时钟偏差） */
  serverTime: string
  hasMore: boolean
  mode: 'delta'
}

export interface CreateContractPayload {
  contractTypeKey: string
  pluginVersion?: string
  name?: string
  parties: Array<{ role: string; companyId: number }>
  inputs: Record<string, unknown>
  isBackfill?: boolean
  fiscalYearId?: number
}

// ---------- 公司 / 字段 ----------

export interface Company {
  id: number
  name: string
  industryKey: string
  teamId: number | null
  regionId: number | null
  status: string
}

export interface CompanyField {
  key: string
  name: string
  type: string
  isCalculated: boolean
  formula: string
  values: Record<string, unknown>
}

export interface CompanyTable {
  company: Company
  table: string
  fields: CompanyField[]
}

// ---------- 财年 ----------

export interface FiscalYear {
  id: number
  year: number
  status: 'OPEN' | 'CLOSED' | 'BACKFILL'
  statusLabel: string
  openedAt: string
  closedAt: string | null
  backupCount: number
}

export interface FiscalYearBackup {
  id: number
  companyId: number
  companyName: string
  snapshot: Record<string, unknown>
  createdAt: string
}

// ---------- 结算 / 获奖 / 奖牌 ----------

export interface ScoringCriterion {
  id: number
  name: string
  fieldKey: string
  aggregation: 'SUM' | 'LATEST' | 'AVERAGE'
  direction: 'HIGHER_BETTER' | 'LOWER_BETTER'
  weight: number
  enabled: boolean
}

export interface AwardRule {
  id: number
  awardLevel: string
  rankFrom: number
  rankTo: number
  medalLevel: string
}

export interface ScoringConfig {
  criteria: ScoringCriterion[]
  awardRules: AwardRule[]
}

export interface SettlementEntry {
  companyId: number
  companyName: string
  rank: number
  score: number
  awardLevel: string
  detail: Record<string, { value: number; normalized: number; weight: number; score: number }>
}

export interface SettlementResult {
  run: { id: number; createdAt: string; criteria: unknown[] } | null
  entries: SettlementEntry[]
}

export interface AwardInfo {
  companyId: number
  companyName: string
  rank: number
  score: number
  awardLevel: string
}

export interface AwardRecord {
  id: number
  competitionId: number
  competitionName: string
  teamName: string
  rank: number | null
  awardLevel: string
  score: number | null
  medalId: number | null
  medalName: string | null
  detail: Record<string, unknown>
  createdAt: string
}

export interface MedalAsset {
  id: number
  awardLevel: string
  displayName: string
  displayAsset: string
  meta: Record<string, unknown>
}

// ---------- 日志 / 消息 / 审计 ----------

export interface NetworkLogItem {
  id: number
  traceId: string
  occurredAt: string
  method: string
  path: string
  query: string
  status: number
  durationMs: number | null
  ip: string | null
  userId: number | null
  username: string | null
  competitionId: number | null
  deviceSnapshot: Record<string, string>
  payloadDigest: string
  responseDigest: string
}

export interface NetworkLogPage {
  total: number
  items: NetworkLogItem[]
}

export interface NetworkLogQuery {
  userId?: number
  competitionId?: number
  deviceId?: number
  traceId?: string
  status?: number
  method?: string
  path?: string
  from?: string
  to?: string
  limit?: number
  offset?: number
}

export interface AdminDevice {
  id: number
  userId: number
  username: string
  os: string
  browser: string
  screen: string
  ip: string | null
  ua: string
  firstLoginAt: string
  lastLoginAt: string
}

export interface FieldLogItem {
  id: number
  companyId: number | null
  companyName: string | null
  fieldKey: string
  dataTable: string
  event: 'VALUE_CHANGE' | 'SCHEMA_CHANGE'
  op: string
  before: unknown
  after: unknown
  source: string
  sourceLabel: string
  contractId: number | null
  roundNo: number
  operatorId: number | null
  operatorUsername: string
  deviceSnapshot: Record<string, string>
  traceId: string
  occurredAt: string
}

export interface FieldLogPage {
  total: number
  items: FieldLogItem[]
}

export interface FieldLogQuery {
  companyId?: number
  fieldKey?: string
  contractId?: number
  operatorId?: number
  source?: string
  event?: string
  traceId?: string
  from?: string
  to?: string
  limit?: number
  offset?: number
}

// ---------- 站内信（系统级，独立于比赛） ----------

export type InmailKind = 'PERSONAL' | 'ANNOUNCE' | 'SYSTEM'

export interface InmailMessage {
  id: number
  kind: InmailKind
  kindLabel: string
  title: string
  body: string
  payload: Record<string, unknown>
  competitionId: number | null
  senderId: number | null
  senderName: string
  readAt: string | null
  createdAt: string
  recipients?: Array<{ userId: number; username: string; readAt: string | null }>
}

export interface InmailPage {
  total: number
  unread: number
  items: InmailMessage[]
}

export interface SendInmailPayload {
  title: string
  body?: string
  recipientUserIds?: number[]
  competitionIds?: number[]
}

export interface AddressBook {
  competitions: Array<{ id: number; name: string; memberCount: number }>
  users: Array<{ id: number; username: string; displayName: string }>
}

export interface AuditLogItem {
  id: number
  action: string
  actorId: number | null
  actorUsername: string
  target: string
  payload: Record<string, unknown>
  traceId: string
  occurredAt: string
}

// ---------- 股票（行情 / 交易 / 增量同步，契约 docs/股票模块与同步优化.md §2/§4） ----------

/** 股票（列表/增量只带薄字段；单股详情含指标全字段）。Decimal 出站可能是数字字符串，数值运算前用 Number() 归一 */
export interface Stock {
  id: number
  code: string
  name: string
  currentPrice: number
  initPrice: number
  round: number
  /** 涨跌幅（%） */
  changePct: number
  /** 涨跌额（薄字段可选） */
  changePrice?: number
  updatedAt: string
  // ---- 单股详情（GET /stock/stocks/{code}）指标全字段 ----
  totalShares?: number
  initNetProfit?: number
  industryPE?: number
  currentCarbon?: number
  industryAvgCarbon?: number
  happiness?: number
}

/** K 线（每轮每股票一根，unique(stock, round)） */
export interface StockCandle {
  id?: number
  stockCode: string
  round: number
  open: number
  high: number
  low: number
  close: number
  changePct: number
  volume: number
  updatedAt?: string
}

export type StockOrderSide = 'BUY' | 'SELL'
export type StockOrderStatus = 'PENDING' | 'FILLED' | 'CANCELLED'

/** 委托（订单） */
export interface StockOrder {
  id: number
  stockId: number
  stockCode: string
  /** 股票名称（后端薄序列化可能不含，视图用代码兜底） */
  stockName?: string
  fundsAccountId: number
  side: StockOrderSide
  price: number
  quantity: number
  amount: number
  status: StockOrderStatus
  round: number
  createdAt: string
  updatedAt: string
}

/** 持仓 */
export interface StockHolding {
  id: number
  fundsAccountId: number
  stockId: number
  stockCode: string
  stockName: string
  /** 现价（后端序列化时可能带上） */
  currentPrice?: number | null
  shares: number
  costPrice: number
  /** 市值（后端序列化时可能带上） */
  marketValue?: number | null
  updatedAt: string
}

/** 资金账户 */
export interface StockFundsAccount {
  id: number
  name: string
  ownerType: 'COMPANY' | 'USER'
  companyId: number | null
  userId: number | null
  cashBalance: number
  bindFieldId: number | null
  /** 绑定产业字段时的实时现金（展示优先级高于 cashBalance） */
  fieldBalance?: number | null
  updatedAt: string
}

/** 市场概览（轻量心跳） */
export interface StockMarketOverview {
  round: number
  stockCount: number
  updatedAt: string
}

/** 我的持仓 + 资金账户（owner 匹配 user 或所辖公司） */
export interface StockBook {
  accounts: StockFundsAccount[]
  holdings: StockHolding[]
}

/** 下单载荷 */
export interface PlaceStockOrderPayload {
  code: string
  side: StockOrderSide
  price: number | string
  quantity: number | string
}

/** 股票分页列表（?page&pageSize） */
export interface StockPage {
  total: number
  items: Stock[]
}

/** 我的委托分页（?status&page&pageSize） */
export interface StockOrderPage {
  total: number
  items: StockOrder[]
}

/** 推进轮次结果（撮合+定价+K线，单事务；具体诊断字段由引擎返回） */
export interface StockRoundAdvanceResult {
  round?: number
  [key: string]: unknown
}

/** 股票同步响应：since 为空 = snapshot（快照起步），带 since = delta（增量游标合并） */
export interface StockSyncPage {
  mode: 'snapshot' | 'delta'
  /** 下次游标（服务端时间，规避客户端时钟偏差） */
  serverTime: string
  round: number
  hasMore: boolean
  stocks: Stock[]
  candles: StockCandle[]
  orders: StockOrder[]
  holdings: StockHolding[]
  accounts: StockFundsAccount[]
}

// ---------- 基础数据管理（数据管理页，契约 §6.1；effect/inputs 等 JSON 列后台维护） ----------

/** 基础数据表：10 类比赛级基础数据 */
export type BasedataTable =
  | 'fuels'
  | 'warehouses'
  | 'vehicles'
  | 'maps'
  | 'materials'
  | 'products'
  | 'parts'
  | 'infrastructures'
  | 'tech_trees'
  | 'production_lines'

/** 基础数据行：id + 各表可选字段（camelCase），其余列以索引签名兜底 */
export interface BasedataRow {
  id: number
  code?: string
  name?: string
  notes?: string
  unit?: string
  energyValue?: number
  price?: number
  capacity?: number
  regionCode?: string
  vehicleType?: string
  loadCapacity?: number
  speed?: number
  fuelCode?: string
  fuelConsumption?: number
  regionType?: string
  adjacentCodes?: string
  distance?: number
  basePrice?: number
  compatibleTypes?: string
  infraType?: string
  buildCost?: number
  maintenanceCost?: number
  tier?: number
  prerequisiteCodes?: string
  researchCost?: number
  [key: string]: unknown
}

/** 基础数据分页（?q&page&pageSize） */
export interface BasedataPage {
  items: BasedataRow[]
  total: number
  page: number
  pageSize: number
}
