<script setup lang="ts">
/**
 * 订单详情。
 *
 * 数据来自 api.getMyOrder({ order_no })（GET /api/v1/orders/{order_no}）。
 * 后端只会返回自己的订单，别人的单子也是 404（R5 同构）。
 *
 * PENDING_CONFIRM（待确认）时显示「确认完成」按钮，
 * 点击调 api.confirmService({ order_no })（POST .../confirm）。
 *
 * UI-02 打磨的重点：
 * - 连点只发一次请求（同步 ref 守住，不只靠 disabled）；
 * - 确认成功后状态变 COMPLETED、按钮消失、显示完成时间；
 * - 确认失败不白屏：显示后端原话 + 重试按钮，订单内容照旧在页面上。
 */
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { api } from "@/api";
import { ORDER_STATUS_TEXT } from "@/constants/status";
import { errorMessage } from "@/utils/error";
import { ApiError } from "@oto/shared/api";
import { formatBusinessDateTime } from "@oto/shared/timezone";
import type { components } from "@oto/shared/api";

type OrderDetail = components["schemas"]["OrderDetail"];

const route = useRoute();

const orderNo = computed(() => String(route.params.orderNo ?? ""));
const order = ref<OrderDetail | null>(null);
const loading = ref(true);
const error = ref("");
/** 确认请求在途。既是按钮的 loading/disabled 依据，也是防连点的同步守卫。 */
const confirming = ref(false);
/** 确认失败的原因（后端原话）。 */
const confirmError = ref("");
/** 完成时间。确认接口的响应里有，详情接口没有（后端 OrderDetail 不含这个字段）。 */
const completedAt = ref("");

/** 待确认才给「确认完成」按钮（其他状态不给，免得用户点出 409）。 */
const canConfirm = computed(() => order.value?.status === "PENDING_CONFIRM");

/** 完成时间按业务时区显示（跟后端存的口径一致）。 */
const completedAtText = computed(() =>
  completedAt.value ? formatBusinessDateTime(completedAt.value) : "",
);

onMounted(load);

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    order.value = await api.getMyOrder({ order_no: orderNo.value });
  } catch (err) {
    error.value = errorMessage(err, "订单加载失败");
  } finally {
    loading.value = false;
  }
}

/**
 * 「这单已经不在待确认状态」——两种情况都算：
 *
 * - **409**：后端明确说状态冲突；
 * - **404**：后端把「状态不对」「订单不存在」「不是你的单」统一成 404
 *   （见 service_flow._claim_order：不能靠报错差异探测订单）。
 *
 * 这两种都不该让用户对着一个已经过期的按钮反复点，
 * 所以先刷新一次，把真实状态拉回来。
 */
function isStateConflict(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 409 || err.status === 404);
}

async function confirmDone(): Promise<void> {
  // 同步守卫：连点两次只发一次请求。
  // 光靠 disabled 不够——两次点击之间 Vue 还没 patch 出 disabled，
  // 第二次点击照样进得来。这里在发请求**之前**同步把 confirming 置 true，
  // 第二次进来直接 return。
  if (confirming.value) return;

  confirming.value = true;
  confirmError.value = "";
  try {
    const result = await api.confirmService({ order_no: orderNo.value });
    completedAt.value = result.completed_at ?? "";
    // 先用响应把本地状态改成 COMPLETED：按钮立刻消失，
    // 不用干等详情刷新回来（刷新失败也不该把按钮留在那儿让人再点一次）。
    if (order.value) {
      order.value = { ...order.value, status: result.status };
    }
    await load();
  } catch (err) {
    if (isStateConflict(err)) {
      // 状态已被改掉：带上后端原话，再刷新一次拿真实状态。
      confirmError.value = `${errorMessage(err, "订单状态已变化")}，正在刷新最新状态`;
      await load();
    } else {
      confirmError.value = errorMessage(err, "确认失败，请重试");
    }
  } finally {
    confirming.value = false;
  }
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">订单详情</h2>

    <!-- 已经有订单数据时就不再用骨架屏盖住页面：刷新别把内容抽走 -->
    <van-loading v-if="loading && !order" size="24" data-test="loading">加载中</van-loading>
    <p v-else-if="error && !order" class="page-error" data-test="error">{{ error }}</p>

    <template v-else-if="order">
      <!-- 刷新失败但订单还在：提示 + 重试，内容不撤 -->
      <div v-if="error" class="page-block" data-test="error-block">
        <p class="page-error" data-test="error">{{ error }}</p>
        <van-button size="small" plain type="primary" data-test="retry" @click="load">
          重试
        </van-button>
      </div>

      <!-- 确认失败：后端原话 + 重试。订单内容照旧在下面，不白屏 -->
      <div v-if="confirmError" class="page-block" data-test="confirm-error">
        <p class="page-error" data-test="confirm-error-text">{{ confirmError }}</p>
        <van-button size="small" plain type="primary" data-test="confirm-retry" @click="confirmDone">
          重试
        </van-button>
      </div>

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
        <van-cell v-if="completedAtText" title="完成时间" data-test="completed-at">
          <template #value>
            {{ completedAtText }}
          </template>
        </van-cell>
      </van-cell-group>

      <div class="page-footer">
        <van-button
          v-if="canConfirm"
          type="primary"
          block
          :loading="confirming"
          :disabled="confirming"
          data-test="confirm-button"
          @click="confirmDone"
        >
          确认完成
        </van-button>
      </div>
    </template>
  </div>
</template>
