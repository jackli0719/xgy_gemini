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
 */
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "@/api";
import { firstQuery } from "@/utils/query";
import { todayStr } from "@/utils/date";
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
    error.value = err instanceof Error ? err.message : "服务项加载失败";
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
    error.value = err instanceof Error ? err.message : "时段加载失败";
  }
}

async function loadAddresses(): Promise<void> {
  try {
    addresses.value = await api.listAddresses();
    const first = addresses.value[0];
    if (first) addressId.value = first.id;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "地址加载失败";
  }
}

async function submit(): Promise<void> {
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
    error.value = err instanceof Error ? err.message : "下单失败";
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">确认预约</h2>

    <van-cell-group inset>
      <van-cell title="服务项目" :value="itemName" data-test="item-name" />
      <van-cell title="预约日期" :value="date" />
      <van-cell title="预约时段">
        <template #value>
          <van-loading v-if="loading" size="16">加载中</van-loading>
          <span v-else-if="slots.length === 0" class="item-meta">当天无可约时段</span>
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
        v-if="!loading && addresses.length === 0"
        image="search"
        description="请先添加地址"
        data-test="no-address"
      />
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
        :disabled="!loading && addresses.length === 0"
        data-test="submit-order"
        @click="submit"
      >
        提交下单
      </van-button>
      <van-tag type="default" class="hint-tag">金额由服务端按服务项基准价计算</van-tag>
    </div>
  </div>
</template>
