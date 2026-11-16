<script setup lang="ts">
/**
 * 应用外壳：顶部导航（带上我的资料）+ 路由出口。
 *
 * 资料来自 api.getMasterProfile()（GET /api/v1/master/profile）：
 * 师傅是谁、属于哪家公司、当前是什么状态，全由服务端按 token 决定，
 * 前端只是显示（不缓存、不外传）。
 *
 * **「申请入驻」的入口**：还没入职的师傅（资料拿不到 = 不是师傅）
 * 或还在审核中的师傅，导航栏给一个入口进申请页——不然这个页面
 * 真实链路上没人能走到（后端 /orders 要 MASTER 角色，没入职的
 * 账号打不开）。已入职的不给这个入口。
 *
 * 样式全部用 Vant 默认主题，不写自定义主题（卡片约束）。
 */
import { computed, onMounted, ref } from "vue";

import { api } from "@/api";
import type { components } from "@oto/shared/api";

type MasterProfile = components["schemas"]["MasterProfile"];

const profile = ref<MasterProfile | null>(null);
/** 资料问过了没有（用来区分「不是师傅」与「还没问」）。 */
const profileLoaded = ref(false);

onMounted(async () => {
  try {
    profile.value = await api.getMasterProfile();
  } catch {
    // 拿不到资料不挡页面（详情与列表才是主流程）
    profile.value = null;
  } finally {
    profileLoaded.value = true;
  }
});

/** 要不要给「申请入驻」的入口：不是师傅，或者还在审核中。 */
const showOnboardingLink = computed(
  () => profileLoaded.value && (!profile.value || profile.value.status !== "ACTIVE"),
);
</script>

<template>
  <div class="app">
    <van-nav-bar title="OTO 家政 · 师傅端">
      <template #right>
        <router-link to="/orders">订单</router-link>
        <router-link
          v-if="showOnboardingLink"
          to="/onboard"
          data-test="onboard-link"
        >
          申请入驻
        </router-link>
      </template>
    </van-nav-bar>

    <p v-if="profile" class="app-profile" data-test="profile">
      {{ profile.real_name }} · {{ profile.provider_name }}
      <van-tag type="primary" plain>{{ profile.status }}</van-tag>
    </p>

    <main class="app-main">
      <router-view />
    </main>
  </div>
</template>
