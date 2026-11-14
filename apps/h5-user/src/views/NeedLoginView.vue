<script setup lang="ts">
/**
 * 「请先登录」占位页。
 *
 * 卡片要求：本卡不写登录页，没有 token 时提示「请先登录」。
 * 真正的登录页属于 FE-03。
 */

import { useRouter } from "vue-router";

const router = useRouter();

function backToCatalog(): void {
  void router.push("/catalog");
}
</script>

<template>
  <div class="page">
    <van-empty image="error" description="请先登录">
      <p class="page-error" data-test="need-login">请先登录</p>
      <van-button size="small" plain @click="backToCatalog">返回品类</van-button>
    </van-empty>
  </div>
</template>
