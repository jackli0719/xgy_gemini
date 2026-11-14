<script setup lang="ts">
/**
 * 下单页：选地址 + 选时段 + 提交下单。
 *
 * 路由：/order/new?itemId=&slotId=（itemName / date 可选，是列表页带过来的）
 *
 * - 时段：api.listItemSlots({ item_id, date })，后端只返回还有余量的时段；
 * - 地址：**占位**。后端还没有「我的地址」接口，卡片允许本卡写死一个
 *   address_id（见 src/constants/addresses.ts）；
 * - 下单：api.placeOrder({ item_id, slot_id, address_id })，金额由服务端算，
 *   前端不传金额。
 *
 * 下单成功跳 /orders。
 */
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "@/api";
import { PLACEHOLDER_ADDRESSES } from "@/constants/addresses";
import { firstQuery } from "@/utils/query";
import { todayStr } from "@/utils/date";
import type { components } from "@oto/shared/api";

type SlotAvailability = components["schemas"]["SlotAvailability"];

const route = useRoute();
const router = useRouter();

const itemId = computed(() => Number(firstQuery(route.query.itemId) ?? 0));
const itemName = computed(
  () => firstQuery(route.query.itemName) ?? `服务项 #${itemId.value}`,
);
const date = ref(firstQuery(route.query.date) ?? todayStr());

/** 列表页带过来的时段；没有就由本页让用户选。 */
const slotId = ref(Number(firstQuery(route.query.slotId) ?? 0));

const slots = ref<SlotAvailability[]>([]);
/** 地址下拉：占位数据，字段与将来的地址接口保持一致（id / label）。 */
const addressOptions = PLACEHOLDER_ADDRESSES.map((address) => ({
  text: address.label,
  value: address.id,
}));
const addressId = ref<number>(PLACEHOLDER_ADDRESSES[0].id);

const loading = ref(true);
const submitting = ref(false);
const error = ref("");

onMounted(loadSlots);

async function loadSlots(): Promise<void> {
  loading.value = true;
  error.value = "";
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
  } finally {
    loading.value = false;
  }
}

async function submit(): Promise<void> {
  if (!slotId.value) {
    error.value = "请选择预约时段";
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
      <van-cell title="服务项目" :value="itemName" />
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
      <van-dropdown-menu>
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
        data-test="submit-order"
        @click="submit"
      >
        提交下单
      </van-button>
      <van-tag type="default" class="hint-tag">金额由服务端按服务项基准价计算</van-tag>
    </div>
  </div>
</template>
