<!--
  平台侧服务商管理页（PLAT-01）。

  四件事：
  1. 打开页面拉服务商列表；
  2. 「新建服务商」-> 弹窗填名称 / 联系电话 / 佣金比例 -> 提交；
  3. 每行按状态显示一个动作：审核通过（PENDING）/ 冻结（ACTIVE）/
     解冻（FROZEN）——点完调 PATCH，成功后**重新拉列表**；
  4. 「创建管理员」-> 弹窗填手机号 -> 提交。

  身份问题：这一页只有 PLATFORM_ADMIN 能用（路由守卫按角色拦，
  见 router/index.ts）。但**操作人身份不是前端传的**——服务端从 token
  里取 role 与 user_id 写审计日志。前端只说「要改哪一家服务商」
  （provider_id 是路径参数）。
-->
<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import {
  ElButton,
  ElDialog,
  ElForm,
  ElFormItem,
  ElInput,
  ElInputNumber,
  ElMessage,
  ElTable,
  ElTableColumn,
  ElTag,
  vLoading,
} from "element-plus";
import { ApiError, type Schemas } from "@oto/shared/api";

import { api } from "@/api";

type PlatformProviderItem = Schemas["PlatformProviderItem"];
type ProviderStatus = PlatformProviderItem["status"];

/** 服务商列表。 */
const providers = ref<PlatformProviderItem[]>([]);
const loading = ref(false);
const errorText = ref("");
/** 正在改状态的服务商 id（把那一行的按钮置灰）。 */
const changing = ref<number | null>(null);

/** 状态 -> 中文文案与 tag 颜色。 */
const STATUS_TEXT: Record<ProviderStatus, string> = {
  PENDING: "待审核",
  ACTIVE: "营业中",
  FROZEN: "已冻结",
  // 两个废弃取值：库里还留着（枚举删不掉），但没有任何代码会写它们
  SUSPENDED: "已停用",
  CLOSED: "已关闭",
};

/** tag 颜色：Element Plus 的 type。 */
const STATUS_TAG_TYPE: Record<
  ProviderStatus,
  "primary" | "success" | "info" | "warning" | "danger"
> = {
  PENDING: "info",
  ACTIVE: "success",
  FROZEN: "danger",
  SUSPENDED: "warning",
  CLOSED: "info",
};

/** 每个状态对应的动作（没有动作的状态返回 null）。 */
const STATUS_ACTION: Record<
  ProviderStatus,
  { label: string; next: "ACTIVE" | "FROZEN" } | null
> = {
  PENDING: { label: "审核通过", next: "ACTIVE" },
  ACTIVE: { label: "冻结", next: "FROZEN" },
  FROZEN: { label: "解冻", next: "ACTIVE" },
  SUSPENDED: null,
  CLOSED: null,
};

function statusText(status: ProviderStatus): string {
  return STATUS_TEXT[status];
}

function statusTagType(status: ProviderStatus) {
  return STATUS_TAG_TYPE[status];
}

function statusAction(status: ProviderStatus) {
  return STATUS_ACTION[status];
}

/** 佣金比例显示成百分比（库里存的是 0~1 的小数）。 */
function formatRate(rate: string): string {
  const value = Number(rate);
  if (!Number.isFinite(value)) return rate;
  return `${(value * 100).toFixed(2)}%`;
}

/** 拉服务商列表。改完状态 / 建完账号也要再调一次（刷新列表）。 */
async function load(): Promise<void> {
  loading.value = true;
  errorText.value = "";
  try {
    const result = await api.listPlatformProviders();
    providers.value = result.items;
  } catch (err) {
    errorText.value = err instanceof ApiError ? err.detail : "加载失败，请稍后再试";
  } finally {
    loading.value = false;
  }
}

// ---------------------------------------------------------------------
// 新建服务商
// ---------------------------------------------------------------------

const createVisible = ref(false);
const creating = ref(false);
/** 新建表单。初始状态由服务端定（待审核），这里不传 status。 */
const createForm = reactive({
  name: "",
  contact_phone: "",
  commission_rate: 0.15,
});

function openCreate(): void {
  createForm.name = "";
  createForm.contact_phone = "";
  createForm.commission_rate = 0.15;
  createVisible.value = true;
}

async function submitCreate(): Promise<void> {
  if (!createForm.name.trim()) {
    ElMessage.warning("请填写服务商名称");
    return;
  }
  if (!createForm.contact_phone.trim()) {
    ElMessage.warning("请填写联系电话");
    return;
  }
  creating.value = true;
  try {
    await api.createProvider({
      name: createForm.name.trim(),
      contact_phone: createForm.contact_phone.trim(),
      commission_rate: createForm.commission_rate,
    });
    ElMessage.success("已创建，等待审核");
    createVisible.value = false;
    await load();
  } catch (err) {
    ElMessage.error(err instanceof ApiError ? err.detail : "创建失败，请稍后再试");
  } finally {
    creating.value = false;
  }
}

// ---------------------------------------------------------------------
// 改状态（审核通过 / 冻结 / 解冻）
// ---------------------------------------------------------------------

async function changeStatus(row: PlatformProviderItem): Promise<void> {
  const action = statusAction(row.status);
  if (!action) return;
  changing.value = row.id;
  try {
    await api.updateProviderStatus({ provider_id: row.id }, { status: action.next });
    ElMessage.success(action.label + "成功");
    // 改完刷新列表：表格里那一行的状态以服务端为准
    await load();
  } catch (err) {
    ElMessage.error(err instanceof ApiError ? err.detail : "操作失败，请稍后再试");
  } finally {
    changing.value = null;
  }
}

// ---------------------------------------------------------------------
// 创建服务商管理员
// ---------------------------------------------------------------------

const adminVisible = ref(false);
const adminCreating = ref(false);
/** 正在建管理员的服务商。 */
const adminTarget = ref<PlatformProviderItem | null>(null);
const adminForm = reactive({ phone: "" });

function openAdmin(row: PlatformProviderItem): void {
  adminTarget.value = row;
  adminForm.phone = "";
  adminVisible.value = true;
}

async function submitAdmin(): Promise<void> {
  const target = adminTarget.value;
  if (!target) return;
  if (!adminForm.phone.trim()) {
    ElMessage.warning("请填写管理员手机号");
    return;
  }
  adminCreating.value = true;
  try {
    await api.createProviderAdmin(
      { provider_id: target.id },
      { phone: adminForm.phone.trim() },
    );
    ElMessage.success("已创建管理员账号");
    adminVisible.value = false;
    await load();
  } catch (err) {
    ElMessage.error(err instanceof ApiError ? err.detail : "创建失败，请稍后再试");
  } finally {
    adminCreating.value = false;
  }
}

onMounted(() => {
  void load();
});
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2 class="page-title">服务商管理</h2>
      <el-button data-test="create-provider-btn" type="primary" @click="openCreate">
        新建服务商
      </el-button>
    </div>

    <p v-if="errorText" class="error-text" data-test="error">{{ errorText }}</p>

    <el-table v-loading="loading" :data="providers" border stripe>
      <el-table-column prop="name" label="名称" min-width="160" />
      <el-table-column prop="contact_phone" label="联系电话" min-width="140" />
      <el-table-column label="佣金比例" width="120" align="right">
        <template #default="{ row }">
          {{ formatRate(row.commission_rate) }}
        </template>
      </el-table-column>
      <el-table-column label="状态" width="110" align="center">
        <template #default="{ row }">
          <el-tag :type="statusTagType(row.status)">
            {{ statusText(row.status) }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="220" align="center">
        <!--
          el-table 的插槽行类型是宽松的 DefaultRow，这里显式断言回
          PlatformProviderItem：表格里的数据就是我们自己塞进去的 providers，
          类型不会比它更差。
        -->
        <template #default="{ row }">
          <el-button
            v-if="statusAction(row.status)"
            type="primary"
            link
            data-test="status-action-btn"
            :loading="changing === row.id"
            @click="changeStatus(row as PlatformProviderItem)"
          >
            {{ statusAction(row.status)?.label }}
          </el-button>
          <el-button
            type="primary"
            link
            data-test="create-admin-btn"
            @click="openAdmin(row as PlatformProviderItem)"
          >
            创建管理员
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 新建服务商 -->
    <el-dialog v-model="createVisible" title="新建服务商" width="420px">
      <div data-test="create-provider-dialog">
        <el-form label-width="90px" @submit.prevent="submitCreate">
          <el-form-item label="名称">
            <!--
              data-test 放在外层 div 上，不放在 el-input 上：
              el-input 会把没声明的属性透传给**内层 input 元素**，
              放在组件上时选择器的层级跟 el-input-number 不一样，
              测试里没法用同一个写法找输入框。
            -->
            <div data-test="provider-name-field">
              <el-input
                v-model="createForm.name"
                placeholder="服务商名称"
                maxlength="128"
              />
            </div>
          </el-form-item>
          <el-form-item label="联系电话">
            <div data-test="provider-phone-field">
              <el-input
                v-model="createForm.contact_phone"
                placeholder="联系电话"
                maxlength="32"
              />
            </div>
          </el-form-item>
          <el-form-item label="佣金比例">
            <div data-test="provider-rate-field">
              <el-input-number
                v-model="createForm.commission_rate"
                :min="0"
                :max="1"
                :step="0.01"
                :precision="4"
                style="width: 100%"
              />
            </div>
          </el-form-item>
        </el-form>
      </div>

      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button
          type="primary"
          data-test="submit-provider-btn"
          :loading="creating"
          @click="submitCreate"
        >
          创建
        </el-button>
      </template>
    </el-dialog>

    <!-- 创建服务商管理员 -->
    <el-dialog v-model="adminVisible" title="创建管理员" width="420px">
      <div data-test="create-admin-dialog">
        <p class="dialog-hint">
          服务商：{{ adminTarget?.name }}
        </p>
        <el-form label-width="90px" @submit.prevent="submitAdmin">
          <el-form-item label="手机号">
            <div data-test="admin-phone-field">
              <el-input
                v-model="adminForm.phone"
                placeholder="管理员登录用的手机号"
                maxlength="20"
              />
            </div>
          </el-form-item>
        </el-form>
      </div>

      <template #footer>
        <el-button @click="adminVisible = false">取消</el-button>
        <el-button
          type="primary"
          data-test="submit-admin-btn"
          :loading="adminCreating"
          @click="submitAdmin"
        >
          创建
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.dialog-hint {
  margin: 0 0 12px;
  color: #606266;
}
</style>
