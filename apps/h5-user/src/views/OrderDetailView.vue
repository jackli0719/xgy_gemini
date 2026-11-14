<script setup lang="ts">
/**
 * 订单详情。
 *
 * 数据来自 api.getMyOrder({ order_no })（GET /api/v1/orders/{order_no}）。
 * 后端只会返回自己的订单，别人的单子也是 404（R5 同构）。
 *
 * PENDING_CONFIRM（待确认）时显示「确认完成」按钮，
 * 点击调 api.confirmService({ order_no })（POST .../confirm）。
 */
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";

import { api } from "@/api";
import { ORDER_STATUS_TEXT } from "@/constants/status";
import type { components } from "@oto/shared/api";

type OrderDetail = components["schemas"]["OrderDetail"];

const route = useRoute();

const orderNo = computed(() => String(route.params.orderNo ?? ""));
const order = ref<OrderDetail | null>(null);
const loading = ref(true);
const confirming = ref(false);
const error = ref("");

/** 待确认才给「确认完成」按钮（其他状态不给，免得用户点出 409）。 */
const canConfirm = computed(() => order.value?.status === "PENDING_CONFIRM");

onMounted(load);

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    order.value = await api.getMyOrder({ order_no: orderNo.value });
  } catch (err) {
    error.value = err instanceof Error ? err.message : "订单加载失败";
  } finally {
    loading.value = false;
  }
}

async function confirmDone(): Promise<void> {
  confirming.value = true;
  error.value = "";
  try {
    await api.confirmService({ order_no: orderNo.value });
    await load();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "确认失败";
  } finally {
    confirming.value = false;
  }
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
      </van-cell-group>

      <div class="page-footer">
        <van-button
          v-if="canConfirm"
          type="primary"
          block
          :loading="confirming"
          data-test="confirm-button"
          @click="confirmDone"
        >
          确认完成
        </van-button>
      </div>
    </template>
  </div>
</template>
