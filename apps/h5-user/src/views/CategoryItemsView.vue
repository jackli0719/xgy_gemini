<script setup lang="ts">
/**
 * 品类下的服务项列表 + 可预约时段。
 *
 * - 服务项：api.listCategoryItems({ category_id })
 * - 时段：api.listItemSlots({ item_id, date })，后端只返回
 *   「今天及以后 且 还有余量」的时段（available > 0）。
 *
 * 「去预约」跳到 /order/new?itemId=&slotId=。
 */
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "@/api";
import { todayStr } from "@/utils/date";
import type { components } from "@oto/shared/api";

type ServiceItemSummary = components["schemas"]["ServiceItemSummary"];
type SlotAvailability = components["schemas"]["SlotAvailability"];

const route = useRoute();
const router = useRouter();

const categoryId = computed(() => Number(route.params.id));
const date = ref(todayStr());

const items = ref<ServiceItemSummary[]>([]);
/** item_id -> 该服务项当天的可预约时段 */
const slotsByItem = ref<Record<number, SlotAvailability[]>>({});
const loading = ref(true);
const error = ref("");

onMounted(load);

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    items.value = await api.listCategoryItems({ category_id: categoryId.value });
    const pairs = await Promise.all(
      items.value.map(async (item) => {
        const slots = await api.listItemSlots({
          item_id: item.id,
          date: date.value,
        });
        return [item.id, slots] as const;
      }),
    );
    slotsByItem.value = Object.fromEntries(pairs);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "服务项加载失败";
  } finally {
    loading.value = false;
  }
}

function slotsOf(itemId: number): SlotAvailability[] {
  return slotsByItem.value[itemId] ?? [];
}

function book(item: ServiceItemSummary, slot: SlotAvailability): void {
  void router.push({
    name: "order-new",
    query: {
      itemId: String(item.id),
      slotId: String(slot.id),
      itemName: item.name,
      date: date.value,
    },
  });
}
</script>

<template>
  <div class="page">
    <van-field
      v-model="date"
      type="date"
      label="预约日期"
      data-test="date-field"
      @change="load"
    />

    <van-loading v-if="loading" size="24" data-test="loading">加载中</van-loading>
    <p v-else-if="error" class="page-error" data-test="error">{{ error }}</p>
    <van-empty v-else-if="items.length === 0" description="该品类下暂无服务项" />

    <van-cell-group v-else inset>
      <van-cell v-for="item in items" :key="item.id" data-test="item-card">
        <template #title>
          <span class="item-name">{{ item.name }}</span>
        </template>
        <template #label>
          <span class="item-meta">
            ¥{{ item.base_price }} · {{ item.duration_min }} 分钟
          </span>
        </template>
        <template #value>
          <div class="slot-list">
            <template v-if="slotsOf(item.id).length === 0">
              <span class="item-meta">当天已无可约时段</span>
            </template>
            <van-button
              v-for="slot in slotsOf(item.id)"
              :key="slot.id"
              size="small"
              type="primary"
              plain
              class="slot-button"
              data-test="slot-button"
              @click="book(item, slot)"
            >
              {{ slot.start_time }} 剩{{ slot.available }}
            </van-button>
          </div>
        </template>
      </van-cell>
    </van-cell-group>

    <div class="page-footer">
      <van-tag type="default">共 {{ items.length }} 个服务项</van-tag>
    </div>
  </div>
</template>
