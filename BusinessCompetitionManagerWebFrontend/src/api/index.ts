// 全部走相对路径 /api/...（开发期由 vite proxy 转发）；契约见 docs/API契约.md
import { getAccessToken, getCompetitionId, http, request } from './client'
import type {
  AdminDevice,
  AssignMemberPayload,
  AuditLogItem,
  BackgroundJob,
  AwardCandidate,
  AwardGrant,
  AwardGrantPayload,
  AwardGrantResult,
  AwardRecord,
  BasedataPage,
  BasedataTable,
  Company,
  CompanyTable,
  Competition,
  CompetitionPermissionConfig,
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
  CreateTimerPayload,
  CompetitionTimer,
  FieldLogCompanyOption,
  FieldLogPage,
  FieldLogQuery,
  FiscalYear,
  FiscalYearBackup,
  InviteCode,
  InviteRedeemResult,
  JobKind,
  LoginResponse,
  MedalAsset,
  MyTicket,
  AddressBook,
  InmailMessage,
  InmailPage,
  IndustryFieldMeta,
  IndustryOption,
  SendInmailPayload,
  NetworkLogPage,
  NetworkLogQuery,
  PackageRecord,
  PlaceStockOrderPayload,
  PluginKind,
  PluginDryRunResult,
  PluginRecord,
  RefreshResponse,
  RegionField,
  RegisterPayload,
  School,
  ScoringConfig,
  SettlementConfigPayload,
  SettlementPreview,
  SettlementResult,
  Stock,
  StockAccount,
  StockAdmin,
  StockCandle,
  StockMarketOverview,
  StockOrder,
  StockOrderStatus,
  StockPage,
  StockRoundAdvanceResult,
  StockSyncPage,
  Team,
  TeamJoinCode,
  UpdateLog,
  UpdateLogLatest,
  UpdateMePayload,
  UpdateMemberPayload,
  User,
} from './types'

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

export function getMe(): Promise<User> {
  return http.get<User>('/me')
}

export function updateMe(payload: UpdateMePayload): Promise<User> {
  return http.patch<User>('/me', payload)
}


export function getLatestUpdateLog(): Promise<UpdateLogLatest> {
  return http.get<UpdateLogLatest>('/update-logs/latest')
}

export function markUpdateLogRead(id: number): Promise<{ seen: number }> {
  return http.post<{ seen: number }>(`/update-logs/${id}/read`)
}

export function getUpdateLogs(): Promise<UpdateLog[]> {
  return http.get<UpdateLog[]>('/update-logs')
}

export function createUpdateLog(payload: {
  version: string
  title: string
  content: string
}): Promise<UpdateLog> {
  return http.post<UpdateLog>('/update-logs', payload)
}

// 改密后后端顶号（旧 token 失效），需重新登录
export function changePassword(
  oldPassword: string,
  newPassword: string,
): Promise<{ ok: boolean; message: string }> {
  return http.post<{ ok: boolean; message: string }>('/auth/change-password', {
    oldPassword,
    newPassword,
  })
}

export function fetchVersion(): Promise<{ version: string }> {
  return http.get<{ version: string }>('/version', { skipAuth: true, skipRefresh: true })
}

/** 我的纪念票（加入比赛时定格的票面） */
export function getMyTickets(): Promise<MyTicket[]> {
  return http.get<MyTicket[]>('/me/tickets')
}

export function getMyAwards(): Promise<AwardRecord[]> {
  return http.get<AwardRecord[]>('/me/awards')
}

export function getMedal(id: number): Promise<MedalAsset> {
  return http.get<MedalAsset>(`/me/medals/${id}`)
}

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

export function getSentInmails(): Promise<InmailMessage[]> {
  return http.get<InmailMessage[]>('/messages/sent')
}

// 收件人 =「比赛全员 + 个人」混合多选；按比赛批量（公告）仅超级管理员
export function sendInmail(payload: SendInmailPayload): Promise<InmailMessage> {
  return http.post<InmailMessage>('/messages/send', payload)
}

export function readInmail(recipientId: number): Promise<{ ok: boolean }> {
  return http.post<{ ok: boolean }>(`/messages/${recipientId}/read`, {})
}

export function readAllInmails(): Promise<{ ok: boolean; updated: number }> {
  return http.post<{ ok: boolean; updated: number }>('/messages/read-all', {})
}

export function getAddressBook(): Promise<AddressBook> {
  return http.get<AddressBook>('/messages/address-book')
}

export function getSchools(q?: string): Promise<School[]> {
  // 公开接口但 optionalAuth：已登录带 token 计入本人额度；匿名则共用按 IP 额度，几处搜索易 429
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

export function getTeams(cid: number | string): Promise<Team[]> {
  return http.get<Team[]>(`/competitions/${cid}/teams`)
}

export function createTeam(cid: number | string, payload: CreateTeamPayload): Promise<Team> {
  return http.post<Team>(`/competitions/${cid}/teams`, payload)
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

export function adjustTeamIndustry(
  cid: number | string,
  tid: number,
  payload: { industryFinal: string; industryChoice?: string[]; industryAdjustAccepted?: string[] },
): Promise<Team> {
  return http.patch<Team>(`/competitions/${cid}/teams/${tid}/industry`, payload)
}

export function getIndustries(cid: number | string): Promise<IndustryOption[]> {
  return http.get<IndustryOption[]>(`/competitions/${cid}/industries`)
}

/** 产业字段元数据（字段键 → 中文名 / 类型），用于把 cash 这类键展示成中文 */
export function getIndustryFields(cid: number | string): Promise<IndustryFieldMeta[]> {
  return http.get<IndustryFieldMeta[]>(`/competitions/${cid}/industry-fields`)
}

/** 设置字段展示分组（仅系统超级管理员；分组名称必填，对本比赛全部公司生效） */
export function updateIndustryFieldGroup(
  cid: number | string,
  fieldKey: string,
  group: string,
): Promise<{ key: string; group: string }> {
  return http.patch(`/competitions/${cid}/industry-fields/${fieldKey}`, { group })
}

// 选产业 + 公司名；后端创建/更新公司并绑定，队长据此获得操作权
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

export function importCompetitionPackage(id: number | string, file: File): Promise<PackageRecord> {
  const form = new FormData()
  form.append('file', file)
  return http.post<PackageRecord>(`/competitions/${id}/package`, form)
}

/** 后台导入比赛包：立刻返回任务，导入在 worker 里跑（大包推荐） */
export function importCompetitionPackageAsync(
  id: number | string,
  file: File,
): Promise<{ job: BackgroundJob }> {
  const form = new FormData()
  form.append('file', file)
  form.append('async', '1')
  return http.post<{ job: BackgroundJob }>(`/competitions/${id}/package`, form)
}

export function getCompetitionPackages(id: number | string): Promise<PackageRecord[]> {
  return http.get<PackageRecord[]>(`/competitions/${id}/packages`)
}

export function getContractTypes(id: number | string): Promise<ContractType[]> {
  return http.get<ContractType[]>(`/competitions/${id}/contract-types`)
}

export function getPlugins(
  kind?: PluginKind,
  competitionId?: number | string,
): Promise<PluginRecord[]> {
  return http.get<PluginRecord[]>('/plugins', { query: { kind, competitionId } })
}

export function getBasedata(
  cid: number | string,
  table: BasedataTable,
  params: { q?: string; page?: number; pageSize?: number } = {},
): Promise<BasedataPage> {
  return http.get<BasedataPage>(`/competitions/${cid}/basedata/${table}`, {
    query: { q: params.q, page: params.page, pageSize: params.pageSize },
  })
}

// 服务端分页 + 薄字段；2000+ 合同不可整表拉取
export function getContracts(
  cid: number | string,
  params: { page?: number; pageSize?: number; status?: string; q?: string } = {},
): Promise<ContractListPage> {
  return http.get<ContractListPage>(`/competitions/${cid}/contracts`, {
    query: { page: params.page, pageSize: params.pageSize, status: params.status, q: params.q },
  })
}

// 只拉 updatedAfter 之后变更的合同；游标用上次响应的 serverTime
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

// 该合同触及字段的全链：当时值（审计）+ 重演值（自动同步）
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

/** 下载二进制文件（xlsx 等）：走同一个鉴权头，返回 Blob 由调用方保存 */
export async function downloadFile(
  path: string,
  payload?: Record<string, unknown>,
): Promise<Blob> {
  const response = await fetch(`/api${path}`, {
    method: payload ? 'POST' : 'GET',
    headers: {
      Authorization: `Bearer ${getAccessToken()}`,
      'X-Competition-Id': getCompetitionId(),
      ...(payload ? { 'Content-Type': 'application/json' } : {}),
    },
    body: payload ? JSON.stringify(payload) : undefined,
  })
  if (!response.ok) {
    let message = '导出失败'
    try {
      const body = await response.json()
      if (body && typeof body.message === 'string') message = body.message
    } catch {
      /* 非 JSON 响应保持默认文案 */
    }
    throw new Error(message)
  }
  return response.blob()
}

/** 下载并触发浏览器保存 */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}


export function exportFieldLogsXlsx(
  cid: number | string,
  ids: number[] = [],
): Promise<Blob> {
  return downloadFile(`/competitions/${cid}/logs/fields/export`, {
    format: 'xlsx',
    ids,
  })
}

export function terminateContract(
  cid: number | string,
  id: number,
  reason?: string,
): Promise<Contract> {
  return http.post<Contract>(`/competitions/${cid}/contracts/${id}/terminate`, { reason })
}

export function rejectContract(
  cid: number | string,
  id: number,
  reason?: string,
): Promise<Contract> {
  return http.post<Contract>(`/competitions/${cid}/contracts/${id}/reject`, { reason })
}

export function updateContractDraft(
  cid: number | string,
  id: number,
  payload: { inputs?: Record<string, unknown>; parties?: unknown[]; name?: string },
): Promise<Contract> {
  return http.patch<Contract>(`/competitions/${cid}/contracts/${id}`, payload)
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

export function getCompanies(cid: number | string): Promise<Company[]> {
  return http.get<Company[]>(`/competitions/${cid}/companies`)
}

/** 已分配公司：组队完成并分配公司后才出现（teamId 非空） */
export function getAssignedCompanies(cid: number | string): Promise<Company[]> {
  return http.get<Company[]>(`/competitions/${cid}/companies`, { query: { assigned: 1 } })
}

export function getCompanyTable(
  cid: number | string,
  companyId: number,
  table: 'entity' | 'finance',
): Promise<CompanyTable> {
  return http.get<CompanyTable>(`/competitions/${cid}/companies/${companyId}/tables/${table}`)
}

/** 手工修改公司字段值（超级管理员；后端写入字段日志；公司有合同修改中时会拒绝） */
export function updateCompanyField(
  cid: number | string,
  companyId: number,
  payload: {
    fieldKey: string
    value: unknown
    fiscalYearId?: number | null
    /** 乐观锁：带上拿到的版本，服务端并发冲突时返回 409 */
    expectedVersion?: number
  },
): Promise<{ fieldKey: string; value: unknown; version: number }> {
  return http.patch(`/competitions/${cid}/companies/${companyId}/fields`, payload)
}

export function getFiscalYears(cid: number | string): Promise<FiscalYear[]> {
  return http.get<FiscalYear[]>(`/competitions/${cid}/fiscal-years`)
}

export function getFiscalYearBackups(
  cid: number | string,
  fiscalYearId: number,
): Promise<FiscalYearBackup[]> {
  return http.get<FiscalYearBackup[]>(`/competitions/${cid}/fiscal-years/${fiscalYearId}/backups`)
}

export function getSettlementConfig(cid: number | string): Promise<ScoringConfig> {
  return http.get<ScoringConfig>(`/competitions/${cid}/settlement/config`)
}

// 新增配置项：评分准则 { kind:'criterion', name, fieldKey, aggregation, direction, weight }；奖项定义 { kind:'award', awardKind:'INDIVIDUAL'|'COLLECTIVE', ... }
export function createSettlementConfigItem(
  cid: number | string,
  payload: SettlementConfigPayload,
): Promise<{ id: number }> {
  return http.post<{ id: number }>(`/competitions/${cid}/settlement/config`, payload)
}

// 删除奖项定义会一并撤销其已发放记录
export function deleteSettlementConfigItem(
  cid: number | string,
  kind: 'criterion' | 'award',
  id: number,
): Promise<{ ok: boolean }> {
  return http.delete<{ ok: boolean }>(`/competitions/${cid}/settlement/config/${kind}/${id}`)
}

export const deleteScoringItem = deleteSettlementConfigItem

/** 提交后台任务（结算 / 财年开启结束），返回任务记录用于轮询 */
export function createJob(
  cid: number | string,
  kind: JobKind,
  payload: Record<string, unknown> = {},
): Promise<BackgroundJob> {
  return http.post<BackgroundJob>(`/competitions/${cid}/jobs`, { kind, payload })
}

export function getJob(cid: number | string, id: number): Promise<BackgroundJob> {
  return http.get<BackgroundJob>(`/competitions/${cid}/jobs/${id}`)
}

/** 轮询直到任务结束（成功/失败），返回最终状态 */
export async function waitJob(
  cid: number | string,
  id: number,
  onProgress?: (job: BackgroundJob) => void,
  options: { intervalMs?: number; timeoutMs?: number } = {},
): Promise<BackgroundJob> {
  const interval = options.intervalMs ?? 1500
  const deadline = Date.now() + (options.timeoutMs ?? 120000)
  for (;;) {
    const job = await getJob(cid, id)
    onProgress?.(job)
    if (job.status === 'SUCCESS' || job.status === 'FAILED') return job
    if (Date.now() > deadline) return job
    await new Promise((resolve) => setTimeout(resolve, interval))
  }
}

export function dryRunContractPlugin(
  cid: number | string,
  key: string,
  payload: { inputs?: Record<string, unknown>; companyIds?: number[] } = {},
): Promise<PluginDryRunResult> {
  return http.post<PluginDryRunResult>(
    `/competitions/${cid}/contracts/plugins/${encodeURIComponent(key)}/dry-run`,
    payload,
  )
}

export function getCompetitionPermissions(
  cid: number | string,
): Promise<CompetitionPermissionConfig> {
  return http.get<CompetitionPermissionConfig>(`/competitions/${cid}/permissions`)
}

export function previewSettlement(cid: number | string): Promise<SettlementPreview> {
  return http.post<SettlementPreview>(`/competitions/${cid}/settlement/preview`, {})
}

export function exportSettlement(cid: number | string): Promise<Blob> {
  return downloadFile(`/competitions/${cid}/settlement/export`)
}

export function getSettlementResult(cid: number | string): Promise<SettlementResult> {
  return http.get<SettlementResult>(`/competitions/${cid}/settlement/result`)
}

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

// 个人奖 { awardId, userId }；集体奖 { awardId, companyId, note? }
export function createAwardGrant(
  cid: number | string,
  payload: AwardGrantPayload,
): Promise<AwardGrantResult> {
  return http.post<AwardGrantResult>(`/competitions/${cid}/awards/grants`, payload)
}

// removed = 回收的个人获奖记录条数
export function deleteAwardGrant(
  cid: number | string,
  id: number,
): Promise<{ ok: boolean; removed: number }> {
  return http.delete<{ ok: boolean; removed: number }>(`/competitions/${cid}/awards/grants/${id}`)
}

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

export function getFieldLogCompanyOptions(
  cid: number | string,
): Promise<FieldLogCompanyOption[]> {
  return http.get<FieldLogCompanyOption[]>(`/competitions/${cid}/logs/fields/companies`)
}

export function exportFieldLogs(
  cid: number | string,
  ids?: number[],
): Promise<{ items: unknown[] }> {
  return http.post<{ items: unknown[] }>(`/competitions/${cid}/logs/fields/export`, ids ? { ids } : {})
}

export function getAuditLogs(
  cid: number | string,
  query: {
    actorId?: number
    actor?: string
    action?: string
    target?: string
    from?: string
    to?: string
    limit?: number
  } = {},
): Promise<AuditLogItem[]> {
  return http.get<AuditLogItem[]>(`/competitions/${cid}/audit-logs`, { query: { ...query } })
}

// 分页响应归一：兼容裸数组与 { total, items }
function toPage<T>(res: { total?: number; items?: T[] } | T[] | null | undefined): {
  total: number
  items: T[]
} {
  if (Array.isArray(res)) return { total: res.length, items: res }
  const items = res?.items ?? []
  return { total: typeof res?.total === 'number' ? res.total : items.length, items }
}

export async function getStocks(
  cid: number | string,
  query: { page?: number; pageSize?: number } = {},
): Promise<StockPage> {
  const res = await http.get<StockPage | Stock[]>(`/competitions/${cid}/stock/stocks`, {
    query: { ...query },
  })
  return toPage<Stock>(res)
}

export function getStock(cid: number | string, code: string): Promise<Stock> {
  return http.get<Stock>(`/competitions/${cid}/stock/stocks/${encodeURIComponent(code)}`)
}

// keyset 增量：?fromRound&limit，返回轮次 > fromRound 的 K 线（选中股票才拉）
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

export function placeStockOrder(
  cid: number | string,
  payload: PlaceStockOrderPayload,
): Promise<StockOrder> {
  return http.post<StockOrder>(`/competitions/${cid}/stock/orders`, payload)
}

// 仅 PENDING 且本人；本地按 id 合并状态
export function cancelStockOrder(
  cid: number | string,
  id: number,
): Promise<{ id: number; status: StockOrderStatus }> {
  return http.delete<{ id: number; status: StockOrderStatus }>(
    `/competitions/${cid}/stock/orders/${id}`,
  )
}

// 超级管理员；撮合 + 定价 + K 线，单事务
export function advanceStockRound(cid: number | string): Promise<StockRoundAdvanceResult> {
  return http.post<StockRoundAdvanceResult>(`/competitions/${cid}/stock/round/advance`, {})
}

export function getStockMarket(cid: number | string): Promise<StockMarketOverview> {
  return http.get<StockMarketOverview>(`/competitions/${cid}/stock/market`)
}

// since 空 = snapshot 快照起步；带 since = delta 增量（游标永远用上一响应的 serverTime）
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

// code/name 必填；currentPrice 缺省 = initPrice
export function createStock(
  cid: number | string,
  payload: Partial<StockAdmin>,
): Promise<StockAdmin> {
  return http.post<StockAdmin>(`/competitions/${cid}/stock/stocks`, payload)
}

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

// 有委托单/持仓时后端拒绝，直接展示 message
export function deleteStock(cid: number | string, code: string): Promise<{ ok: boolean }> {
  return http.delete<{ ok: boolean }>(
    `/competitions/${cid}/stock/stocks/${encodeURIComponent(code)}`,
  )
}

export async function getStockAccounts(
  cid: number | string,
): Promise<{ items: StockAccount[]; total: number }> {
  const res = await http.get<{ items?: StockAccount[]; total?: number } | StockAccount[]>(
    `/competitions/${cid}/stock/accounts`,
  )
  return toPage<StockAccount>(res)
}

export function createStockAccount(
  cid: number | string,
  payload: Partial<StockAccount>,
): Promise<StockAccount> {
  return http.post<StockAccount>(`/competitions/${cid}/stock/accounts`, payload)
}

export function updateStockAccount(
  cid: number | string,
  id: number,
  payload: Partial<StockAccount>,
): Promise<StockAccount> {
  return http.patch<StockAccount>(`/competitions/${cid}/stock/accounts/${id}`, payload)
}

export function deleteStockAccount(cid: number | string, id: number): Promise<{ ok: boolean }> {
  return http.delete<{ ok: boolean }>(`/competitions/${cid}/stock/accounts/${id}`)
}

// 值由服务端按公司产业字段算好；valid=false 表示公司/字段已失效
export interface RegionOverviewCard {
  id: string
  displayName: string
  companyId: number
  industryFieldId: number | null
  zone?: 'top' | 'bottom'
  value?: unknown
  valid?: boolean
  // 兼容旧值 BOOLEAN/STRING/DICTIONARY/LIST
  fieldType?: string
}

export interface RegionMapOverview {
  id: number | null
  region: string
  companies: Array<{ id: number; name: string; industryKey: string }>
  cards: RegionOverviewCard[]
}

export interface CompanyIndustryField {
  id: number
  key: string
  name: string
  fieldType: string
  visible?: boolean
}

export function getRegionMapOverview(cid: number | string): Promise<RegionMapOverview[]> {
  return http.get<RegionMapOverview[]>(`/competitions/${cid}/regions/map-overview`)
}

// 按区域名整表替换（body { cards }；zone ∈ 'top' | 'bottom'）
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

// ---------------------------------------------------------------- 区域字段

/** 某区域的全部区域字段值（定义由比赛包提供；读不到该区域时返回默认值） */
export function getRegionFieldValues(
  cid: number | string,
  regionName: string,
): Promise<RegionField[]> {
  return http.get<RegionField[]>(
    `/competitions/${cid}/regions/by-name/${encodeURIComponent(regionName)}/field-values`,
  )
}

export function setRegionFieldValue(
  cid: number | string,
  regionName: string,
  key: string,
  value: unknown,
): Promise<{ key: string; value: unknown; version: number }> {
  return http.patch(
    `/competitions/${cid}/regions/by-name/${encodeURIComponent(regionName)}/field-values/${encodeURIComponent(key)}`,
    { value },
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

export interface RegionCardConfig {
  id?: number
  displayName: string
  companyId: number
  industryFieldKey: string
  zone?: string
}

// 区域已改由地图节点 region 字段维护；接口保留仅为兼容旧调用方
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
  regionId: number | null
  regionName: string
  productId: number | null
  productName: string
  quantity: number
  note: string
  updatedAt: string
}

export function createRegion(
  cid: number | string,
  payload: { name: string; description?: string },
): Promise<RegionItem> {
  return http.post<RegionItem>(`/competitions/${cid}/regions`, payload)
}

export function deleteRegion(cid: number | string, id: number): Promise<{ ok: boolean }> {
  return http.delete<{ ok: boolean }>(`/competitions/${cid}/regions/${id}`)
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
    region?: string
    regionId?: number
    productId?: number
    productName?: string
    // 大数安全：允许数字字符串（BigNumberInput 直传，避免 > 2^53 丢精度）
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

// rollback=true「删除（回滚）」；false「不回滚删除」（仅限无落账效果）
export function deleteContract(
  cid: number | string,
  id: number,
  rollback = true,
): Promise<{ ok: boolean; rolledBackRounds: number[] }> {
  return http.delete<{ ok: boolean; rolledBackRounds: number[] }>(
    `/competitions/${cid}/contracts/${id}?rollback=${rollback ? 1 : 0}`,
  )
}

// ---------- 工具箱：计时器 ----------
export async function getTimers(cid: number | string): Promise<CompetitionTimer[]> {
  const res = await http.get<{ items: CompetitionTimer[] } | CompetitionTimer[]>(
    `/competitions/${cid}/timers`,
  )
  return Array.isArray(res) ? res : (res.items ?? [])
}

export function createTimer(
  cid: number | string,
  payload: CreateTimerPayload,
): Promise<CompetitionTimer> {
  return http.post<CompetitionTimer>(`/competitions/${cid}/timers`, payload)
}

export function deleteTimer(cid: number | string, id: number): Promise<void> {
  return http.delete<void>(`/competitions/${cid}/timers/${id}`)
}
