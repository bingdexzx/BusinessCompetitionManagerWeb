// 后端接口调用（全部走相对路径 /api/...，开发期由 vite proxy 转发；契约见 docs/API契约.md）
import { http, request } from './client'
import type {
  AdminDevice,
  AssignMemberPayload,
  AuditLogItem,
  AwardCandidate,
  AwardGrant,
  AwardGrantPayload,
  AwardGrantResult,
  AwardInfo,
  AwardRecord,
  BasedataPage,
  BasedataRow,
  BasedataTable,
  Company,
  CompanyTable,
  Competition,
  CompetitionMember,
  CompetitionMetaPayload,
  Contract,
  ContractEffect,
  ContractSyncPage,
  ContractListPage,
  ContractLedger,
  ContractType,
  CreateCompetitionPayload,
  CreateContractPayload,
  CreateInvitePayload,
  CreateSchoolPayload,
  CreateTeamPayload,
  FieldLogPage,
  FieldLogQuery,
  FiscalYear,
  FiscalYearBackup,
  InviteCode,
  InviteRedeemResult,
  LoginResponse,
  MedalAsset,
  AddressBook,
  InmailMessage,
  InmailPage,
  IndustryOption,
  SendInmailPayload,
  MyDevice,
  NetworkLogPage,
  NetworkLogQuery,
  PackageRecord,
  PlaceStockOrderPayload,
  PluginKind,
  PluginRecord,
  RefreshResponse,
  RegisterPayload,
  School,
  ScoringConfig,
  SettlementConfigPayload,
  SettlementResult,
  Stock,
  StockAccount,
  StockAdmin,
  StockBook,
  StockCandle,
  StockMarketOverview,
  StockOrder,
  StockOrderPage,
  StockOrderStatus,
  StockPage,
  StockRoundAdvanceResult,
  StockSyncPage,
  Team,
  TeamJoinCode,
  UpdateMePayload,
  UpdateMemberPayload,
  User,
} from './types'

// ---------- 认证 ----------

export function login(username: string, password: string): Promise<LoginResponse> {
  return http.post<LoginResponse>(
    '/auth/login',
    { username, password },
    { skipAuth: true, skipRefresh: true },
  )
}

export function register(payload: RegisterPayload): Promise<User> {
  return http.post<User>('/auth/register', payload, { skipAuth: true, skipRefresh: true })
}

export function refresh(refreshToken: string): Promise<RefreshResponse> {
  return http.post<RefreshResponse>(
    '/auth/refresh',
    { refresh: refreshToken },
    { skipAuth: true, skipRefresh: true },
  )
}

// ---------- 个人 ----------

export function getMe(): Promise<User> {
  return http.get<User>('/me')
}

export function updateMe(payload: UpdateMePayload): Promise<User> {
  return http.patch<User>('/me', payload)
}

export function getMyDevices(): Promise<MyDevice[]> {
  return http.get<MyDevice[]>('/me/devices')
}

/** 修改密码（旧密码校验；成功后后端顶号，需重新登录） */
export function changePassword(
  oldPassword: string,
  newPassword: string,
): Promise<{ ok: boolean; message: string }> {
  return http.post<{ ok: boolean; message: string }>('/auth/change-password', {
    oldPassword,
    newPassword,
  })
}

/** 服务端版本（版本硬封锁比对用） */
export function fetchVersion(): Promise<{ version: string }> {
  return http.get<{ version: string }>('/version', { skipAuth: true, skipRefresh: true })
}

export function getMyAwards(): Promise<AwardRecord[]> {
  return http.get<AwardRecord[]>('/me/awards')
}

export function getMyMedals(): Promise<MedalAsset[]> {
  return http.get<MedalAsset[]>('/me/medals')
}

export function getMedal(id: number): Promise<MedalAsset> {
  return http.get<MedalAsset>(`/me/medals/${id}`)
}

export function getMyMessages(): Promise<InmailPage> {
  return http.get<InmailPage>('/messages')
}

// ---------- 站内信（系统级，独立于比赛） ----------

/** 收件箱（站内信/公告/系统通知统一收件箱，可筛未读/类型） */
export function getInbox(
  query: { unread?: boolean; kind?: string; limit?: number; offset?: number } = {},
): Promise<InmailPage> {
  return http.get<InmailPage>('/messages', {
    query: {
      unread: query.unread ? 1 : undefined,
      kind: query.kind,
      limit: query.limit,
      offset: query.offset,
    },
  })
}

/** 我发送的站内信 */
export function getSentInmails(): Promise<InmailMessage[]> {
  return http.get<InmailMessage[]>('/messages/sent')
}

/** 发送站内信：收件人为「比赛（全员）+ 个人」混合多选；按比赛批量（公告）仅超管 */
export function sendInmail(payload: SendInmailPayload): Promise<InmailMessage> {
  return http.post<InmailMessage>('/messages/send', payload)
}

/** 标记已读（按收件人记录 id） */
export function readInmail(recipientId: number): Promise<{ ok: boolean }> {
  return http.post<{ ok: boolean }>(`/messages/${recipientId}/read`, {})
}

export function readAllInmails(): Promise<{ ok: boolean; updated: number }> {
  return http.post<{ ok: boolean; updated: number }>('/messages/read-all', {})
}

/** 收件人通讯录（多选框数据：比赛 + 个人） */
export function getAddressBook(): Promise<AddressBook> {
  return http.get<AddressBook>('/messages/address-book')
}

// ---------- 学校 ----------

export function getSchools(q?: string): Promise<School[]> {
  // 公开接口：注册页无 token 也能搜；已登录则带上 token，计入本人额度。
  // 若仍走匿名（skipAuth），所有标签页会共用「匿名按 IP」额度，几处学校搜索就会 429。
  return http.get<School[]>('/schools', { query: { q }, optionalAuth: true })
}

export function createSchool(payload: CreateSchoolPayload): Promise<School> {
  return http.post<School>('/schools', payload)
}

export function updateSchool(
  id: number,
  payload: Partial<CreateSchoolPayload>,
): Promise<School> {
  return http.patch<School>(`/schools/${id}`, payload)
}

export function deleteSchool(id: number): Promise<{ ok: boolean }> {
  return http.delete<{ ok: boolean }>(`/schools/${id}`)
}

// ---------- 比赛 ----------

export function getCompetitions(): Promise<Competition[]> {
  return http.get<Competition[]>('/competitions')
}

export function getCompetition(id: number | string): Promise<Competition> {
  return http.get<Competition>(`/competitions/${id}`)
}

export function createCompetition(payload: CreateCompetitionPayload): Promise<Competition> {
  return http.post<Competition>('/competitions', payload)
}

export function updateCompetitionMeta(
  id: number | string,
  payload: CompetitionMetaPayload,
): Promise<Competition> {
  return http.patch<Competition>(`/competitions/${id}/meta`, payload)
}

export function transitionCompetition(id: number | string, target: string): Promise<Competition> {
  return http.post<Competition>(`/competitions/${id}/transition`, { target })
}

// ---------- 比赛成员（指派超管/管理员所辖公司，系统超管） ----------

export function getCompetitionMembers(id: number | string): Promise<CompetitionMember[]> {
  return http.get<CompetitionMember[]>(`/competitions/${id}/members`)
}

export function assignCompetitionMember(
  id: number | string,
  payload: AssignMemberPayload,
): Promise<CompetitionMember> {
  return http.post<CompetitionMember>(`/competitions/${id}/members`, payload)
}

export function updateCompetitionMember(
  id: number | string,
  memberId: number,
  payload: UpdateMemberPayload,
): Promise<CompetitionMember> {
  return http.patch<CompetitionMember>(`/competitions/${id}/members/${memberId}`, payload)
}

// ---------- 组队 / 激活码（M2） ----------

export function getTeams(cid: number | string): Promise<Team[]> {
  return http.get<Team[]>(`/competitions/${cid}/teams`)
}

export function createTeam(cid: number | string, payload: CreateTeamPayload): Promise<Team> {
  return http.post<Team>(`/competitions/${cid}/teams`, payload)
}

export function getTeam(cid: number | string, tid: number): Promise<Team> {
  return http.get<Team>(`/competitions/${cid}/teams/${tid}`)
}

export function createTeamJoinCode(
  cid: number | string,
  tid: number,
  maxUses?: number,
): Promise<TeamJoinCode> {
  return http.post<TeamJoinCode>(`/competitions/${cid}/teams/${tid}/join-codes`, { maxUses })
}

export function joinTeam(cid: number | string, code: string): Promise<Team> {
  return http.post<Team>(`/competitions/${cid}/teams/join`, { code })
}

/** 管理员手动调整队伍产业（最终定夺，同步创建/更新公司） */
export function adjustTeamIndustry(
  cid: number | string,
  tid: number,
  payload: { industryFinal: string; industryChoice?: string[]; industryAdjustAccepted?: string[] },
): Promise<Team> {
  return http.patch<Team>(`/competitions/${cid}/teams/${tid}/industry`, payload)
}

/** 本比赛已导入的产业插件（分配公司时下拉用；非本比赛成员 403） */
export function getIndustries(cid: number | string): Promise<IndustryOption[]> {
  return http.get<IndustryOption[]>(`/competitions/${cid}/industries`)
}

/** 为队伍分配公司（选产业 + 填公司名称；后端创建/更新公司并绑定，队长据此获得操作权） */
export function assignTeamCompany(
  cid: number | string,
  tid: number,
  payload: { industryKey: string; companyName: string },
): Promise<Team> {
  return http.post<Team>(`/competitions/${cid}/teams/${tid}/company`, payload)
}

export function getInviteCodes(cid: number | string): Promise<InviteCode[]> {
  return http.get<InviteCode[]>(`/competitions/${cid}/invites`)
}

export function createInviteCode(
  cid: number | string,
  payload: CreateInvitePayload,
): Promise<InviteCode> {
  return http.post<InviteCode>(`/competitions/${cid}/invites`, payload)
}

export function redeemInvite(code: string): Promise<InviteRedeemResult> {
  return http.post<InviteRedeemResult>('/invites/redeem', { code })
}

// ---------- 比赛包 / 合同类型 / 插件（M1） ----------

export function importCompetitionPackage(id: number | string, file: File): Promise<PackageRecord> {
  const form = new FormData()
  form.append('file', file)
  return http.post<PackageRecord>(`/competitions/${id}/package`, form)
}

export function getCompetitionPackages(id: number | string): Promise<PackageRecord[]> {
  return http.get<PackageRecord[]>(`/competitions/${id}/packages`)
}

export function getContractTypes(id: number | string): Promise<ContractType[]> {
  return http.get<ContractType[]>(`/competitions/${id}/contract-types`)
}

export function getPlugins(kind?: PluginKind): Promise<PluginRecord[]> {
  return http.get<PluginRecord[]>('/plugins', { query: { kind } })
}

// ---------- 基础数据管理（数据管理页，契约 §6.1） ----------

/** 基础数据列表（?q&page&pageSize；行字段 camelCase，effect/inputs 等 JSON 列后台维护） */
export function getBasedata(
  cid: number | string,
  table: BasedataTable,
  params: { q?: string; page?: number; pageSize?: number } = {},
): Promise<BasedataPage> {
  return http.get<BasedataPage>(`/competitions/${cid}/basedata/${table}`, {
    query: { q: params.q, page: params.page, pageSize: params.pageSize },
  })
}

export function createBasedataRow(
  cid: number | string,
  table: BasedataTable,
  payload: Partial<BasedataRow>,
): Promise<BasedataRow> {
  return http.post<BasedataRow>(`/competitions/${cid}/basedata/${table}`, payload)
}

export function updateBasedataRow(
  cid: number | string,
  table: BasedataTable,
  id: number,
  payload: Partial<BasedataRow>,
): Promise<BasedataRow> {
  return http.patch<BasedataRow>(`/competitions/${cid}/basedata/${table}/${id}`, payload)
}

export function deleteBasedataRow(
  cid: number | string,
  table: BasedataTable,
  id: number,
): Promise<{ ok: boolean }> {
  return http.delete<{ ok: boolean }>(`/competitions/${cid}/basedata/${table}/${id}`)
}

// ---------- 合同（M3/M4） ----------

/** 合同列表（服务端分页 + 薄字段；2000+ 合同不可整表拉取） */
export function getContracts(
  cid: number | string,
  params: { page?: number; pageSize?: number; status?: string; q?: string } = {},
): Promise<ContractListPage> {
  return http.get<ContractListPage>(`/competitions/${cid}/contracts`, {
    query: { page: params.page, pageSize: params.pageSize, status: params.status, q: params.q },
  })
}

/** 合同增量同步：只拉 updatedAfter 之后变更的合同（游标用上次响应的 serverTime） */
export function syncContracts(
  cid: number | string,
  updatedAfter: string,
  limit = 500,
): Promise<ContractSyncPage> {
  return http.get<ContractSyncPage>(`/competitions/${cid}/contracts`, {
    query: { updatedAfter, limit },
  })
}

export function createContract(
  cid: number | string,
  payload: CreateContractPayload,
): Promise<Contract> {
  return http.post<Contract>(`/competitions/${cid}/contracts`, payload)
}

export function getContract(cid: number | string, id: number): Promise<Contract> {
  return http.get<Contract>(`/competitions/${cid}/contracts/${id}`)
}

export function submitContract(cid: number | string, id: number): Promise<Contract> {
  return http.post<Contract>(`/competitions/${cid}/contracts/${id}/submit`, {})
}

export function confirmContract(cid: number | string, id: number): Promise<Contract> {
  return http.post<Contract>(`/competitions/${cid}/contracts/${id}/confirm`, {})
}

export function getContractEffects(cid: number | string, id: number): Promise<ContractEffect[]> {
  return http.get<ContractEffect[]>(`/competitions/${cid}/contracts/${id}/effects`)
}

/** 资金账本链（查账）：该合同触及字段的全链——当时值（审计）+ 重演值（自动同步） */
export function getContractLedger(cid: number | string, id: number): Promise<ContractLedger> {
  return http.get<ContractLedger>(`/competitions/${cid}/contracts/${id}/ledger`)
}

export function requestContractModify(
  cid: number | string,
  id: number,
  reason: string,
): Promise<Contract> {
  return http.post<Contract>(`/competitions/${cid}/contracts/${id}/request-modify`, { reason })
}

export function reviewContractModify(
  cid: number | string,
  id: number,
  action: 'approve' | 'reject',
  note?: string,
): Promise<Contract> {
  return http.post<Contract>(`/competitions/${cid}/contracts/${id}/modify/review`, {
    action,
    note,
  })
}

export function reviewContractOtherParty(
  cid: number | string,
  id: number,
  action: 'approve' | 'reject',
  note?: string,
): Promise<Contract> {
  return http.post<Contract>(`/competitions/${cid}/contracts/${id}/modify/other-party`, {
    action,
    note,
  })
}

export function submitContractChanges(
  cid: number | string,
  id: number,
  payload: { inputs?: Record<string, unknown>; parties?: Array<{ role: string; companyId: number }> },
): Promise<Contract> {
  return http.post<Contract>(`/competitions/${cid}/contracts/${id}/modify/submit`, payload)
}

export function reviewBackfill(
  cid: number | string,
  id: number,
  action: 'approve' | 'reject',
  note?: string,
): Promise<Contract> {
  return http.post<Contract>(`/competitions/${cid}/contracts/${id}/backfill/review`, {
    action,
    note,
  })
}

// ---------- 公司 / 字段 ----------

export function getCompanies(cid: number | string): Promise<Company[]> {
  return http.get<Company[]>(`/competitions/${cid}/companies`)
}

export function getCompanyTable(
  cid: number | string,
  companyId: number,
  table: 'entity' | 'finance',
): Promise<CompanyTable> {
  return http.get<CompanyTable>(`/competitions/${cid}/companies/${companyId}/tables/${table}`)
}

export function updateCompanyField(
  cid: number | string,
  companyId: number,
  payload: { fieldKey: string; value: unknown; fiscalYearId?: number },
): Promise<{ fieldKey: string; value: unknown; version: number }> {
  return http.patch(`/competitions/${cid}/companies/${companyId}/fields`, payload)
}

// ---------- 财年 / 补录（M4） ----------

export function getFiscalYears(cid: number | string): Promise<FiscalYear[]> {
  return http.get<FiscalYear[]>(`/competitions/${cid}/fiscal-years`)
}

export function openFiscalYear(cid: number | string): Promise<FiscalYear> {
  return http.post<FiscalYear>(`/competitions/${cid}/fiscal-years/open`, {})
}

export function closeFiscalYear(cid: number | string): Promise<FiscalYear> {
  return http.post<FiscalYear>(`/competitions/${cid}/fiscal-years/close`, {})
}

export function getFiscalYearBackups(
  cid: number | string,
  fiscalYearId: number,
): Promise<FiscalYearBackup[]> {
  return http.get<FiscalYearBackup[]>(`/competitions/${cid}/fiscal-years/${fiscalYearId}/backups`)
}

// ---------- 结算 / 获奖（M5；2026-10 需求变更：结算只算分，奖项人工定义与发放） ----------

export function getSettlementConfig(cid: number | string): Promise<ScoringConfig> {
  return http.get<ScoringConfig>(`/competitions/${cid}/settlement/config`)
}

/**
 * 新增结算配置项：
 * - 评分准则 `{ kind:'criterion', name, fieldKey, aggregation, direction, weight }`
 * - 奖项定义 `{ kind:'award', name, awardKind:'INDIVIDUAL'|'COLLECTIVE', description?, medalLevel? }`
 */
export function createSettlementConfigItem(
  cid: number | string,
  payload: SettlementConfigPayload,
): Promise<{ id: number }> {
  return http.post<{ id: number }>(`/competitions/${cid}/settlement/config`, payload)
}

/** 删除评分准则 / 奖项定义（删除奖项定义会一并撤销其已有发放） */
export function deleteSettlementConfigItem(
  cid: number | string,
  kind: 'criterion' | 'award',
  id: number,
): Promise<{ ok: boolean }> {
  return http.delete<{ ok: boolean }>(`/competitions/${cid}/settlement/config/${kind}/${id}`)
}

// 兼容旧命名（同名同签名，行为完全一致）
export const getScoringConfig = getSettlementConfig
export const createScoringItem = createSettlementConfigItem
export const deleteScoringItem = deleteSettlementConfigItem

export function runSettlement(cid: number | string): Promise<{ runId: number; status: string }> {
  return http.post(`/competitions/${cid}/settlement/run`, {})
}

export function getSettlementResult(cid: number | string): Promise<SettlementResult> {
  return http.get<SettlementResult>(`/competitions/${cid}/settlement/result`)
}

// ---------- 奖项人工发放 ----------

/** 个人奖候选人：本比赛全部成员，可按用户名/显示名搜索 */
export function getAwardCandidates(
  cid: number | string,
  q?: string,
): Promise<AwardCandidate[]> {
  return http.get<AwardCandidate[]>(`/competitions/${cid}/settlement/candidates`, {
    query: { q },
  })
}

export function getAwardGrants(cid: number | string): Promise<AwardGrant[]> {
  return http.get<AwardGrant[]>(`/competitions/${cid}/awards/grants`)
}

/** 发放奖项：个人奖给 `{ awardId, userId }`；集体奖给 `{ awardId, companyId, note? }` */
export function createAwardGrant(
  cid: number | string,
  payload: AwardGrantPayload,
): Promise<AwardGrantResult> {
  return http.post<AwardGrantResult>(`/competitions/${cid}/awards/grants`, payload)
}

/** 撤销发放：removed = 回收的个人档案获奖记录条数 */
export function deleteAwardGrant(
  cid: number | string,
  id: number,
): Promise<{ ok: boolean; removed: number }> {
  return http.delete<{ ok: boolean; removed: number }>(`/competitions/${cid}/awards/grants/${id}`)
}

export function getAwards(cid: number | string): Promise<AwardInfo[]> {
  return http.get<AwardInfo[]>(`/competitions/${cid}/awards`)
}

// ---------- 日志 / 消息 / 审计（M6） ----------

export function getNetworkLogs(query: NetworkLogQuery = {}): Promise<NetworkLogPage> {
  return http.get<NetworkLogPage>('/logs/network', { query: { ...query } })
}

export function exportNetworkLogs(ids?: number[]): Promise<{ items: unknown[] }> {
  return http.post<{ items: unknown[] }>('/logs/network/export', ids ? { ids } : {})
}

export function getAdminDevices(userId?: number): Promise<AdminDevice[]> {
  return http.get<AdminDevice[]>('/logs/devices', { query: { userId } })
}

export function getFieldLogs(
  cid: number | string,
  query: FieldLogQuery = {},
): Promise<FieldLogPage> {
  return http.get<FieldLogPage>(`/competitions/${cid}/logs/fields`, { query: { ...query } })
}

export function exportFieldLogs(
  cid: number | string,
  ids?: number[],
): Promise<{ items: unknown[] }> {
  return http.post<{ items: unknown[] }>(`/competitions/${cid}/logs/fields/export`, ids ? { ids } : {})
}

export function getAuditLogs(
  cid: number | string,
  query: { actorId?: number; action?: string; limit?: number } = {},
): Promise<AuditLogItem[]> {
  return http.get<AuditLogItem[]>(`/competitions/${cid}/audit-logs`, { query: { ...query } })
}

// ---------- 股票（行情 / 交易 / 推进 / 同步，契约 docs/股票模块与同步优化.md §4） ----------

/** 分页响应归一：兼容裸数组与 { total, items } 两种形态 */
function toPage<T>(res: { total?: number; items?: T[] } | T[] | null | undefined): {
  total: number
  items: T[]
} {
  if (Array.isArray(res)) return { total: res.length, items: res }
  const items = res?.items ?? []
  return { total: typeof res?.total === 'number' ? res.total : items.length, items }
}

/** 股票列表（薄字段：code/name/currentPrice/initPrice/round/updatedAt/涨跌幅；?page&pageSize 分页） */
export async function getStocks(
  cid: number | string,
  query: { page?: number; pageSize?: number } = {},
): Promise<StockPage> {
  const res = await http.get<StockPage | Stock[]>(`/competitions/${cid}/stock/stocks`, {
    query: { ...query },
  })
  return toPage<Stock>(res)
}

/** 单股详情（含指标全字段） */
export function getStock(cid: number | string, code: string): Promise<Stock> {
  return http.get<Stock>(`/competitions/${cid}/stock/stocks/${encodeURIComponent(code)}`)
}

/** K 线（按需加载：选中股票才拉；?fromRound&limit keyset 增量，返回轮次大于 fromRound 的 K 线） */
export async function getStockCandles(
  cid: number | string,
  code: string,
  query: { fromRound?: number; limit?: number } = {},
): Promise<StockCandle[]> {
  const res = await http.get<
    | { items?: StockCandle[]; hasMore?: boolean; nextFromRound?: number }
    | { candles?: StockCandle[] }
    | StockCandle[]
  >(`/competitions/${cid}/stock/stocks/${encodeURIComponent(code)}/candles`, {
    query: { ...query },
  })
  if (Array.isArray(res)) return res
  const wrapped = res as { items?: StockCandle[]; candles?: StockCandle[] }
  return wrapped.items ?? wrapped.candles ?? []
}

/** 我的持仓 + 资金账户（owner 匹配 user 或本队公司） */
export async function getStockBook(cid: number | string): Promise<StockBook> {
  const res = await http.get<Partial<StockBook>>(`/competitions/${cid}/stock/book`)
  return { accounts: res?.accounts ?? [], holdings: res?.holdings ?? [] }
}

/** 我的委托（?status 状态筛选，分页） */
export async function getStockOrders(
  cid: number | string,
  query: { status?: string; page?: number; pageSize?: number } = {},
): Promise<StockOrderPage> {
  const res = await http.get<StockOrderPage | StockOrder[]>(`/competitions/${cid}/stock/orders`, {
    query: { ...query },
  })
  return toPage<StockOrder>(res)
}

/** 下单 {code, side, price, quantity}（校验现金/持仓） */
export function placeStockOrder(
  cid: number | string,
  payload: PlaceStockOrderPayload,
): Promise<StockOrder> {
  return http.post<StockOrder>(`/competitions/${cid}/stock/orders`, payload)
}

/** 撤单（仅 PENDING 且本人）→ 返回 { id, status }，本地按 id 合并状态 */
export function cancelStockOrder(
  cid: number | string,
  id: number,
): Promise<{ id: number; status: StockOrderStatus }> {
  return http.delete<{ id: number; status: StockOrderStatus }>(
    `/competitions/${cid}/stock/orders/${id}`,
  )
}

/** 推进轮次（超管；撮合+定价+K线，单事务） */
export function advanceStockRound(cid: number | string): Promise<StockRoundAdvanceResult> {
  return http.post<StockRoundAdvanceResult>(`/competitions/${cid}/stock/round/advance`, {})
}

/** 市场概览（轻量心跳：轮次/股票数/更新时间） */
export function getStockMarket(cid: number | string): Promise<StockMarketOverview> {
  return http.get<StockMarketOverview>(`/competitions/${cid}/stock/market`)
}

/** 股票同步：since 空 = snapshot 快照起步；带 since = delta 增量（游标永远用上一响应的 serverTime） */
export async function syncStockMarket(
  cid: number | string,
  since = '',
  limit = 500,
): Promise<StockSyncPage> {
  const res = await http.get<StockSyncPage>(`/competitions/${cid}/stock/sync`, {
    query: { since, limit },
  })
  return {
    mode: res?.mode === 'delta' ? 'delta' : 'snapshot',
    serverTime: res?.serverTime ?? '',
    round: res?.round ?? 0,
    hasMore: Boolean(res?.hasMore),
    stocks: res?.stocks ?? [],
    candles: res?.candles ?? [],
    orders: res?.orders ?? [],
    holdings: res?.holdings ?? [],
    accounts: res?.accounts ?? [],
  }
}

// ---------- 股票管理（超管：股票 / 资金账户新增·编辑·删除） ----------

/** 新增股票（code/name 必填；currentPrice 缺省 = initPrice） */
export function createStock(
  cid: number | string,
  payload: Partial<StockAdmin>,
): Promise<StockAdmin> {
  return http.post<StockAdmin>(`/competitions/${cid}/stock/stocks`, payload)
}

/** 编辑股票（按 code 定位，字段同新增） */
export function updateStock(
  cid: number | string,
  code: string,
  payload: Partial<StockAdmin>,
): Promise<StockAdmin> {
  return http.patch<StockAdmin>(
    `/competitions/${cid}/stock/stocks/${encodeURIComponent(code)}`,
    payload,
  )
}

/** 删除股票（存在委托单/持仓时后端拒绝，直接展示 message） */
export function deleteStock(cid: number | string, code: string): Promise<{ ok: boolean }> {
  return http.delete<{ ok: boolean }>(
    `/competitions/${cid}/stock/stocks/${encodeURIComponent(code)}`,
  )
}

/** 资金账户列表（{ items, total }） */
export async function getStockAccounts(
  cid: number | string,
): Promise<{ items: StockAccount[]; total: number }> {
  const res = await http.get<{ items?: StockAccount[]; total?: number } | StockAccount[]>(
    `/competitions/${cid}/stock/accounts`,
  )
  return toPage<StockAccount>(res)
}

/** 新增资金账户（name 必填；USER 必填 userId、COMPANY 必填 companyId） */
export function createStockAccount(
  cid: number | string,
  payload: Partial<StockAccount>,
): Promise<StockAccount> {
  return http.post<StockAccount>(`/competitions/${cid}/stock/accounts`, payload)
}

/** 编辑资金账户（字段同新增） */
export function updateStockAccount(
  cid: number | string,
  id: number,
  payload: Partial<StockAccount>,
): Promise<StockAccount> {
  return http.patch<StockAccount>(`/competitions/${cid}/stock/accounts/${id}`, payload)
}

/** 删除资金账户（存在委托/持仓时后端拒绝，直接展示 message） */
export function deleteStockAccount(cid: number | string, id: number): Promise<{ ok: boolean }> {
  return http.delete<{ ok: boolean }>(`/competitions/${cid}/stock/accounts/${id}`)
}

// ---------- 区域总览 / 消费者需求（区域由地图节点维护，按区域名关联） ----------

/** 总览卡片（值由服务端按公司产业字段算好；valid=false 表示公司/字段已失效） */
export interface RegionOverviewCard {
  id: string
  displayName: string
  companyId: number
  industryFieldId: number | null
  /** 所属分区：top = 上半段「消费者需求」区，bottom = 下半段「区域数据」区 */
  zone?: 'top' | 'bottom'
  /** 服务端算好的展示值（数字/字符串/布尔） */
  value?: unknown
  valid?: boolean
  /** 产业字段类型：NUMBER | TEXT | BOOL | REF | DATE（兼容旧值 BOOLEAN/STRING/DICTIONARY/LIST） */
  fieldType?: string
}

/** 地图区域总览（GET /competitions/{cid}/regions/map-overview） */
export interface RegionMapOverview {
  /** Region 实体 id；地图上已有区域名但还没保存过卡片时为 null */
  id: number | null
  /** 区域名（来自地图节点 region 字段 ∪ 已有 Region） */
  region: string
  /** 该区域内的公司（按 location 字段匹配地图节点名） */
  companies: Array<{ id: number; name: string; industryKey: string }>
  cards: RegionOverviewCard[]
}

/** 公司产业字段（GET /competitions/{cid}/companies/{pk}/industry-fields，「产业字段」下拉） */
export interface CompanyIndustryField {
  id: number
  key: string
  name: string
  fieldType: string
  /** 隐藏字段标注（旧接口带该字段；新接口可不返回） */
  visible?: boolean
}

export function getRegionMapOverview(cid: number | string): Promise<RegionMapOverview[]> {
  return http.get<RegionMapOverview[]>(`/competitions/${cid}/regions/map-overview`)
}

/** 按区域名整表替换总览卡片（body { cards }；zone ∈ 'top' | 'bottom'） */
export function saveRegionCardsByName(
  cid: number | string,
  regionName: string,
  cards: RegionOverviewCard[],
): Promise<{ success: boolean }> {
  return request<{ success: boolean }>(
    `/competitions/${cid}/regions/by-name/${encodeURIComponent(regionName)}/overview-cards`,
    { method: 'PUT', body: { cards } },
  )
}

export function getCompanyIndustryFields(
  cid: number | string,
  companyId: number,
): Promise<CompanyIndustryField[]> {
  return http.get<CompanyIndustryField[]>(
    `/competitions/${cid}/companies/${companyId}/industry-fields`,
  )
}

/** Region 实体上的总览卡片配置（区域 CRUD 遗留接口用；字段键 industryFieldKey） */
export interface RegionCardConfig {
  id?: number
  displayName: string
  companyId: number
  industryFieldKey: string
  zone?: string
}

/** Region 实体（区域已改由地图节点 region 字段维护；保留接口以兼容旧调用方） */
export interface RegionItem {
  id: number
  name: string
  description: string
  overviewCards: RegionCardConfig[]
  demandCount: number | null
  updatedAt: string
}

export interface ConsumerDemandItem {
  id: number
  /** Region 实体 id（区域仅存在于地图节点上时可为 null） */
  regionId: number | null
  /** 区域名（与地图区域总览的 region 对应；前端按它归入区域带） */
  regionName: string
  productId: number | null
  productName: string
  quantity: number
  note: string
  updatedAt: string
}

export function getRegions(cid: number | string): Promise<RegionItem[]> {
  return http.get<RegionItem[]>(`/competitions/${cid}/regions`)
}

export function createRegion(
  cid: number | string,
  payload: { name: string; description?: string },
): Promise<RegionItem> {
  return http.post<RegionItem>(`/competitions/${cid}/regions`, payload)
}

export function updateRegion(
  cid: number | string,
  id: number,
  payload: { name?: string; description?: string },
): Promise<RegionItem> {
  return http.patch<RegionItem>(`/competitions/${cid}/regions/${id}`, payload)
}

export function deleteRegion(cid: number | string, id: number): Promise<{ ok: boolean }> {
  return http.delete<{ ok: boolean }>(`/competitions/${cid}/regions/${id}`)
}

export function getOverviewCards(
  cid: number | string,
  regionId: number,
): Promise<RegionCardConfig[]> {
  return http.get<RegionCardConfig[]>(`/competitions/${cid}/regions/${regionId}/overview-cards`)
}

export function saveOverviewCards(
  cid: number | string,
  regionId: number,
  cards: RegionCardConfig[],
): Promise<RegionCardConfig[]> {
  return http.patch<RegionCardConfig[]>(
    `/competitions/${cid}/regions/${regionId}/overview-cards`,
    cards,
  )
}

export function getConsumerDemands(
  cid: number | string,
  regionId?: number,
): Promise<ConsumerDemandItem[]> {
  const query = regionId ? `?regionId=${regionId}` : ''
  return http.get<ConsumerDemandItem[]>(`/competitions/${cid}/consumer-demands${query}`)
}

export function createConsumerDemand(
  cid: number | string,
  payload: {
    /** 区域名（新版按区域名关联；区域只存在于地图节点上时用这个） */
    region?: string
    /** Region 实体 id（旧调用方兼容） */
    regionId?: number
    productId?: number
    productName?: string
    /** 大数安全：允许数字字符串（BigNumberInput 直传，避免 > 2^53 丢精度） */
    quantity: number | string
    note?: string
  },
): Promise<ConsumerDemandItem> {
  return http.post<ConsumerDemandItem>(`/competitions/${cid}/consumer-demands`, payload)
}

export function updateConsumerDemand(
  cid: number | string,
  id: number,
  payload: Partial<{
    region: string
    regionId: number
    productName: string
    productId: number
    quantity: number | string
    note: string
  }>,
): Promise<ConsumerDemandItem> {
  return http.patch<ConsumerDemandItem>(`/competitions/${cid}/consumer-demands/${id}`, payload)
}

export function deleteConsumerDemand(cid: number | string, id: number): Promise<{ ok: boolean }> {
  return http.delete<{ ok: boolean }>(`/competitions/${cid}/consumer-demands/${id}`)
}

/** 删除合同：rollback=true「删除（回滚）」（回滚落账再删）；false「不回滚删除」（仅限无落账效果） */
export function deleteContract(
  cid: number | string,
  id: number,
  rollback = true,
): Promise<{ ok: boolean; rolledBackRounds: number[] }> {
  return http.delete<{ ok: boolean; rolledBackRounds: number[] }>(
    `/competitions/${cid}/contracts/${id}?rollback=${rollback ? 1 : 0}`,
  )
}
