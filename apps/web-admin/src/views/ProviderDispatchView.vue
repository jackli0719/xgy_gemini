<!--
  派单页：本商待派单订单列表 + 派单弹窗。

  三步：
  1. 打开页面拉两样数据：待派单订单、本商师傅；
  2. 每行点「派单」-> 弹窗里选师傅 -> 确认，调 POST /orders/{order_id}/dispatch；
  3. 派单成功后**重新拉列表**（这单已经不在待派单池里了，不刷新会看到幽灵数据）。

  归属问题：前端**不带 provider_id**。服务商是谁由后端按 token 决定，
  这里只是调普通的列表接口。
-->
<script setup lang="ts">
import { onMounted, ref } from "vue";
import {
  ElButton,
  ElDialog,
  ElMessage,
  ElOption,
  ElSelect,
  ElTable,
  ElTableColumn,
  vLoading,
} from "element-plus";
import { ApiError, type Schemas } from "@oto/shared/api";

import { api } from "@/api";
import { formatDateTime } from "@/utils/date";

type ProviderOrderItem = Schemas["ProviderOrderItem"];
type ProviderMasterItem = Schemas["ProviderMasterItem"];

/** 待派单的订单。 */
const orders = ref<ProviderOrderItem[]>([]);
/** 本商师傅。 */
const masters = ref<ProviderMasterItem[]>([]);
const loading = ref(false);
const errorText = ref("");

/** 派单弹窗 */
const dialogVisible = ref(false);
const currentOrder = ref<ProviderOrderItem | null>(null);
const selectedMasterId = ref<number | null>(null);
const dispatching = ref(false);

function masterLabel(master: ProviderMasterItem): string {
  const rating = master.rating == null ? "暂无评分" : `评分 ${master.rating}`;
  return `${master.real_name}（${master.status} · ${rating}）`;
}

/** 拉订单 + 师傅。派单成功后也要再调一次（刷新列表）。 */
async function load(): Promise<void> {
  loading.value = true;
  errorText.value = "";
  try {
    const [orderResult, masterResult] = await Promise.all([
      api.listProviderOrders({ status: "PENDING_DISPATCH" }),
      api.listProviderMasters(),
    ]);
    orders.value = orderResult.items;
    masters.value = masterResult.items;
  } catch (err) {
    errorText.value = err instanceof ApiError ? err.detail : "加载失败，请稍后再试";
  } finally {
    loading.value = false;
  }
}

function openDispatch(row: ProviderOrderItem): void {
  currentOrder.value = row;
  selectedMasterId.value = null;
  dialogVisible.value = true;
}

async function confirmDispatch(): Promise<void> {
  const order = currentOrder.value;
  if (!order) return;
  if (selectedMasterId.value == null) {
    ElMessage.warning("请先选择师傅");
    return;
  }

  dispatching.value = true;
  try {
    await api.dispatchOrder(
      { order_id: order.id },
      { master_id: selectedMasterId.value },
    );
    ElMessage.success("派单成功");
    dialogVisible.value = false;
    // 派出去的订单已经不在待派单池里了：不刷新列表会看到幽灵数据
    await load();
  } catch (err) {
    ElMessage.error(err instanceof ApiError ? err.detail : "派单失败，请稍后再试");
  } finally {
    dispatching.value = false;
  }
}

onMounted(() => {
  void load();
});
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2 class="page-title">待派单</h2>
      <el-button data-test="reload" :loading="loading" @click="load">
        刷新
      </el-button>
    </div>

    <p v-if="errorText" class="error-text" data-test="error">{{ errorText }}</p>

    <el-table v-loading="loading" :data="orders" border stripe>
      <el-table-column prop="order_no" label="订单号" min-width="180" />
      <el-table-column prop="item_name" label="服务项" min-width="140" />
      <el-table-column label="金额" width="120" align="right">
        <template #default="{ row }">¥{{ row.amount }}</template>
      </el-table-column>
      <el-table-column label="下单时间" min-width="170">
        <template #default="{ row }">{{ formatDateTime(row.created_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="100" align="center">
        <!--
          el-table 的插槽行类型是宽松的 DefaultRow，这里显式断言回
          ProviderOrderItem：表格里的数据就是我们自己塞进去的 orders，
          类型不会比它更差。
        -->
        <template #default="{ row }">
          <el-button
            type="primary"
            link
            data-test="dispatch-btn"
            @click="openDispatch(row as ProviderOrderItem)"
          >
            派单
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="dialogVisible" title="派单" width="420px">
      <div data-test="dispatch-dialog">
        <p v-if="currentOrder" class="dialog-order">
          订单 {{ currentOrder.order_no }} · {{ currentOrder.item_name }}
        </p>

        <el-select
          v-model="selectedMasterId"
          data-test="master-select"
          placeholder="选择师傅"
          :teleported="false"
          style="width: 100%"
        >
          <el-option
            v-for="master in masters"
            :key="master.id"
            :label="masterLabel(master)"
            :value="master.id"
          />
        </el-select>
      </div>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          data-test="dispatch-confirm"
          :loading="dispatching"
          @click="confirmDispatch"
        >
          确认派单
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.dialog-order {
  margin: 0 0 12px;
  color: #606266;
}
</style>
