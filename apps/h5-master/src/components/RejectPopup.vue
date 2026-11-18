<script setup lang="ts">
/**
 * 拒单原因弹窗（列表页与详情页共用）。
 *
 * 拒单必须带原因：原因会原样写进订单状态流转日志（后端 order_status_log.reason），
 * 服务商与平台要能看出这单为什么被退回去。
 *
 * 原因由**师傅自己填**，这里只做非空校验——后端也要求非空。
 *
 * **传了 `loading` 时，请求在途不许关弹窗**：拒单请求一旦发出，
 * 后端就把单真拒掉了。这时候关弹窗（点「取消」/ 点遮罩）**不是撤销**，
 * 只是把结果藏起来——用户以为「取消了这单」，实际单已经被拒，
 * 用户完全不知情（静默拒单）。所以 loading 为真时「取消」按钮 disabled，
 * 遮罩那条关闭路径也一并挡掉（用 Vant 的 close-on-click-overlay，
 * 详见模板里的注释——**不能靠吞掉 update:show 事件来实现**）。
 *
 * 这条保护**只对传了 `loading` 的调用方生效**（目前只有详情页）。
 * 列表页不传 `loading`：它在发请求**之前**就把弹窗关掉了（UI-01 的既有
 * 行为，本卡没动）——列表页拒单后订单会直接从列表里消失，用户看得到结果，
 * 不存在「以为拒了其实没拒」的静默问题。
 *
 * teleport=null：内容就地渲染，不传送到 body。
 * 传送到 body 的话，测试里 wrapper 根本找不到这个弹窗的内容。
 */
import { ref, watch } from "vue";

const props = defineProps<{
  show: boolean;
  /**
   * 后端返回的失败原因（可选）。
   *
   * 拒单失败时用户**视线在弹窗上**（他刚点了「确认拒单」），
   * 错误写在页面顶部的提示条里他根本看不见。详情页把动作错误透传进来，
   * 让失败原因显示在弹窗内——用户能立刻看到成没成、能不能直接重试。
   *
   * 不传（列表页）时行为完全不变：只有本地的空值校验错误。
   */
  serverError?: string;
  /**
   * 请求在途（可选）。
   *
   * 拒单请求是**弹窗里的「确认拒单」按钮**发出的，所以「请求中」的
   * 反馈必须落在这个按钮上：loading + disabled，让用户知道
   * 「已经点下去了、在处理」，而不是以为没点上又点一次。
   *
   * 同时它也是「**能不能关弹窗**」的依据：请求一旦发出，后端就会把单
   * 真的拒掉，这时候关弹窗不是「撤销」，只是把结果藏起来（静默拒单）。
   * 不传（列表页）时按钮外观与关闭行为完全不变。
   */
  loading?: boolean;
}>();
const emit = defineEmits<{
  "update:show": [value: boolean];
  confirm: [reason: string];
}>();

const reason = ref("");
/** 本地的空值校验错误（跟后端原因分开存，两条同时显示、互不覆盖）。 */
const reasonError = ref("");

// 每次打开都清空上一次的输入（免得把上一单的原因带给这一单）
watch(
  () => props.show,
  (visible) => {
    if (visible) {
      reason.value = "";
      reasonError.value = "";
    }
  },
);

// 原因一填上，之前那条「请填写拒单原因」就不成立了——清掉。
// 不清的话它会一直挂在弹窗里（用户填好原因、那条错误还在），
// 甚至和后端原话并排显示两条错误，其中一条已经不成立了。
watch(reason, (text) => {
  if (text.trim()) reasonError.value = "";
});

function close(): void {
  // 请求已发出，取消不是撤销——后端会把单真的拒掉。
  // 这时候关掉弹窗，用户以为「取消了这单」，实际上单已经被拒了
  // （静默拒单，用户完全不知情）。所以请求在途时不许关。
  // 「取消」按钮已经 disabled 了，这里再挡一道：以后谁把那个 disabled
  // 去掉，close() 也不会把关掉的弹窗放出去。
  if (props.loading) return;
  emit("update:show", false);
}

function confirm(): void {
  const text = reason.value.trim();
  if (!text) {
    reasonError.value = "请填写拒单原因";
    return;
  }
  emit("confirm", text);
}
</script>

<template>
  <!--
    遮罩那条关闭路径的拦截方式：**用 Vant 官方的 close-on-click-overlay**，
    而不是「吞掉 update:show 事件」。

    为什么不能吞事件：Vant 的 close() 是**先**把内部的 opened 置成 false、
    **再** emit update:show(false)。如果我们把这个 emit 吞掉（父组件的 show
    还是 true，弹窗照常显示），Vant 内部的 opened 却已经是 false 了。
    而 opened 只有在 show 由假变真时才会被 open() 重置 —— 也就是说
    **本次打开期间，遮罩那条关闭路径从此永久失效**：请求在途时点过一次
    遮罩被挡住，等请求结束（loading 变 false）再点遮罩，弹窗纹丝不动。

    改成 :close-on-click-overlay="!loading" 就没有这个问题：loading 为真时
    Vant 根本不进 close()（opened 保持 true），loading 变回 false 后遮罩
    又恢复正常关闭，Vant 内部状态跟 show prop 始终一致。
  -->
  <van-popup
    :show="show"
    position="bottom"
    round
    :teleport="null"
    :close-on-click-overlay="!loading"
    @update:show="emit('update:show', $event)"
  >
    <div class="reject-popup" data-test="reject-popup">
      <p class="reject-popup-title">拒单原因</p>
      <van-field
        v-model="reason"
        type="text"
        maxlength="100"
        placeholder="请输入拒单原因"
        data-test="reject-reason"
      />
      <p v-if="reasonError" class="page-error" data-test="reject-error">
        {{ reasonError }}
      </p>
      <!-- 后端原话（可选）：与上面的空值校验错误分开、两条可同时显示 -->
      <p v-if="serverError" class="page-error" data-test="reject-server-error">
        {{ serverError }}
      </p>
      <div class="reject-popup-actions">
        <!--
          「取消」在请求在途时 disabled：请求**已经发出去了**，取消不是撤销——
          后端会把单真的拒掉。让按钮不可点，避免用户以为撤销了（静默拒单）。
          真要撤销请求得用 AbortController 撤掉，那是另一件事。
        -->
        <van-button :disabled="loading" data-test="reject-cancel" @click="close">
          取消
        </van-button>
        <!--
          loading / disabled 都绑到「确认拒单」上：拒单请求是这个按钮发出的，
          请求在途时按钮外观要变（不然用户以为没点上）。
          loading 是可选 prop，列表页不传 = 行为不变。
        -->
        <van-button
          type="primary"
          :loading="loading"
          :disabled="loading"
          data-test="reject-confirm"
          @click="confirm"
        >
          确认拒单
        </van-button>
      </div>
    </div>
  </van-popup>
</template>
