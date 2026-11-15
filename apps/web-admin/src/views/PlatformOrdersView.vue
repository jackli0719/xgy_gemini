<!--
  平台侧订单总览页（PLAT-02）。

  三件事：
  1. 打开页面拉订单列表（**全量**：不按用户过滤，这是平台侧的特权）；
  2. 筛选栏：按状态 / 按服务商筛——筛选是查询条件，不是隔离边界；
  3. 翻页。

  筛选条件变了就回到第一页重新拉（否则会停在不存在的页码上）。

  服务商选项来自订单接口自带的 providers 列表：平台侧的服务商列表接口
  只对平台管理员开放，而订单总览平台运营也要能筛。
-->
<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import {
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

type PlatformOrderItem = Schemas["PlatformOrderItem"];
type OrderStatus = PlatformOrderItem["status"];

/** 订单状态 -> 中文文案与 tag 颜色。 */
const STATUS_TEXT: Record<OrderStatus, string> = {
  PENDING_PAY: "待支付",
  PENDING_DISPATCH: "待派单",
  PENDING_ACCEPT: "待接单",
  ACCEPTED: "已接单",
  IN_SERVICE: "服务中",
  PENDING_CONFIRM: "待确认",
  COMPLETED: "已完成",
  PENDING_SETTLE: "待结算",
  SETTLED: "已结算",
  CANCELLED: "已取消",
  REFUNDING: "退款中",
  REFUNDED: "已退款",
};

const STATUS_TAG_TYPE: Record<
  OrderStatus,
  "primary" | "success" | "info" | "warning" | "danger"
> = {
  PENDING_PAY: "info",
  PENDING_DISPATCH: "warning",
  PENDING_ACCEPT: "warning",
  ACCEPTED: "primary",
  IN_SERVICE: "primary",
  PENDING_CONFIRM: "info",
  COMPLETED: "success",
  PENDING_SETTLE: "info",
  SETTLED: "success",
  CANCELLED: "info",
  REFUNDING: "warning",
  REFUNDED: "danger",
};

/** 筛选项的取值：空字符串表示「不限」。 */
const statusFilter = ref<string>("");
const providerFilter = ref<number | undefined>(undefined);

const orders = ref<PlatformOrderItem[]>([]);
const providers = ref<{ id: number; name: string }[]>([]);
const total = ref(0);
const page = ref(1);
const limit = ref(20);
const loading = ref(false);
const errorText = ref("");

function statusText(status: OrderStatus): string {
  return STATUS_TEXT[status];
}

function statusTagType(status: OrderStatus) {
  return STATUS_TAG_TYPE[status];
}

/** 拉订单列表。筛选或翻页变了都走这里。 */
async function load(): Promise<void> {
  loading.value = true;
  errorText.value = "";
  try {
    const result = await api.listPlatformOrders({
      status: (statusFilter.value || undefined) as never,
      provider_id: providerFilter.value,
      page: page.value,
      limit: limit.value,
    });
    orders.value = result.items;
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

onMounted(() => {
  void load();
});
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2 class="page-title">订单总览</h2>
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

    <el-table v-loading="loading" :data="orders" border stripe>
      <el-table-column prop="order_no" label="订单号" min-width="180" />
      <el-table-column label="状态" width="110" align="center">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)">
            {{ statusText(row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="pay_status" label="支付状态" width="110" />
      <el-table-column prop="amount" label="金额" width="110" align="right" />
      <el-table-column label="服务商" min-width="140">
        <template #default="{ row }">
          {{ row.provider_name ?? "（未派单）" }}
        </template>
      </el-table-column>
      <el-table-column prop="item_name" label="服务项" min-width="140" />
      <el-table-column prop="created_at" label="下单时间" min-width="180" />
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
