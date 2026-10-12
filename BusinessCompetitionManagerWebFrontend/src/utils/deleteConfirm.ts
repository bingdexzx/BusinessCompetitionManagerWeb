import { ElMessageBox } from "element-plus";

export interface DeleteImpactItem {
  label: string;
  count: number;
}

/** impact.refs 条目：{ kind, label, count }（label 已可读） */
export interface DeleteImpactRef extends DeleteImpactItem {
  kind?: string;
}

export interface DeleteImpact {
  name?: string;
  /**
   * 新契约 GET .../impact：
   * - removable=false：存在外部引用，禁止删除（弹窗列出 refs 后阻断）
   * - removable=true 且 refs 非空：refs 为自身级联子配置，需确认级联删除
   * - removable=true 且 refs 空：普通删除确认
   */
  removable?: boolean;
  refs?: DeleteImpactRef[];
  /** 旧字段（children）兼容保留 */
  children?: DeleteImpactItem[];
}

/**
 * 删除前的二次确认。
 * - 数据被外部引用（impact.removable === false）：弹窗列出引用并**阻断删除**。
 * - 存在级联子数据（refs/children 有计数）：展示危险提示并逐项列出
 *   将被级联删除的关联数据条数，要求用户显式确认级联删除。
 * - 无级联子数据时仅做普通删除确认。
 *
 * 确认通过则 resolve；用户取消 / 被阻断时 reject（调用方按取消处理，不执行删除）。
 *
 * @param name   数据名称（用于提示文案）
 * @param impact 后端返回的级联影响信息（GET .../impact），失败或为空时按普通删除处理
 */
export async function confirmDeleteWithImpact(
  name: string,
  impact?: DeleteImpact | null,
  options?: { baseMessage?: string; confirmText?: string },
): Promise<void> {
  // 新契约 refs 优先，兼容旧 children 字段
  const refs = impact?.refs || impact?.children || [];

  // 1) 被外部引用 → 不可删除：列出引用并阻断（reject 使调用方走取消分支）
  if (impact && impact.removable === false) {
    const lines =
      refs
        .filter((c) => (c.count || 0) > 0)
        .map((c) => `• ${c.label}：${c.count} 条`)
        .join("<br/>") || "• 未知引用";
    const msg =
      `「<b>${name}</b>」正在被以下数据引用，<b>无法删除</b>：<br/><br/>` +
      `${lines}<br/><br/>请先解除引用后重试。`;
    await ElMessageBox.alert(msg, "无法删除", {
      type: "warning",
      dangerouslyUseHTMLString: true,
      confirmButtonText: "知道了",
    });
    return Promise.reject(new Error("该数据被引用，无法删除"));
  }

  // 2) 自身级联子配置 → 级联删除警告
  const total = refs.reduce((sum, c) => sum + (c.count || 0), 0);
  if (total > 0) {
    const lines = refs
      .filter((c) => (c.count || 0) > 0)
      .map((c) => `• ${c.label}：${c.count} 条`)
      .join("<br/>");
    const msg =
      `删除「<b>${name}</b>」将<b>级联删除</b>以下关联数据，且不可恢复：<br/><br/>` +
      `${lines}<br/><br/>确定继续删除吗？`;
    await ElMessageBox.confirm(msg, "级联删除警告", {
      type: "warning",
      dangerouslyUseHTMLString: true,
      confirmButtonText: options?.confirmText || "确认级联删除",
      cancelButtonText: "取消",
    });
    return;
  }

  // 3) 普通删除确认
  const msg = options?.baseMessage || `确定删除「${name}」？删除后不可恢复。`;
  await ElMessageBox.confirm(msg, "确认删除", { type: "warning" });
}
