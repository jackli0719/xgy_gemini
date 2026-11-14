<script setup lang="ts">
/**
 * 我的订单列表。
 *
 * 数据来自 api.listMyOrders({ limit, offset })（GET /api/v1/orders）。
 * 后端已经按「当前登录用户」过滤（R5），前端不需要也不能传 user_id。
 *
 * 分页：每页 20 条（后端上限 100），用 total 判断还有没有下一页。
 */
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { api } from "@/api";
import { ORDER_STATUS_TEXT } from "@/constants/status";
import type { components } from "@oto/shared/api";

type OrderListItem = components["schemas"]["OrderListItem"];

const router = useRouter();

/** 每页条数。后端默认 20、上限 100，这里就用默认值。 */
const PAGE_SIZE = 20;

const page = ref(1);
const total = ref(0);
const orders = ref<OrderListItem[]>([]);
const loading = ref(true);
const error = ref("");

onMounted(load);

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const result = await api.listMyOrders({
      limit: PAGE_SIZE,
      offset: (page.value - 1) * PAGE_SIZE,
    });
    orders.value = result.items;
    total.value = result.total;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "订单加载失败";
  } finally {
    loading.value = false;
  }
}

function turn(pageNo: number): void {
  page.value = pageNo;
  void load();
}

function open(orderNo: string): void {
  void router.push(`/orders/${orderNo}`);
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">我的订单</h2>

    <van-loading v-if="loading" size="24" data-test="loading">加载中</van-loading>
    <p v-else-if="error" class="page-error" data-test="error">{{ error }}</p>
    <van-empty v-else-if="orders.length === 0" description="还没有订单" />

    <van-cell-group v-else inset>
      <van-cell
        v-for="order in orders"
        :key="order.order_no"
        is-link
        data-test="order-item"
        @click="open(order.order_no)"
      >
        <template #title>
          <span class="item-name">{{ order.item_name }}</span>
        </template>
        <template #label>
          <span class="item-meta">
            {{ order.order_no }} · {{ order.slot_date }} {{ order.slot_start_time }}
          </span>
        </template>
        <template #value>
          <div class="order-value">
            <span class="order-amount">¥{{ order.amount }}</span>
            <van-tag type="primary" plain>
              {{ ORDER_STATUS_TEXT[order.status] }}
            </van-tag>
          </div>
        </template>
      </van-cell>
    </van-cell-group>

    <div class="page-footer">
      <van-button
        size="small"
        :disabled="page <= 1"
        data-test="prev-page"
        @click="turn(page - 1)"
      >
        上一页
      </van-button>
      <span class="page-meta" data-test="page-meta">
        第 {{ page }} 页 / 共 {{ total }} 条
      </span>
      <van-button
        size="small"
        :disabled="page * PAGE_SIZE >= total"
        data-test="next-page"
        @click="turn(page + 1)"
      >
        下一页
      </van-button>
    </div>
  </div>
</template>
