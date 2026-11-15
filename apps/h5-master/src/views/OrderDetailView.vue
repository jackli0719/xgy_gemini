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
 */
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { api } from "@/api";
import RejectPopup from "@/components/RejectPopup.vue";
import { ORDER_STATUS_TEXT } from "@/constants/status";
import type { components } from "@oto/shared/api";

type MasterOrderDetail = components["schemas"]["MasterOrderDetail"];

const route = useRoute();

const orderNo = computed(() => String(route.params.orderNo ?? ""));
const order = ref<MasterOrderDetail | null>(null);
const loading = ref(true);
const busy = ref(false);
const error = ref("");

const rejectVisible = ref(false);

const canAccept = computed(() => order.value?.status === "PENDING_ACCEPT");
const canStart = computed(() => order.value?.status === "ACCEPTED");
const canFinish = computed(() => order.value?.status === "IN_SERVICE");

onMounted(load);

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    order.value = await api.getMasterOrder({ order_no: orderNo.value });
  } catch (err) {
    error.value = err instanceof Error ? err.message : "订单加载失败";
  } finally {
    loading.value = false;
  }
}

/** 做完一个动作就重新拉一次详情（状态变了，页面上的状态标签也得跟着变）。 */
async function act(action: () => Promise<unknown>): Promise<void> {
  busy.value = true;
  error.value = "";
  try {
    await action();
    await load();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "操作失败";
  } finally {
    busy.value = false;
  }
}

async function accept(): Promise<void> {
  await act(() => api.acceptOrder({ order_no: orderNo.value }));
}

async function start(): Promise<void> {
  await act(() => api.startService({ order_no: orderNo.value }));
}

async function finish(): Promise<void> {
  await act(() => api.finishService({ order_no: orderNo.value }));
}

async function reject(reason: string): Promise<void> {
  rejectVisible.value = false;
  await act(() => api.rejectOrder({ order_no: orderNo.value }, { reason }));
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">订单详情</h2>

    <van-loading v-if="loading" size="24" data-test="loading">加载中</van-loading>
    <p v-else-if="error" class="page-error" data-test="error">{{ error }}</p>

    <template v-else-if="order">
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
        <template v-if="canAccept">
          <van-button
            type="primary"
            block
            :loading="busy"
            data-test="accept-button"
            @click="accept"
          >
            接单
          </van-button>
          <van-button
            block
            :loading="busy"
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
