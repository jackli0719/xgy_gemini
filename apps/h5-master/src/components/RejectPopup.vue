<script setup lang="ts">
/**
 * 拒单原因弹窗（列表页与详情页共用）。
 *
 * 拒单必须带原因：原因会原样写进订单状态流转日志（后端 order_status_log.reason），
 * 服务商与平台要能看出这单为什么被退回去。
 *
 * 原因由**师傅自己填**，这里只做非空校验——后端也要求非空。
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
   * 不传（列表页）时按钮外观完全不变。
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

function close(): void {
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
  <van-popup
    :show="show"
    position="bottom"
    round
    :teleport="null"
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
        <van-button data-test="reject-cancel" @click="close">取消</van-button>
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
