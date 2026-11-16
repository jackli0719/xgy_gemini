<!--
  平台侧结算确认页（PLAT-03）。

  三件事：
  1. 打开页面拉结算单列表（全平台，可按状态 / 服务商筛）；
  2. 筛选栏：状态 / 服务商——筛选是查询条件，不是隔离边界；
  3. 待结算的行上点「确认结算」-> 调确认接口 -> 刷新列表。

  **看与确认是两件事**：
  - 列表接口（GET /api/v1/platform/settlements）平台财务与平台管理员都能看
    ——管理员要能对账、核查服务商的结算情况；
  - 确认接口（POST /api/v1/settlements/{id}/confirm，T-11b 做的那条）
    **只认平台财务**：后端按 token 里的 role 判，其他角色一律 403。

  所以平台管理员进这页能看到列表，但**看不到「确认结算」按钮**
  （前端不给点，后端也拦得住——两边都堵，才不会出现「点了才知道不行」）。
  非财务角色看到的待结算行写「仅财务可确认」。

  筛选条件变了就回到第一页重新拉（否则会停在不存在的页码上）。
-->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import {
  ElButton,
  ElOption,
  ElPagination,
  ElSelect,
  ElTable,
  ElTableColumn,
  ElTag,
  vLoading,
} from "element-plus";
import { ApiError, type Schemas } from "@oto/shared/api";

import { api } from "@/api";
import { useSessionStore } from "@/stores/session";
import { formatDateTime } from "@/utils/date";

type PlatformSettlementItem = Schemas["PlatformSettlementItem"];
type SettlementStatus = PlatformSettlementItem["status"];

const session = useSessionStore();

/**
 * 能不能点「确认结算」：**只有平台财务**。
 *
 * 后端确认接口只放 PLATFORM_FINANCE（钱相关的写动作），
 * 前端跟着收窄——管理员能看见列表，但对没有权限的动作不给按钮。
 */
const canConfirm = computed(() => session.isPlatformFinance);

/** 结算单状态 -> 中文文案与 tag 颜色。 */
const STATUS_TEXT: Record<SettlementStatus, string> = {
  PENDING: "待结算",
  CONFIRMED: "已确认",
};

const STATUS_TAG_TYPE: Record<
  SettlementStatus,
  "primary" | "success" | "info" | "warning" | "danger"
> = {
  PENDING: "warning",
  CONFIRMED: "success",
};

/** 筛选项的取值：空字符串表示「不限」。 */
const statusFilter = ref<string>("");
const providerFilter = ref<number | undefined>(undefined);

const settlements = ref<PlatformSettlementItem[]>([]);
const providers = ref<{ id: number; name: string }[]>([]);
const total = ref(0);
const page = ref(1);
const limit = ref(20);
const loading = ref(false);
const errorText = ref("");

/** 正在确认中的结算单 id：用来禁用这一行的按钮，防重复提交。 */
const confirmingId = ref<number | null>(null);

function statusText(status: SettlementStatus): string {
  return STATUS_TEXT[status];
}

function statusTagType(status: SettlementStatus) {
  return STATUS_TAG_TYPE[status];
}

/** 结算周期：起止日期都带出来（服务端给的就是 YYYY-MM-DD）。 */
function periodText(row: PlatformSettlementItem): string {
  return `${row.period_start} ~ ${row.period_end}`;
}

/** 拉结算单列表。筛选或翻页变了都走这里。 */
async function load(): Promise<void> {
  loading.value = true;
  errorText.value = "";
  try {
    const result = await api.listPlatformSettlements({
      status: (statusFilter.value || undefined) as SettlementStatus | undefined,
      provider_id: providerFilter.value,
      page: page.value,
      limit: limit.value,
    });
    settlements.value = result.items;
    total.value = result.total;
    providers.value = result.providers ?? [];
  } catch (err) {
    errorText.value = err instanceof ApiError ? err.detail : "加载失败，请稍后再试";
  } finally {
    loading.value = false;
  }
}

// 筛选变了：回到第一页重新拉。
//
// 不用 watch 之外的写法（@change）是刻意的：@change 只在**用户操作**时触发，
// 程序里改筛选条件不会触发；watch 两种情况都覆盖。
watch([statusFilter, providerFilter], () => {
  page.value = 1;
  void load();
});

function onPageChange(next: number): void {
  page.value = next;
  void load();
}

/**
 * 确认结算：调 T-11b 的确认接口，成功后刷新列表。
 *
 * 失败（比如这张单刚被别人确认了，服务端回 404）时把服务端的话显示出来，
 * 并刷新一次列表——列表里的状态才是真的。
 *
 * **顺序有讲究**：先刷新、后报错。刷新会清掉页面上的错误提示
 * （load() 开头就重置 errorText），反过来写错误就等于没写。
 */
async function confirmSettlement(row: PlatformSettlementItem): Promise<void> {
  confirmingId.value = row.id;
  let message = "";
  try {
    await api.confirmSettlement({ settlement_id: row.id });
  } catch (err) {
    message = err instanceof ApiError ? err.detail : "确认失败，请稍后再试";
  } finally {
    confirmingId.value = null;
  }
  // 成功与失败都要刷新：失败时这张单可能刚被别人确认掉了
  await load();
  errorText.value = message;
}

onMounted(() => {
  void load();
});
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2 class="page-title">结算确认</h2>
    </div>

    <div class="filter-bar">
      <div data-test="status-filter">
        <el-select v-model="statusFilter" placeholder="全部状态" clearable>
          <el-option
            v-for="(text, value) in STATUS_TEXT"
            :key="value"
            :label="text"
            :value="value"
          />
        </el-select>
      </div>
      <div data-test="provider-filter">
        <el-select
          v-model="providerFilter"
          placeholder="全部服务商"
          clearable
        >
          <el-option
            v-for="provider in providers"
            :key="provider.id"
            :label="provider.name"
            :value="provider.id"
          />
        </el-select>
      </div>
    </div>

    <p v-if="errorText" class="error-text" data-test="error">{{ errorText }}</p>

    <el-table v-loading="loading" :data="settlements" border stripe>
      <el-table-column prop="provider_name" label="服务商" min-width="140" />
      <el-table-column label="周期" min-width="180">
        <template #default="{ row }">
          {{ periodText(row as PlatformSettlementItem) }}
        </template>
      </el-table-column>
      <el-table-column prop="total_amount" label="合计" width="110" align="right" />
      <el-table-column
        prop="commission_amount"
        label="佣金"
        width="110"
        align="right"
      />
      <el-table-column prop="net_amount" label="实收" width="110" align="right" />
      <el-table-column label="状态" width="100" align="center">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)">
            {{ statusText(row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" min-width="150">
        <template #default="{ row }">
          <!--
            三个分支：
            1. 待结算 + 财务 -> 给「确认结算」按钮；
            2. 待结算 + 非财务 -> 不给按钮，写明「仅财务可确认」
               （后端确认接口也只放财务，这里只是不让人白点一次）；
            3. 已确认 -> 显示确认时间。
          -->
          <el-button
            v-if="row.status === 'PENDING' && canConfirm"
            type="primary"
            size="small"
            data-test="confirm-button"
            :loading="confirmingId === row.id"
            @click="confirmSettlement(row as PlatformSettlementItem)"
          >
            确认结算
          </el-button>
          <span v-else-if="row.status === 'PENDING'" data-test="finance-only-hint">
            仅财务可确认
          </span>
          <span v-else data-test="confirmed-at">
            {{ row.confirmed_at ? formatDateTime(row.confirmed_at) : "—" }}
          </span>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      class="pager"
      layout="total, prev, pager, next"
      :total="total"
      :current-page="page"
      :page-size="limit"
      @current-change="onPageChange"
    />
  </div>
</template>

<style scoped>
.filter-bar {
  display: flex;
  gap: 12px;
  margin-bottom: 12px;
}

.pager {
  margin-top: 12px;
}
</style>
