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

const props = defineProps<{ show: boolean }>();
const emit = defineEmits<{
  "update:show": [value: boolean];
  confirm: [reason: string];
}>();

const reason = ref("");
const error = ref("");

// 每次打开都清空上一次的输入（免得把上一单的原因带给这一单）
watch(
  () => props.show,
  (visible) => {
    if (visible) {
      reason.value = "";
      error.value = "";
    }
  },
);

function close(): void {
  emit("update:show", false);
}

function confirm(): void {
  const text = reason.value.trim();
  if (!text) {
    error.value = "请填写拒单原因";
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
      <p v-if="error" class="page-error" data-test="reject-error">{{ error }}</p>
      <div class="reject-popup-actions">
        <van-button data-test="reject-cancel" @click="close">取消</van-button>
        <van-button type="primary" data-test="reject-confirm" @click="confirm">
          确认拒单
        </van-button>
      </div>
    </div>
  </van-popup>
</template>
