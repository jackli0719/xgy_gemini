<!--
  后台外壳：顶栏 + 路由出口。

  顶栏显示当前登录的账号与服务商归属（provider_id）：
  服务商后台的人一眼要能看出「我现在看的是哪个服务商的数据」。

  **顶栏标题与菜单都按角色走**（PLAT-02 修的 PLAT-01 遗留）：
  - 平台账号看的是「平台管理后台」，菜单里只有平台侧的页面；
  - 服务商账号看的是「服务商后台」，菜单里只有服务商侧的页面。
  平台账号点进服务商页面会拿到 403（后端的边界），所以干脆不显示。
-->
<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";
import { ElButton, ElContainer, ElHeader, ElMain } from "element-plus";

import { useSessionStore } from "@/stores/session";
import { appTitleForRole } from "@/utils/role";

const session = useSessionStore();
const router = useRouter();

const providerLabel = computed(() => {
  const id = session.currentUser?.provider_id;
  return id == null ? "（无服务商归属）" : `服务商 #${id}`;
});

/** 顶栏标题：平台账号与服务商账号看到的不是同一个后台。 */
const appTitle = computed(() => `OTO ${appTitleForRole(session.currentUser?.role)}`);

function logout(): void {
  session.clear();
  router.replace({ name: "login" });
}
</script>

<template>
  <el-container>
    <el-header class="app-header">
      <span class="app-title" data-test="app-title">{{ appTitle }}</span>
      <nav class="app-nav" data-test="app-nav">
        <!-- 服务商侧菜单：只有服务商角色看得到 -->
        <template v-if="session.isProviderRole">
          <router-link class="app-nav-link" to="/provider/dispatch">派单</router-link>
          <router-link class="app-nav-link" to="/provider/masters">师傅管理</router-link>
        </template>
        <!-- 平台侧菜单：只有平台角色看得到（真正的边界在后端 403） -->
        <template v-if="session.isPlatformStaff">
          <router-link
            v-if="session.isPlatformAdmin"
            class="app-nav-link"
            data-test="platform-providers-link"
            to="/platform/providers"
          >
            服务商管理
          </router-link>
          <router-link
            class="app-nav-link"
            data-test="platform-orders-link"
            to="/platform/orders"
          >
            订单总览
          </router-link>
          <router-link
            class="app-nav-link"
            data-test="platform-categories-link"
            to="/platform/categories"
          >
            品类管理
          </router-link>
          <!--
            入驻审核：只有平台管理员能审（跟「服务商管理」一样）。
            运营 / 财务点进去只会拿到 403，所以不给他们显示。
          -->
          <router-link
            v-if="session.isPlatformAdmin"
            class="app-nav-link"
            data-test="platform-master-review-link"
            to="/platform/masters/review"
          >
            入驻审核
          </router-link>
        </template>
        <!--
          结算确认：平台财务与平台管理员看得到。
          单独一块，不跟上面的运营菜单混：财务进不了订单总览 / 品类管理
          （后端只放 PLATFORM_ADMIN / PLATFORM_OPS），混在一起会让它
          点进去只拿到 403。
        -->
        <template v-if="session.isPlatformFinance || session.isPlatformAdmin">
          <router-link
            class="app-nav-link"
            data-test="platform-settlements-link"
            to="/platform/settlements"
          >
            结算确认
          </router-link>
        </template>
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
