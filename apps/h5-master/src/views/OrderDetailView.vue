<script setup lang="ts">
/**
 * 订单详情（师傅端）。
 *
 * 数据来自 api.getMasterOrder({ order_no })（GET /api/v1/master/orders/{order_no}）。
 * 后端只返回派给我的单，别人的单也是 404（R5 同构）。
 *
 * 详情里带**客户联系方式与上门地址**：师傅要上门服务，得知道去哪儿、找谁。
 *
 * 操作按钮按订单状态给：待接单给「接单 / 拒单」，已接单给「开始服务」，
 * 服务中给「完成服务」——不给不该出现的按钮，免得用户点出 404 / 409。
 *
 * UI-M2 打磨的重点：
 *
 * 1. **拒单后不回详情**：拒单成功订单退回 PENDING_DISPATCH、master_id 被清空，
 *    这单已经不属于我了，详情接口必然 404。所以拒单成功只做两件事：
 *    记一条回执（「已拒单」）+ 跳回列表。刷新详情 = 白屏 + 404。
 * 2. **连点只发一次请求**：同步 ref 守住（不只靠 disabled），
 *    两次点击之间 Vue 还没 patch 出 disabled，光靠按钮禁用拦不住。
 * 3. **失败不白屏**：显示后端原话 + 「返回列表」按钮，订单内容照旧在页面上。
 */
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "@/api";
import RejectPopup from "@/components/RejectPopup.vue";
import { ORDER_STATUS_TEXT } from "@/constants/status";
import { errorMessage } from "@/utils/error";
import { setNotice } from "@/utils/notice";
import { ApiError } from "@oto/shared/api";
import type { components } from "@oto/shared/api";

type MasterOrderDetail = components["schemas"]["MasterOrderDetail"];

const route = useRoute();
const router = useRouter();

const orderNo = computed(() => String(route.params.orderNo ?? ""));
const order = ref<MasterOrderDetail | null>(null);
/** 正在拉详情。只有**还没有订单数据**时才盖住页面（见模板）。 */
const loading = ref(true);
/** 动作在途：既是按钮 loading/disabled 的依据，也是防连点的同步守卫。 */
const busy = ref(false);
/** 详情加载失败的原因（后端原话）。空串 = 没出错。 */
const loadError = ref("");
/** 动作失败的原因（后端原话）。空串 = 没出错。 */
const actionError = ref("");

/** 拒单弹窗 */
const rejectVisible = ref(false);

/**
 * 按钮按订单状态给。
 *
 * 只有这三种状态能操作，其余状态（如 PENDING_DISPATCH / COMPLETED）
 * **一个按钮都不给**——给了也是 409，白白让用户点一次。
 */
const canAccept = computed(() => order.value?.status === "PENDING_ACCEPT");
const canStart = computed(() => order.value?.status === "ACCEPTED");
const canFinish = computed(() => order.value?.status === "IN_SERVICE");

onMounted(load);

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    order.value = await api.getMasterOrder({ order_no: orderNo.value });
  } catch (err) {
    // 业务错显示后端原话，网络错给统一文案（见 utils/error.ts）
    loadError.value = errorMessage(err, "订单加载失败");
  } finally {
    loading.value = false;
  }
}

/**
 * 「这单已经不在预期状态」——两种情况都算：
 *
 * - **409**：后端明确说状态冲突；
 * - **404**：后端把「状态不对」「订单不存在」「不是我的单」统一成 404。
 *
 * 这两种都该让用户看到最新状态，所以顺手再拉一次详情。
 */
function isStateConflict(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 409 || err.status === 404);
}

/**
 * 做一个订单动作。
 *
 * @param action 真正发请求的动作
 * @param onSuccess 成功后的收尾：接单/开工/完工要刷新详情，拒单要跳回列表
 */
async function act(
  action: () => Promise<unknown>,
  onSuccess?: () => Promise<void> | void,
): Promise<void> {
  // 连点守卫：光靠按钮的 loading/disabled 不够——两次点击之间 Vue 还没
  // patch 出 disabled，第二次点击照样进得来（与 UI-01 / UI-02 的做法一致）。
  // 这里在发请求**之前**同步把 busy 置 true，第二次进来直接 return。
  if (busy.value) return;

  busy.value = true;
  actionError.value = "";
  try {
    await action();
    await onSuccess?.();
  } catch (err) {
    if (isStateConflict(err)) {
      // 状态已被改掉：带上后端原话，再刷新一次拿真实状态。
      // 刷新只动 loadError，**不会把 actionError 冲掉**——
      // 用户还得看到后端那句话（不然就只剩一句「状态变了」）。
      actionError.value = errorMessage(err, "订单状态已变化");
      await load();
    } else {
      actionError.value = errorMessage(err, "操作失败，请重试");
    }
  } finally {
    busy.value = false;
  }
}

async function accept(): Promise<void> {
  // 接单成功：状态变了，重新拉一次详情，状态标签与按钮跟着变
  await act(() => api.acceptOrder({ order_no: orderNo.value }), load);
}

async function start(): Promise<void> {
  await act(() => api.startService({ order_no: orderNo.value }), load);
}

async function finish(): Promise<void> {
  await act(() => api.finishService({ order_no: orderNo.value }), load);
}

/**
 * 拒单。
 *
 * 成功之后**绝对不能刷新详情**：后端把订单退回 PENDING_DISPATCH 并清空
 * master_id，这单已经不属于我了，详情接口会 404（刷新 = 白屏 + 404）。
 * 所以改成记一条回执（「已拒单」）然后跳回列表。
 */
async function reject(reason: string): Promise<void> {
  rejectVisible.value = false;
  await act(
    () => api.rejectOrder({ order_no: orderNo.value }, { reason }),
    async () => {
      setNotice("已拒单");
      // 用 replace 而不是 push：这单已经 404 了，留着历史记录的话
      // 用户一按后退就又撞回 404。
      await router.replace("/orders");
    },
  );
}

/**
 * 回列表页（错误块里的「返回列表」按钮）。
 *
 * 同样用 replace：这个详情页可能已经不存在了（拒单后 / 订单被收走），
 * 留着历史记录只会让用户后退又撞一次 404。
 */
function goList(): void {
  void router.replace("/orders");
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">订单详情</h2>

    <!-- 已经有订单数据时就不再用加载动画盖住页面：刷新别把内容抽走 -->
    <van-loading v-if="loading && !order" size="24" data-test="loading">加载中</van-loading>

    <!--
      错误块：两个错误源互斥（v-if / v-else-if），「返回列表」按钮
      永远只出现一次。订单内容在下面照常渲染 —— 出错时页面不白屏。
    -->
    <div v-if="actionError" class="page-block" data-test="action-error">
      <p class="page-error" data-test="action-error-text">{{ actionError }}</p>
      <van-button
        size="small"
        plain
        type="primary"
        data-test="back-to-list"
        @click="goList"
      >
        返回列表
      </van-button>
    </div>
    <div v-else-if="loadError" class="page-block" data-test="error-block">
      <p class="page-error" data-test="error">{{ loadError }}</p>
      <van-button
        size="small"
        plain
        type="primary"
        data-test="back-to-list"
        @click="goList"
      >
        返回列表
      </van-button>
    </div>

    <template v-if="order">
      <van-cell-group inset>
        <van-cell title="订单号" :value="order.order_no" data-test="order-no" />
        <van-cell title="服务项目" :value="order.item_name" />
        <van-cell title="预约时段">
          <template #value>
            {{ order.slot_date }} {{ order.slot_start_time }} - {{ order.slot_end_time }}
          </template>
        </van-cell>
        <van-cell title="订单金额" :value="`¥${order.amount}`" data-test="order-amount" />
        <van-cell title="订单状态">
          <template #value>
            <van-tag type="primary" plain data-test="order-status">
              {{ ORDER_STATUS_TEXT[order.status] }}
            </van-tag>
          </template>
        </van-cell>
        <van-cell title="客户" :value="order.customer_contact" data-test="customer" />
        <van-cell title="客户电话" :value="order.customer_phone" />
        <van-cell title="上门地址">
          <template #value>
            <span data-test="address">
              {{ order.address_region }} {{ order.address_detail }}
            </span>
          </template>
        </van-cell>
      </van-cell-group>

      <div class="page-footer">
        <!--
          按钮按订单状态给：待接单 -> 接单/拒单，已接单 -> 开始服务，
          服务中 -> 完成服务。**其他状态一个按钮都不给**
          （给了也是 409，白白让用户点一次）。
        -->
        <template v-if="canAccept">
          <van-button
            type="primary"
            block
            :loading="busy"
            :disabled="busy"
            data-test="accept-button"
            @click="accept"
          >
            接单
          </van-button>
          <van-button
            block
            :loading="busy"
            :disabled="busy"
            data-test="reject-button"
            @click="rejectVisible = true"
          >
            拒单
          </van-button>
        </template>
        <van-button
          v-else-if="canStart"
          type="primary"
          block
          :loading="busy"
          :disabled="busy"
          data-test="start-button"
          @click="start"
        >
          开始服务
        </van-button>
        <van-button
          v-else-if="canFinish"
          type="primary"
          block
          :loading="busy"
          :disabled="busy"
          data-test="finish-button"
          @click="finish"
        >
          完成服务
        </van-button>
      </div>
    </template>

    <RejectPopup v-model:show="rejectVisible" @confirm="reject" />
  </div>
</template>
