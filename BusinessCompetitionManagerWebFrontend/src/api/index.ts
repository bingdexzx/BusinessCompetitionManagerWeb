// 后端接口调用（全部走相对路径 /api/...，开发期由 vite proxy 转发；契约见 docs/API契约.md）
import { http } from './client'
import type {
  AdminDevice,
  AssignMemberPayload,
  AuditLogItem,
  AwardInfo,
  AwardRecord,
  Company,
  CompanyTable,
  Competition,
  CompetitionMember,
  CompetitionMetaPayload,
  Contract,
  ContractEffect,
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
  MessageItem,
  MyDevice,
  NetworkLogPage,
  NetworkLogQuery,
  PackageRecord,
  PluginKind,
  PluginRecord,
  RefreshResponse,
  RegisterPayload,
  School,
  ScoringConfig,
  SettlementResult,
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

export function getMyAwards(): Promise<AwardRecord[]> {
  return http.get<AwardRecord[]>('/me/awards')
}

export function getMyMedals(): Promise<MedalAsset[]> {
  return http.get<MedalAsset[]>('/me/medals')
}

export function getMedal(id: number): Promise<MedalAsset> {
  return http.get<MedalAsset>(`/me/medals/${id}`)
}

export function getMyMessages(): Promise<MessageItem[]> {
  return http.get<MessageItem[]>('/me/messages')
}

// ---------- 学校 ----------

export function getSchools(q?: string): Promise<School[]> {
  return http.get<School[]>('/schools', { query: { q }, skipAuth: true })
}

export function createSchool(payload: CreateSchoolPayload): Promise<School> {
  return http.post<School>('/schools', payload)
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

// ---------- 合同（M3/M4） ----------

export function getContracts(cid: number | string): Promise<Contract[]> {
  return http.get<Contract[]>(`/competitions/${cid}/contracts`)
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

// ---------- 结算 / 获奖（M5） ----------

export function getScoringConfig(cid: number | string): Promise<ScoringConfig> {
  return http.get<ScoringConfig>(`/competitions/${cid}/settlement/config`)
}

export function createScoringItem(
  cid: number | string,
  payload: Record<string, unknown> & { kind: 'criterion' | 'award' },
): Promise<{ id: number }> {
  return http.post<{ id: number }>(`/competitions/${cid}/settlement/config`, payload)
}

export function deleteScoringItem(
  cid: number | string,
  kind: 'criterion' | 'award',
  id: number,
): Promise<{ ok: boolean }> {
  return http.delete<{ ok: boolean }>(`/competitions/${cid}/settlement/config/${kind}/${id}`)
}

export function runSettlement(cid: number | string): Promise<{ runId: number; status: string }> {
  return http.post(`/competitions/${cid}/settlement/run`, {})
}

export function getSettlementResult(cid: number | string): Promise<SettlementResult> {
  return http.get<SettlementResult>(`/competitions/${cid}/settlement/result`)
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

export function getMessages(cid: number | string, unread?: boolean): Promise<MessageItem[]> {
  return http.get<MessageItem[]>(`/competitions/${cid}/messages`, {
    query: { unread: unread ? 1 : undefined },
  })
}

export function readMessage(cid: number | string, id: number): Promise<{ ok: boolean }> {
  return http.post<{ ok: boolean }>(`/competitions/${cid}/messages/${id}/read`, {})
}

export function getAuditLogs(
  cid: number | string,
  query: { actorId?: number; action?: string; limit?: number } = {},
): Promise<AuditLogItem[]> {
  return http.get<AuditLogItem[]>(`/competitions/${cid}/audit-logs`, { query: { ...query } })
}
