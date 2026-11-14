<script setup lang="ts">
/**
 * 应用外壳：顶部导航 + 路由出口。
 *
 * 样式全部用 Vant 默认主题，不写自定义主题（卡片约束）。
 */
</script>

<template>
  <div class="app">
    <van-nav-bar title="OTO 家政">
      <template #right>
        <router-link to="/orders">订单</router-link>
      </template>
    </van-nav-bar>

    <main class="app-main">
      <router-view />
    </main>

    <van-tabbar route>
      <van-tabbar-item to="/catalog" icon="apps-o">品类</van-tabbar-item>
      <van-tabbar-item to="/orders" icon="orders-o">我的订单</van-tabbar-item>
    </van-tabbar>
  </div>
</template>
