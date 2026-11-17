<!--
  派单页：本商待派单订单列表 + 派单弹窗。

  三步：
  1. 打开页面拉两样数据：待派单订单、本商师傅；
  2. 每行点「派单」-> 弹窗里选师傅 -> 确认，调 POST /orders/{order_id}/dispatch；
  3. 派单成功后**重新拉列表**（这单已经不在待派单池里了，不刷新会看到幽灵数据）。

  归属问题：前端**不带 provider_id**。服务商是谁由后端按 token 决定，
  这里只是调普通的列表接口。

  UI-03 打磨的重点：
  - 列表空的时候给一句「暂无待派单订单」+ 刷新按钮，不是一张空表；
  - 没有在岗师傅时，弹窗里说清楚「暂无在岗师傅」，确认按钮禁用；
  - 派单提交中按钮禁用，**连点两次只发一次请求**（同步 ref 守着，不只靠 disabled）；
  - 派单失败（409 已被派走 / 404 师傅不存在）显示后端原话 + 刷新列表。
-->
<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import {
  ElButton,
  ElDialog,
  ElEmpty,
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
/** 派单失败的原因（后端原话）。 */
const dispatchError = ref("");

function masterLabel(master: ProviderMasterItem): string {
  const rating = master.rating == null ? "暂无评分" : `评分 ${master.rating}`;
  return `${master.real_name}（${master.status} · ${rating}）`;
}

/**
 * 可选的师傅 = **在岗**的师傅。
 *
 * 后端派单时会拒掉停用 / 休假 / 未审核的师傅（409「师傅当前不可接单」），
 * 把他们列出来等于让人点一下再吃一个报错。
 */
const availableMasters = computed(() =>
  masters.value.filter((master) => master.status === "ACTIVE"),
);

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
  dispatchError.value = "";
  dialogVisible.value = true;
}

/**
 * 派单失败要分两种看：
 *
 * - **409**（订单已被派走 / 状态不对）：列表里这行已经不是待派单了，
 *   页面上的列表已经过期，必须刷新；
 * - **404**（师傅不存在 / 不属于本商）：可选师傅列表也过期了，同样刷新。
 *
 * 其他失败（网络错、500）刷新也没用，只显示后端原话。
 */
function needsRefresh(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 409 || err.status === 404);
}

async function confirmDispatch(): Promise<void> {
  const order = currentOrder.value;
  if (!order) return;

  // 同步守卫：连点两次只发一次请求。
  // 光靠 disabled 不够——两次点击之间 Vue 还没 patch 出 disabled，
  // 第二次点击照样进得来。这里在发请求**之前**同步把 dispatching 置 true，
  // 第二次进来直接 return。
  if (dispatching.value) return;

  if (selectedMasterId.value == null) {
    ElMessage.warning("请先选择师傅");
    return;
  }

  dispatching.value = true;
  dispatchError.value = "";
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
    // 后端原话（409「订单已派单，不能重复派单」/ 404「师傅不存在」）
    dispatchError.value =
      err instanceof ApiError ? err.detail : "派单失败，请稍后再试";
    if (needsRefresh(err)) {
      // 409 / 404 都意味着页面这份列表已经过期了：拉一次新的
      await load();
    }
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

    <!-- 空状态：一句人话 + 一个刷新按钮，不是一张空表让人猜 -->
    <div
      v-if="!loading && !errorText && orders.length === 0"
      class="empty-block"
      data-test="dispatch-empty"
    >
      <el-empty description="暂无待派单订单">
        <el-button data-test="dispatch-empty-refresh" @click="load">
          刷新
        </el-button>
      </el-empty>
    </div>

    <el-table v-else v-loading="loading" :data="orders" border stripe>
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

        <!-- 没有在岗师傅：下拉是空的，先说清楚，别让人对着空下拉发呆 -->
        <p v-if="availableMasters.length === 0" class="dialog-hint" data-test="no-master-hint">
          暂无在岗师傅
        </p>

        <el-select
          v-model="selectedMasterId"
          data-test="master-select"
          placeholder="选择师傅"
          :disabled="availableMasters.length === 0"
          :teleported="false"
          style="width: 100%"
        >
          <el-option
            v-for="master in availableMasters"
            :key="master.id"
            :label="masterLabel(master)"
            :value="master.id"
          />
        </el-select>

        <!-- 派单失败：后端原话。弹窗不关，让人换个师傅再试 -->
        <p v-if="dispatchError" class="error-text" data-test="dispatch-error">
          {{ dispatchError }}
        </p>
      </div>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          data-test="dispatch-confirm"
          :loading="dispatching"
          :disabled="dispatching || availableMasters.length === 0"
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

.dialog-hint {
  margin: 0 0 12px;
  color: #909399;
}
</style>
