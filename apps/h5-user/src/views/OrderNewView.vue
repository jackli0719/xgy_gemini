<script setup lang="ts">
/**
 * 下单页：选地址 + 选时段 + 提交下单。
 *
 * 路由：/order/new?itemId=&slotId=（date 可选，是列表页带过来的）
 *
 * - 服务项：api.getItem({ item_id })，**商品名不再靠 query 传**——
 *   query 是客户端可控的，价格和名称都得以服务端返回的为准；
 * - 时段：api.listItemSlots({ item_id, date })，后端只返回还有余量的时段；
 * - 地址：api.listAddresses()，没有地址就提示「请先添加地址」并挡住下单；
 * - 下单：api.placeOrder({ item_id, slot_id, address_id })，金额由服务端算，
 *   前端不传金额。
 *
 * 下单成功跳 /orders。
 *
 * UI-01 的几个约束：
 * - **提交按钮防连点**：`submitting` 是一道同步的闸（见 submit），
 *   连点两次只发一次下单请求；
 * - **没有时段 / 没有地址**都给出下一步的按钮，不把人堵在页面上；
 * - **网络错误与业务错误分开说**：网络错提示重试，业务错显示后端原话。
 */
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "@/api";
import { firstQuery } from "@/utils/query";
import { todayStr, shiftDate } from "@/utils/date";
import { errorMessage } from "@/utils/error";
import type { components } from "@oto/shared/api";

type SlotAvailability = components["schemas"]["SlotAvailability"];
type AddressResponse = components["schemas"]["AddressResponse"];

const route = useRoute();
const router = useRouter();

const itemId = computed(() => Number(firstQuery(route.query.itemId) ?? 0));
const date = ref(firstQuery(route.query.date) ?? todayStr());

/** 列表页带过来的时段；没有就由本页让用户选。 */
const slotId = ref(Number(firstQuery(route.query.slotId) ?? 0));

const slots = ref<SlotAvailability[]>([]);
/** 服务项名称：来自接口，不是 query。 */
const itemName = ref("");
/** 我的地址：来自接口。 */
const addresses = ref<AddressResponse[]>([]);
const addressId = ref<number | null>(null);

const loading = ref(true);
const submitting = ref(false);
const error = ref("");

const addressOptions = computed(() =>
  addresses.value.map((address) => ({
    text: `${address.contact} ${address.region} ${address.detail}`,
    value: address.id,
  })),
);

onMounted(load);

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  await Promise.all([loadItem(), loadSlots(), loadAddresses()]);
  loading.value = false;
}

async function loadItem(): Promise<void> {
  try {
    const item = await api.getItem({ item_id: itemId.value });
    itemName.value = item.name;
  } catch (err) {
    itemName.value = `服务项 #${itemId.value}`;
    error.value = errorMessage(err, "服务项加载失败");
  }
}

async function loadSlots(): Promise<void> {
  try {
    slots.value = await api.listItemSlots({
      item_id: itemId.value,
      date: date.value,
    });
    if (!slotId.value) {
      const first = slots.value[0];
      if (first) slotId.value = first.id;
    }
  } catch (err) {
    error.value = errorMessage(err, "时段加载失败");
  }
}

async function loadAddresses(): Promise<void> {
  try {
    addresses.value = await api.listAddresses();
    const first = addresses.value[0];
    if (first) addressId.value = first.id;
  } catch (err) {
    error.value = errorMessage(err, "地址加载失败");
  }
}

/**
 * 换到下一天。
 *
 * 时段是跟着日期走的：日期一变，上一天的时段就作废了，
 * 所以这里把 slotId 清零（loadSlots 会自动选新日期的第一个时段）。
 */
async function nextDay(): Promise<void> {
  date.value = shiftDate(date.value, 1);
  slotId.value = 0;
  await loadSlots();
}

/** 空状态里给一条出路：去地址页补一个地址。 */
function goAddresses(): void {
  void router.push("/addresses");
}

async function submit(): Promise<void> {
  // **防连点的闸**：submitting 是同步置位的。
  //
  // 按钮上的 disabled / loading 要等 Vue 重新渲染才生效，
  // 连点两下时第二次点击发生在重渲染之前，光靠按钮禁用拦不住——
  // 于是这里用 ref 自己再挡一次（ref 赋值是同步的）。
  if (submitting.value) return;
  if (!slotId.value) {
    error.value = "请选择预约时段";
    return;
  }
  if (addressId.value === null) {
    error.value = "请先添加地址";
    return;
  }
  submitting.value = true;
  error.value = "";
  try {
    await api.placeOrder({
      item_id: itemId.value,
      slot_id: slotId.value,
      address_id: addressId.value,
    });
    await router.push("/orders");
  } catch (err) {
    error.value = errorMessage(err, "下单失败");
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">确认预约</h2>

    <div v-if="loading" data-test="skeleton">
      <van-skeleton title :row="3" />
    </div>

    <template v-else>
      <van-cell-group inset>
        <van-cell title="服务项目" :value="itemName" data-test="item-name" />
        <van-cell title="预约日期" :value="date" />
        <van-cell title="预约时段">
          <template #value>
            <div v-if="slots.length === 0" class="empty-inline" data-test="no-slot">
              <span class="item-meta">当天无可约时段</span>
              <van-button
                size="small"
                plain
                type="primary"
                class="slot-button"
                data-test="next-day"
                @click="nextDay"
              >
                换一天
              </van-button>
            </div>
            <div v-else class="slot-list">
              <van-button
                v-for="slot in slots"
                :key="slot.id"
                size="small"
                :type="slot.id === slotId ? 'primary' : 'default'"
                plain
                class="slot-button"
                data-test="slot-button"
                @click="slotId = slot.id"
              >
                {{ slot.start_time }} 剩{{ slot.available }}
              </van-button>
            </div>
          </template>
        </van-cell>
      </van-cell-group>

      <div class="page-block">
        <p class="page-label">服务地址</p>
        <van-empty
          v-if="addresses.length === 0"
          image="search"
          description="请先添加地址"
          data-test="no-address"
        >
          <van-button
            size="small"
            type="primary"
            data-test="add-address"
            @click="goAddresses"
          >
            去添加地址
          </van-button>
        </van-empty>
        <van-dropdown-menu v-else>
          <van-dropdown-item
            v-model="addressId"
            :options="addressOptions"
            data-test="address-select"
          />
        </van-dropdown-menu>
      </div>

      <p v-if="error" class="page-error" data-test="error">{{ error }}</p>

      <div class="page-footer">
        <van-button
          type="primary"
          block
          :loading="submitting"
          :disabled="submitting || addresses.length === 0"
          data-test="submit-order"
          @click="submit"
        >
          提交下单
        </van-button>
        <van-tag type="default" class="hint-tag">金额由服务端按服务项基准价计算</van-tag>
      </div>
    </template>
  </div>
</template>
