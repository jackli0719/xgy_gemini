<script setup lang="ts">
/**
 * 我的订单（三个工作分组：待接单 / 待服务 / 服务中）。
 *
 * 数据来自 api.listMasterOrders({ status })（GET /api/v1/master/orders）。
 * **不带 master_id**：师傅身份由服务端按 token 里的 user_id 查 master 表，
 * 前端传了也没用（后端压根没这个入参）。
 *
 * 每个分组对应后端的一种状态（MasterOrderStatus）：
 * 待接单 PENDING_ACCEPT / 已接单待开工 ACCEPTED / 服务中 IN_SERVICE。
 *
 * 动作（接单 / 拒单 / 开始服务 / 完成服务）走已有的订单动作接口
 * （POST /api/v1/orders/{order_no}/accept 等），动完**重新拉列表**——
 * 状态变了还显示旧列表，用户会点出第二次 404。
 */
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";

import { api } from "@/api";
import RejectPopup from "@/components/RejectPopup.vue";
import { ORDER_STATUS_TEXT, WORK_TABS } from "@/constants/status";
import type { components } from "@oto/shared/api";

type MasterOrderItem = components["schemas"]["MasterOrderItem"];
type MasterOrderStatus = components["schemas"]["MasterOrderStatus"];

const router = useRouter();

/** 当前选中的分组下标（van-tabs 用下标做 active）。 */
const activeTab = ref(0);
/** 每个分组一份列表：切回某个分组时显示的是它自己的数据。 */
const lists = ref<Record<string, MasterOrderItem[]>>({
  PENDING_ACCEPT: [],
  ACCEPTED: [],
  IN_SERVICE: [],
});
const loading = ref(false);
const error = ref("");
/** 动作进行中：动作按钮禁用，防止重复点。 */
const busy = ref(false);

/** 拒单弹窗 */
const rejectVisible = ref(false);
const rejectTarget = ref<MasterOrderItem | null>(null);

const activeStatus = computed<MasterOrderStatus>(
  () => WORK_TABS[activeTab.value].status,
);

onMounted(() => {
  void loadStatus(activeStatus.value);
});

// 换分组就换一份列表
watch(activeTab, () => {
  void loadStatus(activeStatus.value);
});

/** 拉某个分组的订单。 */
async function loadStatus(status: MasterOrderStatus): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const result = await api.listMasterOrders({ status });
    lists.value = { ...lists.value, [status]: result.items };
  } catch (err) {
    error.value = err instanceof Error ? err.message : "订单加载失败";
  } finally {
    loading.value = false;
  }
}

/**
 * 做一个动作，然后刷新受影响的分组。
 *
 * 动作会让订单在分组之间搬家（接单：待接单 -> 待服务），
 * 所以两个分组都要重新拉一遍，不然切过去看到的是旧列表。
 */
async function act(
  action: () => Promise<unknown>,
  affected: MasterOrderStatus[],
): Promise<void> {
  busy.value = true;
  error.value = "";
  try {
    await action();
    await Promise.all(affected.map((status) => loadStatus(status)));
  } catch (err) {
    error.value = err instanceof Error ? err.message : "操作失败";
  } finally {
    busy.value = false;
  }
}

async function accept(row: MasterOrderItem): Promise<void> {
  await act(
    () => api.acceptOrder({ order_no: row.order_no }),
    ["PENDING_ACCEPT", "ACCEPTED"],
  );
}

async function start(row: MasterOrderItem): Promise<void> {
  await act(
    () => api.startService({ order_no: row.order_no }),
    ["ACCEPTED", "IN_SERVICE"],
  );
}

async function finish(row: MasterOrderItem): Promise<void> {
  await act(() => api.finishService({ order_no: row.order_no }), ["IN_SERVICE"]);
}

function openReject(row: MasterOrderItem): void {
  rejectTarget.value = row;
  rejectVisible.value = true;
}

/** 弹窗回传了拒单原因（非空由弹窗自己校验）。 */
async function confirmReject(reason: string): Promise<void> {
  const row = rejectTarget.value;
  if (!row) return;
  rejectVisible.value = false;
  await act(() => api.rejectOrder({ order_no: row.order_no }, { reason }), [
    "PENDING_ACCEPT",
  ]);
}

function openDetail(orderNo: string): void {
  void router.push(`/orders/${orderNo}`);
}
</script>

<template>
  <div class="page">
    <van-tabs v-model:active="activeTab" data-test="work-tabs">
      <!--
        tab 不设 name：Vant 的 active 会在「有 name 时回 name、没有时回下标」
        之间切换，混着来会让 active 有时是 "PENDING_ACCEPT"、有时是 0。
        这里统一用下标（下标 -> 状态的映射在 WORK_TABS 里）。
      -->
      <van-tab v-for="tab in WORK_TABS" :key="tab.status" :title="tab.title">
        <p v-if="error" class="page-error" data-test="error">{{ error }}</p>

        <van-loading v-if="loading" size="24" data-test="loading">加载中</van-loading>

        <van-empty
          v-else-if="lists[tab.status].length === 0"
          :description="`没有${tab.title}的订单`"
        />

        <van-cell-group v-else inset>
          <template v-for="row in lists[tab.status]" :key="row.order_no">
            <van-cell
              data-test="order-item"
              is-link
              @click="openDetail(row.order_no)"
            >
              <template #title>
                <span class="item-name">{{ row.item_name }}</span>
              </template>
              <template #label>
                <span class="item-meta">
                  {{ row.order_no }} · {{ row.slot_date }} {{ row.slot_start_time }}
                </span>
              </template>
              <template #value>
                <div class="order-value">
                  <span class="order-amount">¥{{ row.amount }}</span>
                  <van-tag type="primary" plain>
                    {{ ORDER_STATUS_TEXT[row.status] }}
                  </van-tag>
                </div>
              </template>
            </van-cell>

            <!-- 操作按钮单独一行：不放在 cell 的 value 槽里，避免整行点击时误触 -->
            <div class="order-actions">
              <template v-if="row.status === 'PENDING_ACCEPT'">
                <van-button
                  size="small"
                  type="primary"
                  :loading="busy"
                  data-test="accept-btn"
                  @click.stop="accept(row)"
                >
                  接单
                </van-button>
                <van-button
                  size="small"
                  :loading="busy"
                  data-test="reject-btn"
                  @click.stop="openReject(row)"
                >
                  拒单
                </van-button>
              </template>
              <van-button
                v-else-if="row.status === 'ACCEPTED'"
                size="small"
                type="primary"
                :loading="busy"
                data-test="start-btn"
                @click.stop="start(row)"
              >
                开始服务
              </van-button>
              <van-button
                v-else-if="row.status === 'IN_SERVICE'"
                size="small"
                type="primary"
                :loading="busy"
                data-test="finish-btn"
                @click.stop="finish(row)"
              >
                完成服务
              </van-button>
            </div>
          </template>
        </van-cell-group>
      </van-tab>
    </van-tabs>

    <!-- 拒单原因弹窗：列表页与详情页共用同一个组件 -->
    <RejectPopup v-model:show="rejectVisible" @confirm="confirmReject" />
  </div>
</template>
