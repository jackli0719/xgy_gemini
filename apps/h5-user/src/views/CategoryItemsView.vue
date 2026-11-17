<script setup lang="ts">
/**
 * 品类下的服务项列表 + 可预约时段。
 *
 * - 服务项：api.listCategoryItems({ category_id })
 * - 时段：api.listItemSlots({ item_id, date })，后端只返回
 *   「今天及以后 且 还有余量」的时段（available > 0）。
 *
 * 「去预约」跳到 /order/new?itemId=&slotId=。
 * 只带 id：下单页会自己按 itemId 去接口查服务项名，
 * 不采信 query 里传的名称（query 是客户端可控的）。
 *
 * 三种页面状态（UI-01）：骨架屏 / 出错（有重试）/ 空数据（有引导按钮）。
 */
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "@/api";
import { todayStr } from "@/utils/date";
import { errorMessage } from "@/utils/error";
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
    error.value = errorMessage(err, "服务项加载失败");
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
      date: date.value,
    },
  });
}

/** 空状态里给一条出路：回到品类列表换个品类看看。 */
function backToCatalog(): void {
  void router.push("/catalog");
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

    <div v-if="loading" data-test="skeleton">
      <van-skeleton title :row="4" />
    </div>

    <div v-else-if="error" class="page-block" data-test="error-block">
      <p class="page-error" data-test="error">{{ error }}</p>
      <van-button size="small" plain type="primary" data-test="retry" @click="load">
        重试
      </van-button>
    </div>

    <van-empty v-else-if="items.length === 0" data-test="empty">
      <template #description>
        <span data-test="empty-text">该品类下暂时没有可预约的服务项</span>
      </template>
      <van-button size="small" type="primary" data-test="empty-action" @click="backToCatalog">
        返回品类列表
      </van-button>
    </van-empty>

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
