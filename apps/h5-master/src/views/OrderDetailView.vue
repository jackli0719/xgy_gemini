<script setup lang="ts">
/**
 * 订单详情（师傅端）。
 *
 * 数据来自 api.getMasterOrder({ order_no })（GET /api/v1/master/orders/{order_no}）。
 * 后端只返回派给我的单，别人的单也是 404（R5 同构）。
 *
 * 详情里带**客户联系方式与上门地址**：师傅要上门服务，得知道去哪儿、找谁。
 *
 * 操作按钮按订单状态给：待接单给「接单 / 拒单」，已接单给「开始服务」，
 * 服务中给「完成服务」——不给不该出现的按钮，免得用户点出 404 / 409。
 *
 * UI-M2 打磨的重点：
 *
 * 1. **拒单后不回详情**：拒单成功订单退回 PENDING_DISPATCH、master_id 被清空，
 *    这单已经不属于我了，详情接口必然 404。所以拒单成功只做两件事：
 *    记一条回执（「已拒单」）+ 跳回列表。刷新详情 = 白屏 + 404。
 * 2. **连点只发一次请求**：同步 ref 守住（不只靠 disabled），
 *    两次点击之间 Vue 还没 patch 出 disabled，光靠按钮禁用拦不住。
 * 3. **失败不白屏**：显示后端原话 + 「返回列表」按钮，订单内容照旧在页面上
 *    （拒单失败是个例外：后端原话显示在弹窗里，见第 7 条）。
 * 4. **刷新失败就不给动作按钮**：刷新失败 = 订单状态不可信，
 *    这时候还挂「开始服务」按钮，用户点了也只会再撞一次 404 / 409。
 * 5. **只有 404 才刷新详情**：师傅端四个写接口的「订单侧冲突」
 *    （订单不存在 / 不是派给我的 / 状态已变）后端同构成一个 404，
 *    这时刷新才能拿到真实状态；409 是「师傅当前不可接单」
 *    （停用 / 休假 / 未审核），订单状态压根没变，刷新学不到东西，不刷新。
 * 6. **动作与收尾分开报错**：收尾（刷新详情 / 跳回列表）失败时动作其实
 *    已经成功了，这时要说「操作已完成」，不能报「操作失败」——
 *    后者会让师傅以为没拒成功、白点一次。
 * 7. **拒单失败弹窗不关**：原因保留、后端原话显示在弹窗里，
 *    师傅能直接再点一次「确认拒单」重试，不用重填原因。
 */
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "@/api";
import RejectPopup from "@/components/RejectPopup.vue";
import { ORDER_STATUS_TEXT } from "@/constants/status";
import { errorMessage } from "@/utils/error";
import { setNotice } from "@/utils/notice";
import { ApiError } from "@oto/shared/api";
import type { components } from "@oto/shared/api";

type MasterOrderDetail = components["schemas"]["MasterOrderDetail"];

const route = useRoute();
const router = useRouter();

const orderNo = computed(() => String(route.params.orderNo ?? ""));
const order = ref<MasterOrderDetail | null>(null);
/** 正在拉详情。只有**还没有订单数据**时才盖住页面（见模板）。 */
const loading = ref(true);
/** 动作在途：既是按钮 loading/disabled 的依据，也是防连点的同步守卫。 */
const busy = ref(false);
/** 详情加载失败的原因（后端原话）。空串 = 没出错。 */
const loadError = ref("");
/** 动作失败的原因（后端原话）。空串 = 没出错。 */
const actionError = ref("");

/** 拒单弹窗 */
const rejectVisible = ref(false);

/**
 * 按钮按订单状态给。
 *
 * 只有这三种状态能操作，其余状态（如 PENDING_DISPATCH / COMPLETED）
 * **一个按钮都不给**——状态不对时后端一律回 404（订单不存在 / 不是我的 /
 * 状态已变，同构），师傅当前不可接单时回 409，两种都是必然失败的请求，
 * 白白让用户点一次。
 */
const canAccept = computed(() => order.value?.status === "PENDING_ACCEPT");
const canStart = computed(() => order.value?.status === "ACCEPTED");
const canFinish = computed(() => order.value?.status === "IN_SERVICE");

/**
 * 能不能给动作按钮。
 *
 * **刷新失败 = 状态不可信 = 不给动作按钮**：
 * 动作返回 404 之后代码会再拉一次详情；如果这次刷新也 404，
 * `order` 里还留着旧值，模板照样按旧状态渲染「开始服务」——
 * 用户可以再点一次、再撞一次 404。
 *
 * 这里的 `loadError` 非空就是「我们没确认这单还在」，
 * 这时候给按钮等于给一个必然失败的按钮。
 *
 * 注意别误伤：404 冲突后**刷新成功**时 loadError 是空的，
 * 按钮照常给（而且状态要跟着刷新后的新状态走）；
 * 409（师傅当前不可接单）压根不刷新，loadError 一直空着，按钮照常给。
 */
const canAct = computed(() => Boolean(order.value) && loadError.value === "");

onMounted(load);

async function load(): Promise<void> {
  loading.value = true;
  loadError.value = "";
  try {
    order.value = await api.getMasterOrder({ order_no: orderNo.value });
  } catch (err) {
    // 业务错显示后端原话，网络错给统一文案（见 utils/error.ts）
    loadError.value = errorMessage(err, "订单加载失败");
  } finally {
    loading.value = false;
  }
}

/**
 * 「订单侧冲突」——也就是「这单的状态跟我想的不一样，只有重新拉详情才知道」。
 *
 * 师傅端四个写接口（accept / reject / start / finish）里，
 * **订单侧的失败一律是 404**：订单不存在 / 不是派给我的 / 状态已变，
 * 后端刻意同构成一个 404（不让调用方靠报错差异探测，R1；
 * 见 apps/api/app/services/master_action.py 与 service_flow.py）。
 * 所以「订单状态变了」只从 404 判断。
 *
 * **409 不是订单侧冲突**：409 = MasterNotDispatchableError =
 * 「师傅当前不可接单：master_id=N」（停用 / 休假 / 未审核）。
 * 订单状态压根没变，刷新详情学不到任何东西——刷新只会白白多一次往返，
 * 而且可能把「不可接单」这个真正的原因盖住。所以 409 不刷新。
 */
function isOrderSideConflict(err: unknown): boolean {
  return err instanceof ApiError && err.status === 404;
}

/**
 * 做一个订单动作。
 *
 * **动作与收尾分开 catch**：两者的失败含义完全不同。
 *
 * - 动作失败 = 这次操作没生效，用户需要知道后端为什么拒绝；
 * - 收尾失败 = 动作**已经成功了**，只是页面没跟上（比如拒单成功后
 *   跳列表的导航挂了）。这时报「操作失败」是骗人的：后端已经把单退回
 *   PENDING_DISPATCH，师傅再点一次「确认拒单」只会得到第二次失败。
 *
 * @param action 真正发请求的动作
 * @param onSuccess 成功后的收尾：接单/开工/完工要刷新详情，拒单要跳回列表
 */
async function act(
  action: () => Promise<unknown>,
  onSuccess?: () => Promise<void> | void,
): Promise<void> {
  // 连点守卫：光靠按钮的 loading/disabled 不够——两次点击之间 Vue 还没
  // patch 出 disabled，第二次点击照样进得来（与 UI-01 / UI-02 的做法一致）。
  // 这里在发请求**之前**同步把 busy 置 true，第二次进来直接 return。
  if (busy.value) return;

  busy.value = true;
  actionError.value = "";
  try {
    try {
      await action();
    } catch (err) {
      if (isOrderSideConflict(err)) {
        // 订单侧冲突（404）：带上后端原话，再刷新一次拿真实状态。
        // 刷新只动 loadError，**不会把 actionError 冲掉**——
        // 用户还得看到后端那句话（不然就只剩一句「状态变了」）。
        actionError.value = errorMessage(err, "订单状态已变化");
        await load();
      } else {
        // 409（师傅当前不可接单）/ 500 等：**不刷新**。
        // 409 的话订单状态没变，刷新学不到东西，只会把真正的原因盖住；
        // 500 更没理由刷新。动作按钮照常留着（loadError 是空的），
        // 因为后端明确允许停用 / 休假的师傅**拒单**——那是他把手上的单退回去的
        // 唯一出路，藏掉按钮等于把单卡死在他手上。
        actionError.value = errorMessage(err, "操作失败，请重试");
      }
      // 动作本身失败了：收尾不该跑（收尾是给成功后的状态做的）。
      return;
    }

    // 动作成功了才做收尾。收尾失败（刷新详情 / 跳回列表出错）**不是操作失败**——
    // 动作已经生效了，报「操作失败」会让用户以为没成功、白点一次。
    try {
      await onSuccess?.();
    } catch (err) {
      actionError.value = "操作已完成，但页面没能自动更新，请点「返回列表」";
    }
  } finally {
    busy.value = false;
  }
}

async function accept(): Promise<void> {
  // 接单成功：状态变了，重新拉一次详情，状态标签与按钮跟着变
  await act(() => api.acceptOrder({ order_no: orderNo.value }), load);
}

async function start(): Promise<void> {
  await act(() => api.startService({ order_no: orderNo.value }), load);
}

async function finish(): Promise<void> {
  await act(() => api.finishService({ order_no: orderNo.value }), load);
}

/**
 * 拒单。
 *
 * 成功之后**绝对不能刷新详情**：后端把订单退回 PENDING_DISPATCH 并清空
 * master_id，这单已经不属于我了，详情接口会 404（刷新 = 白屏 + 404）。
 * 所以改成记一条回执（「已拒单」）然后跳回列表。
 *
 * **失败时弹窗不关**：关掉的话用户得重新打开弹窗、重填一遍原因
 * （RejectPopup 每次打开都清空输入），才能知道刚才到底成没成。
 * 留在原地 + 保留原因 = 用户能直接再点一次「确认拒单」重试。
 * 后端原话显示在弹窗里（用户视线所在处），不写在页面顶部。
 */
async function reject(reason: string): Promise<void> {
  await act(
    () => api.rejectOrder({ order_no: orderNo.value }, { reason }),
    async () => {
      // 到这里说明动作成功了：这时才关弹窗（失败的话弹窗要留着重试）
      rejectVisible.value = false;
      setNotice("已拒单");
      // 用 replace 而不是 push：这单已经 404 了，留着历史记录的话
      // 用户一按后退就又撞回 404。
      await router.replace("/orders");
    },
  );
}

/**
 * 打开拒单弹窗。
 *
 * **先把上一次的错误清掉**：弹窗里会显示后端原话（serverError），
 * 带着上一次动作的错误（比如刚才接单失败）打开弹窗，
 * 用户会以为这次拒单也失败了。
 */
function openReject(): void {
  actionError.value = "";
  rejectVisible.value = true;
}

/**
 * 回列表页（错误块里的「返回列表」按钮）。
 *
 * 同样用 replace：这个详情页可能已经不存在了（拒单后 / 订单被收走），
 * 留着历史记录只会让用户后退又撞一次 404。
 */
function goList(): void {
  void router.replace("/orders");
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">订单详情</h2>

    <!-- 已经有订单数据时就不再用加载动画盖住页面：刷新别把内容抽走 -->
    <van-loading v-if="loading && !order" size="24" data-test="loading">加载中</van-loading>

    <!--
      错误块：两个错误源互斥（v-if / v-else-if），「返回列表」按钮
      永远只出现一次。订单内容在下面照常渲染 —— 出错时页面不白屏。

      两个块都带 `&& !rejectVisible`：拒单失败时错误显示在**弹窗里**
      （用户视线所在处），页面顶部就**一个都不渲染**。
      为什么两个都要带：拒单 404 之后代码会再拉一次详情，这次刷新
      也可能 404，于是 actionError 与 loadError 同时非空、而且是同一句
      后端原话（「订单不存在：order_no=…」）。只给第一个块加条件的话，
      第二个块照样会把同一句话在页面顶部再显示一遍（还多一个「重试」），
      用户看到的是同一条错误出现两次。
      关掉弹窗后（rejectVisible = false）页面顶部才重新出现错误块，
      那时两块的互斥关系由 v-if / v-else-if 保证，「返回列表」仍然只有一个。
    -->
    <div
      v-if="actionError && !rejectVisible"
      class="page-block"
      data-test="action-error"
    >
      <p class="page-error" data-test="action-error-text">{{ actionError }}</p>
      <van-button
        size="small"
        plain
        type="primary"
        data-test="back-to-list"
        @click="goList"
      >
        返回列表
      </van-button>
    </div>
    <div
      v-else-if="loadError && !rejectVisible"
      class="page-block"
      data-test="error-block"
    >
      <p class="page-error" data-test="error">{{ loadError }}</p>
      <!--
        首屏加载失败给「重试」：用户能做的就是再拉一次，
        让他退回列表再点进订单太绕了。与列表页的错误块保持一致
        （列表页的「重试」在 OrdersView.vue，同样是 data-test="retry"）。
        「返回列表」也留着——重试是出路之一，不是唯一出路。
      -->
      <van-button
        size="small"
        plain
        type="primary"
        data-test="retry"
        @click="load"
      >
        重试
      </van-button>
      <van-button
        size="small"
        plain
        type="primary"
        data-test="back-to-list"
        @click="goList"
      >
        返回列表
      </van-button>
    </div>

    <template v-if="order">
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
        <van-cell title="客户" :value="order.customer_contact" data-test="customer" />
        <van-cell title="客户电话" :value="order.customer_phone" />
        <van-cell title="上门地址">
          <template #value>
            <span data-test="address">
              {{ order.address_region }} {{ order.address_detail }}
            </span>
          </template>
        </van-cell>
      </van-cell-group>

      <div class="page-footer">
        <!--
          按钮按订单状态给：待接单 -> 接单/拒单，已接单 -> 开始服务，
          服务中 -> 完成服务。**其他状态一个按钮都不给**
          （状态不对时后端回 404，师傅不可接单时回 409，都是必然失败的请求）。
        -->
        <!--
          canAct：详情刷新失败时**整个按钮组都不给**。
          理由：刷新失败 = 状态不可信 = 点了也只会再撞一次 404 / 409
          （订单内容照旧在页面上，不白屏；错误块里有「返回列表」）。
        -->
        <template v-if="canAct">
          <template v-if="canAccept">
            <van-button
              type="primary"
              block
              :loading="busy"
              :disabled="busy"
              data-test="accept-button"
              @click="accept"
            >
              接单
            </van-button>
            <van-button
              block
              :loading="busy"
              :disabled="busy"
              data-test="reject-button"
              @click="openReject"
            >
              拒单
            </van-button>
          </template>
          <van-button
            v-else-if="canStart"
            type="primary"
            block
            :loading="busy"
            :disabled="busy"
            data-test="start-button"
            @click="start"
          >
            开始服务
          </van-button>
          <van-button
            v-else-if="canFinish"
            type="primary"
            block
            :loading="busy"
            :disabled="busy"
            data-test="finish-button"
            @click="finish"
          >
            完成服务
          </van-button>
        </template>
      </div>
    </template>

    <!--
      拒单弹窗：后端原话透传进弹窗（用户视线所在处）。
      loading 传 busy：拒单请求是弹窗里那个「确认拒单」按钮发出的，
      请求在途时那个按钮要显示 loading（详情页上的「拒单」按钮被弹窗挡住了，
      用户看不见它的 loading）。
      列表页不传这两个 prop，行为不变。
    -->
    <RejectPopup
      v-model:show="rejectVisible"
      :server-error="actionError"
      :loading="busy"
      @confirm="reject"
    />
  </div>
</template>
