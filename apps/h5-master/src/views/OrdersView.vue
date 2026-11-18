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
 *
 * UI-M1 打磨的重点：三种页面状态**互斥**，不能同时冒出来。
 * 1. **骨架屏**：请求中显示骨架（比转圈更像「马上就有东西」）；
 * 2. **出错**：显示后端原话 + 重试按钮，不白屏；
 * 3. **空数据**：每个分组自己的文案（暂无待接单 / 暂无待服务 / 暂无服务中）。
 *
 * 每个分组一份状态（loading / error 都按分组记）：
 * 共用一份的话，「待接单」那条错误提示会跟着冒到「待服务」页签上。
 *
 * UI-M2：详情页拒单成功后跳回这里，页面顶部显示一条**一次性回执**
 * （「已拒单」）——见 utils/notice.ts。回执在 setup 里就被取走，
 * 所以用户下次再回列表不会看到残留的提示。
 *
 * **列表页拒单不写回执**：列表页拒单成功后订单会被退回待派单、
 * 直接从列表里消失，用户看得到结果（列表少了一单），不需要额外提示；
 * 详情页拒单才需要回执，因为它必须跳回列表、离开详情页。
 */
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";

import { api } from "@/api";
import RejectPopup from "@/components/RejectPopup.vue";
import { ORDER_STATUS_TEXT, WORK_TABS } from "@/constants/status";
import { errorMessage } from "@/utils/error";
import { takeNotice } from "@/utils/notice";
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

/** 一个分组当前的页面状态。 */
interface TabState {
  /** 正在拉这个分组的数据（拉的时候显示骨架屏）。 */
  loading: boolean;
  /** 拉失败时的提示（后端原话）。空串表示没出错。 */
  error: string;
}

/**
 * 每个分组一份状态。
 *
 * 初始就是 loading：Vant 的 tab 内容是懒渲染的，没点过的分组不会渲染出来，
 * 所以「一开始三个都是 loading」不会露出三张骨架屏。
 */
const states = ref<Record<string, TabState>>({
  PENDING_ACCEPT: { loading: true, error: "" },
  ACCEPTED: { loading: true, error: "" },
  IN_SERVICE: { loading: true, error: "" },
});

/** 动作进行中：动作按钮禁用，防止重复点。 */
const busy = ref(false);
/** 动作失败时的提示（后端原话）。 */
const actionError = ref("");
/** 上次失败的动作：给「重试」按钮用。 */
const retryAction = ref<(() => Promise<void>) | null>(null);

/** 拒单弹窗 */
const rejectVisible = ref(false);
const rejectTarget = ref<MasterOrderItem | null>(null);

/**
 * 一次性回执（如「已拒单」）。
 *
 * 在 setup 里就取走（不是 onMounted）：回执是一次性的，
 * 读到即清空，用户下次再回列表看不到残留。
 */
const noticeText = ref(takeNotice());

const activeStatus = computed<MasterOrderStatus>(
  () => WORK_TABS[activeTab.value].status,
);

onMounted(() => {
  void loadStatus(activeStatus.value);
});

// 换分组就换一份列表（并重新拉一次：分组里的单一直在变）
watch(activeTab, () => {
  void loadStatus(activeStatus.value);
});

/** 改某个分组的状态。 */
function setState(status: string, patch: Partial<TabState>): void {
  states.value = {
    ...states.value,
    [status]: { ...states.value[status], ...patch },
  };
}

/** 取某个分组的状态（模板里用）。 */
function stateOf(status: string): TabState {
  return states.value[status];
}

/** 拉某个分组的订单。 */
async function loadStatus(status: MasterOrderStatus): Promise<void> {
  setState(status, { loading: true, error: "" });
  try {
    const result = await api.listMasterOrders({ status });
    lists.value = { ...lists.value, [status]: result.items };
  } catch (err) {
    // 业务错显示后端原话，网络错给统一文案（见 utils/error.ts）
    setState(status, { error: errorMessage(err, "订单加载失败") });
  } finally {
    setState(status, { loading: false });
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
  // 连点守卫：光靠按钮的 loading 不够——两次点击之间 Vue 还没 patch 出
  // loading，第二次点击照样进得来（与 UI-02 的做法一致）。
  if (busy.value) return;

  busy.value = true;
  actionError.value = "";
  retryAction.value = null;
  try {
    await action();
    await Promise.all(affected.map((status) => loadStatus(status)));
  } catch (err) {
    actionError.value = errorMessage(err, "操作失败");
    // 记住这次动作，失败后可以原样再试一次（列表不撤，用户不白屏）
    retryAction.value = async () => {
      await act(action, affected);
    };
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
    <!-- 一次性回执（如「已拒单」）：只在跳回列表的那一次出现 -->
    <div v-if="noticeText" class="page-notice" data-test="notice">{{ noticeText }}</div>

    <!-- 动作失败：后端原话 + 重试。页面内容照旧在下面，不白屏 -->
    <div v-if="actionError" class="page-block" data-test="action-error">
      <p class="page-error" data-test="action-error-text">{{ actionError }}</p>
      <van-button
        v-if="retryAction"
        size="small"
        plain
        type="primary"
        data-test="action-retry"
        @click="retryAction()"
      >
        重试
      </van-button>
    </div>

    <van-tabs v-model:active="activeTab" data-test="work-tabs">
      <!--
        tab 不设 name：Vant 的 active 会在「有 name 时回 name、没有时回下标」
        之间切换，混着来会让 active 有时是 "PENDING_ACCEPT"、有时是 0。
        这里统一用下标（下标 -> 状态的映射在 WORK_TABS 里）。
      -->
      <van-tab v-for="tab in WORK_TABS" :key="tab.status" :title="tab.title">
        <!--
          三种状态互斥：骨架屏 -> 错误 -> 空 -> 列表。
          出错时**不再**显示空状态（否则「拉挂了」和「没单」看起来一样）。
        -->
        <div v-if="stateOf(tab.status).loading" data-test="skeleton">
          <van-skeleton title :row="4" />
        </div>

        <div
          v-else-if="stateOf(tab.status).error"
          class="page-block"
          data-test="error-block"
        >
          <p class="page-error" data-test="error">{{ stateOf(tab.status).error }}</p>
          <van-button
            size="small"
            plain
            type="primary"
            data-test="retry"
            @click="loadStatus(tab.status)"
          >
            重试
          </van-button>
        </div>

        <van-empty
          v-else-if="lists[tab.status].length === 0"
          :data-test="`empty-${tab.status}`"
        >
          <template #description>
            <span data-test="empty-text">暂无{{ tab.title }}</span>
          </template>
        </van-empty>

        <van-cell-group v-else inset>
          <template v-for="row in lists[tab.status]" :key="row.order_no">
            <van-cell
              data-test="order-item"
              is-link
              @click="openDetail(row.order_no)"
            >
              <template #title>
                <span class="item-name" data-test="order-item-name">{{ row.item_name }}</span>
              </template>
              <template #label>
                <!-- 订单号 / 时间 / 地址：师傅在路上全都要看 -->
                <div class="item-meta">
                  <span data-test="order-no">{{ row.order_no }}</span>
                  <span data-test="order-time">
                    {{ row.slot_date }} {{ row.slot_start_time }}-{{ row.slot_end_time }}
                  </span>
                  <span data-test="order-address">
                    {{ row.address_region }} {{ row.address_detail }}
                  </span>
                </div>
              </template>
              <template #value>
                <div class="order-value">
                  <span class="order-amount" data-test="order-amount">¥{{ row.amount }}</span>
                  <van-tag type="primary" plain data-test="order-status">
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
