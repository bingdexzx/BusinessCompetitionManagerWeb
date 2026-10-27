// 后端 API 数据结构（对齐 docs/API契约.md，camelCase）

export type MemberIdentity = 'COMP_SUPER_ADMIN' | 'ADMIN' | 'PLAYER'

export const MEMBER_IDENTITIES: MemberIdentity[] = ['COMP_SUPER_ADMIN', 'ADMIN', 'PLAYER']

export const MEMBER_IDENTITY_LABELS: Record<MemberIdentity, string> = {
  COMP_SUPER_ADMIN: '比赛超管',
  ADMIN: '管理员（主席团）',
  PLAYER: '参赛代表',
}

export const COMPETITION_STATUS_CHAIN = [
  'CREATED',
  'PACKAGE_IMPORTED',
  'ENROLLING',
  'RUNNING',
  'SETTLING',
  'CLOSED',
] as const

export interface ApiErrorBody {
  code: number
  message: string
  details: unknown
}

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
  companyName?: string
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
  /** 重导入去重：同类型 + 名称 + 参与方 + 输入 已存在则跳过 */
  contractsSkipped?: number
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

export interface IndustryOption {
  key: string
  name: string
  version?: string
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
  /** §7.3 四检查点落库；修改后按轮次回放当时的检查内容 */
  checks?: ContractCheck[]
}

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
  basis?: Record<string, Record<string, unknown>>
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
  /** ACTIVE=当前生效轮次；ROLLED_BACK=已回滚（旧轮效果转为审计历史） */
  roundStatus: 'ACTIVE' | 'ROLLED_BACK'
  isCurrent: boolean
  replayBefore?: unknown
  replayAfter?: unknown
}

/** 当时值=审计；重演值=按当前内容重算（上游合同修改后自动同步） */
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
  /** 下次增量游标（服务端时间，避免客户端时钟偏差） */
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

export interface ScoringCriterion {
  id: number
  name: string
  fieldKey: string
  aggregation: 'SUM' | 'LATEST' | 'AVERAGE'
  direction: 'HIGHER_BETTER' | 'LOWER_BETTER'
  weight: number
  enabled: boolean
}

/** 个人奖=1 人；集体奖=所选公司队伍全员 */
export type AwardKind = 'INDIVIDUAL' | 'COLLECTIVE'

export interface AwardDefinition {
  id: number
  name: string
  kind: AwardKind
  kindLabel: string
  description: string
  medalLevel: string | null
}

export interface ScoringConfig {
  criteria: ScoringCriterion[]
  awards: AwardDefinition[]
}

export interface SettlementEntry {
  companyId: number
  companyName: string
  rank: number
  score: number
  detail: Record<string, { value: number; normalized: number; weight: number; score: number }>
}

export interface SettlementResult {
  run: { id: number; createdAt: string; criteria: unknown[] } | null
  entries: SettlementEntry[]
}

/** kind 为配置项判别符；awardKind 才是奖项类型 */
export type SettlementConfigPayload =
  | {
      kind: 'criterion'
      name: string
      fieldKey: string
      aggregation: ScoringCriterion['aggregation']
      direction: ScoringCriterion['direction']
      weight: number
    }
  | {
      kind: 'award'
      name: string
      awardKind: AwardKind
      description?: string
      medalLevel?: string
    }

export interface AwardCandidate {
  userId: number
  username: string
  displayName: string
  companyId: number | null
  companyName: string
}

export interface AwardGrant {
  id: number
  awardId: number
  awardName: string
  kind: AwardKind
  kindLabel: string
  medalLevel: string | null
  userId: number | null
  userName: string
  companyId: number | null
  companyName: string
  recipientCount: number
  note: string
  grantedByUsername: string
  grantedAt: string
}

export type AwardGrantPayload =
  | { awardId: number; userId: number }
  | { awardId: number; companyId: number; note?: string }

export interface AwardGrantResult {
  id: number
  recipientCount: number
  recipients: Array<{ userId: number; userName: string }>
}

export interface AwardInfo {
  companyId: number
  companyName: string
  rank: number
  score: number
  awardLevel: string
}

/** 集体奖对每个受益成员各记一条 */
export interface AwardRecord {
  id: number
  competitionId: number
  competitionName: string
  teamName: string
  awardName: string
  awardKind: string
  awardKindLabel: string
  rank: number | null
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

/** 列表/增量只带薄字段；Decimal 出站可能是数字字符串，运算前用 Number() 归一 */
export interface Stock {
  id: number
  code: string
  name: string
  currentPrice: number
  initPrice: number
  round: number
  changePct: number
  changePrice?: number
  updatedAt: string
  totalShares?: number
  initNetProfit?: number
  industryPE?: number
  currentCarbon?: number
  industryAvgCarbon?: number
  happiness?: number
}

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

export interface StockOrder {
  id: number
  stockId: number
  stockCode: string
  /** 后端薄序列化可能不含名称，视图用代码兜底 */
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

export interface StockHolding {
  id: number
  fundsAccountId: number
  stockId: number
  stockCode: string
  stockName: string
  currentPrice?: number | null
  shares: number
  costPrice: number
  marketValue?: number | null
  updatedAt: string
}

export interface StockFundsAccount {
  id: number
  name: string
  ownerType: 'COMPANY' | 'USER'
  companyId: number | null
  userId: number | null
  cashBalance: number
  bindFieldId: number | null
  /** 绑定产业字段时的实时现金（优先于 cashBalance） */
  fieldBalance?: number | null
  updatedAt: string
}

export interface StockMarketOverview {
  round: number
  stockCount: number
  updatedAt: string
}

/** owner 匹配 user 或所辖公司 */
export interface StockBook {
  accounts: StockFundsAccount[]
  holdings: StockHolding[]
}

export interface PlaceStockOrderPayload {
  code: string
  side: StockOrderSide
  price: number | string
  quantity: number | string
}

export interface StockPage {
  total: number
  items: Stock[]
}

export interface StockOrderPage {
  total: number
  items: StockOrder[]
}

export interface StockRoundAdvanceResult {
  round?: number
  [key: string]: unknown
}

/** since 空 = snapshot（快照起步）；带 since = delta（游标合并） */
export interface StockSyncPage {
  mode: 'snapshot' | 'delta'
  serverTime: string
  round: number
  hasMore: boolean
  stocks: Stock[]
  candles: StockCandle[]
  orders: StockOrder[]
  holdings: StockHolding[]
  accounts: StockFundsAccount[]
}

/** POST/PATCH 与写回同名 camelCase；行业 PE 管理端为 industryPe、详情为 industryPE */
export interface StockAdmin {
  id?: number
  code: string
  name: string
  totalShares?: number | string | null
  initNetProfit?: number | string | null
  industryPe?: number | string | null
  industryPE?: number | string | null
  currentCarbon?: number | null
  industryAvgCarbon?: number | null
  happiness?: number | null
  initPrice?: number | string | null
  currentPrice?: number | string | null
  round?: number
  companyId?: number | null
  /** 与 pbFieldId 同填为联动模式，均空为随机模式 */
  pbCompanyId?: number | null
  pbFieldId?: number | null
  pbRandom?: number | null
  carbonFieldRef?: string | null
  happinessFieldRef?: string | null
  industryAvgCarbonRefs?: string | null
}

export type StockAccountOwnerType = 'USER' | 'COMPANY'

export interface StockAccount {
  id?: number
  name: string
  ownerType: StockAccountOwnerType
  userId?: number | null
  companyId?: number | null
  cashBalance?: number | string | null
  bindFieldId?: number | null
}

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

export interface BasedataPage {
  items: BasedataRow[]
  total: number
  page: number
  pageSize: number
}
