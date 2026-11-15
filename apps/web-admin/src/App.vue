<!--
  后台外壳：顶栏 + 路由出口。

  顶栏显示当前登录的账号与服务商归属（provider_id）：
  服务商后台的人一眼要能看出「我现在看的是哪个服务商的数据」。
-->
<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";
import { ElButton, ElContainer, ElHeader, ElMain } from "element-plus";

import { useSessionStore } from "@/stores/session";

const session = useSessionStore();
const router = useRouter();

const providerLabel = computed(() => {
  const id = session.currentUser?.provider_id;
  return id == null ? "（无服务商归属）" : `服务商 #${id}`;
});

function logout(): void {
  session.clear();
  router.replace({ name: "login" });
}
</script>

<template>
  <el-container>
    <el-header class="app-header">
      <span class="app-title">OTO 服务商后台</span>
      <nav class="app-nav" data-test="app-nav">
        <router-link class="app-nav-link" to="/provider/dispatch">派单</router-link>
        <router-link class="app-nav-link" to="/provider/masters">师傅管理</router-link>
        <!-- 平台侧菜单：只有平台管理员看得到（真正的边界在后端 403） -->
        <router-link
          v-if="session.isPlatformAdmin"
          class="app-nav-link"
          data-test="platform-providers-link"
          to="/platform/providers"
        >
          服务商管理
        </router-link>
      </nav>
      <div v-if="session.isLoggedIn" class="app-user">
        <span data-test="current-user">
          {{ session.currentUser?.nickname }} · {{ providerLabel }}
        </span>
        <el-button link type="primary" data-test="logout" @click="logout">
          退出
        </el-button>
      </div>
    </el-header>

    <el-main>
      <router-view />
    </el-main>
  </el-container>
</template>

<style scoped>
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background-color: #fff;
  border-bottom: 1px solid #e4e7ed;
}

.app-title {
  font-weight: 600;
}

.app-nav {
  display: flex;
  align-items: center;
  gap: 16px;
}

.app-nav-link {
  color: #606266;
  text-decoration: none;
}

.app-nav-link:hover {
  color: #409eff;
}

.app-user {
  display: flex;
  align-items: center;
  gap: 12px;
}
</style>
