<!--
  师傅管理页：本商师傅列表 + 启用/停用。

  两步：
  1. 打开页面拉本商师傅；
  2. 点「停用 / 启用」-> 调 PATCH /provider/masters/{master_id} -> 成功后**重新拉列表**。

  归属问题：前端**不带 provider_id**。服务商是谁由后端按 token 决定，
  这里只是调普通的列表 / 修改接口。

  状态标签用 el-tag 区分颜色：一眼能看出谁在岗、谁休假、谁被停用。

  UI-03 打磨的重点：
  - 空状态：一句「暂无师傅」+ 刷新按钮，不是一张空表；
  - 状态切换中：按钮显示 loading 并禁用，连点只改一次。
-->
<script setup lang="ts">
import { onMounted, ref } from "vue";
import {
  ElButton,
  ElEmpty,
  ElMessage,
  ElTable,
  ElTableColumn,
  ElTag,
  vLoading,
} from "element-plus";
import { ApiError, type Schemas } from "@oto/shared/api";

import { api } from "@/api";

type ProviderMasterItem = Schemas["ProviderMasterItem"];

/** 本商师傅。 */
const masters = ref<ProviderMasterItem[]>([]);
const loading = ref(false);
const errorText = ref("");
/** 正在改状态的师傅 id（用来把那一行的按钮置灰）。 */
const changing = ref<number | null>(null);

/** 状态 -> 中文文案与 tag 颜色。 */
const STATUS_TEXT: Record<ProviderMasterItem["status"], string> = {
  PENDING: "待审核",
  ACTIVE: "在岗",
  ON_LEAVE: "休假",
  DISABLED: "已停用",
};

/** tag 颜色：Element Plus 的 type。 */
const STATUS_TAG_TYPE: Record<
  ProviderMasterItem["status"],
  "primary" | "success" | "info" | "warning" | "danger"
> = {
  PENDING: "info",
  ACTIVE: "success",
  ON_LEAVE: "warning",
  DISABLED: "danger",
};

function statusText(status: ProviderMasterItem["status"]): string {
  return STATUS_TEXT[status];
}

function statusTagType(status: ProviderMasterItem["status"]) {
  return STATUS_TAG_TYPE[status];
}

/** 在岗的可以停用；其余状态点「启用」回到在岗。 */
function toggleLabel(status: ProviderMasterItem["status"]): string {
  return status === "ACTIVE" ? "停用" : "启用";
}

/** 拉师傅列表。改完状态也要再调一次（刷新列表）。 */
async function load(): Promise<void> {
  loading.value = true;
  errorText.value = "";
  try {
    const result = await api.listProviderMasters();
    masters.value = result.items;
  } catch (err) {
    errorText.value = err instanceof ApiError ? err.detail : "加载失败，请稍后再试";
  } finally {
    loading.value = false;
  }
}

async function toggleStatus(row: ProviderMasterItem): Promise<void> {
  // 同步守卫：改状态请求在途时再点一次直接返回，
  // 免得同一个师傅连发两次 PATCH（第二次多半是 409）。
  if (changing.value !== null) return;

  const next = row.status === "ACTIVE" ? "DISABLED" : "ACTIVE";
  changing.value = row.id;
  try {
    await api.updateProviderMaster({ master_id: row.id }, { status: next });
    ElMessage.success(next === "ACTIVE" ? "已启用" : "已停用");
    // 改完刷新列表：表格里那一行的状态以服务端为准
    await load();
  } catch (err) {
    ElMessage.error(err instanceof ApiError ? err.detail : "操作失败，请稍后再试");
  } finally {
    changing.value = null;
  }
}

onMounted(() => {
  void load();
});
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2 class="page-title">师傅管理</h2>
      <el-button data-test="reload" :loading="loading" @click="load">
        刷新
      </el-button>
    </div>

    <p v-if="errorText" class="error-text" data-test="error">{{ errorText }}</p>

    <!-- 空状态：一句人话 + 一个刷新按钮，不是一张空表让人猜 -->
    <div
      v-if="!loading && !errorText && masters.length === 0"
      class="empty-block"
      data-test="masters-empty"
    >
      <el-empty description="暂无师傅">
        <el-button data-test="masters-empty-refresh" @click="load">
          刷新
        </el-button>
      </el-empty>
    </div>

    <el-table v-else v-loading="loading" :data="masters" border stripe>
      <el-table-column prop="real_name" label="姓名" min-width="140" />
      <el-table-column prop="phone" label="手机号" min-width="140" />
      <el-table-column label="评分" width="100" align="right">
        <template #default="{ row }">
          {{ row.rating == null ? "暂无评分" : row.rating }}
        </template>
      </el-table-column>
      <el-table-column label="状态" width="110" align="center">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)">
            {{ statusText(row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="100" align="center">
        <!--
          el-table 的插槽行类型是宽松的 DefaultRow，这里显式断言回
          ProviderMasterItem：表格里的数据就是我们自己塞进去的 masters，
          类型不会比它更差。
        -->
        <template #default="{ row }">
          <el-button
            type="primary"
            link
            data-test="toggle-btn"
            :loading="changing === row.id"
            :disabled="changing !== null"
            @click="toggleStatus(row as ProviderMasterItem)"
          >
            {{ toggleLabel(row.status) }}
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>
