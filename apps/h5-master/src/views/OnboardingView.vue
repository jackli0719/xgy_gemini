<script setup lang="ts">
/**
 * 师傅入驻申请页（/onboard）。
 *
 * 流程（后端 app.services.master_onboarding）：
 *
 * 1. 打开页面先问「我有没有申请」：GET /api/v1/masters/onboarding。
 *    - **404 = 没有申请**（后端就是用 404 表示「还没申请」）-> 显示表单；
 *    - 200 = 已有申请 -> 只显示状态，不再给表单（不给重复申请的机会）。
 * 2. 表单里选一家服务商（GET /api/v1/masters/joinable-providers，
 *    只有营业中的服务商可选）+ 填姓名，提交：
 *    POST /api/v1/masters/onboarding。
 * 3. 提交成功状态是「待审核」（PENDING），能不能入职由平台说了算。
 *
 * **状态页与表单是互斥的**：已有申请时表单整个不渲染。
 *
 * **409 不当错误处理**：后端在「已经申请过 / 已入职」时返回 409，
 * 这时页面**不弹错误**，而是把已有申请的状态拉出来显示——重复提交
 * 是正常情况（用户连点了两次），不是故障。
 *
 * 已经在职（ACTIVE）的师傅不该走这个页：路由守卫会把他送回订单页
 * （见 router/index.ts），页面自己也会跳一次（防止直接打开本页）。
 */
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { api } from "@/api";
import { MASTER_STATUS_TEXT } from "@/constants/status";
import { ApiError, type components } from "@oto/shared/api";

type Application = components["schemas"]["OnboardingApplicationItem"];
type JoinableProvider = components["schemas"]["JoinableProviderItem"];

const router = useRouter();

const loading = ref(true);
const submitting = ref(false);
const error = ref("");

/** 我的申请（没有申请时为 null）。 */
const application = ref<Application | null>(null);
/** 可以申请加入的服务商。 */
const providers = ref<JoinableProvider[]>([]);
/** 选中的服务商 id（null = 还没选）。 */
const providerId = ref<number | null>(null);
/** 填写的姓名。 */
const realName = ref("");

/** 下拉选项（Vant 的 options 形状）。 */
const providerOptions = computed(() =>
  providers.value.map((provider) => ({
    text: provider.name,
    value: provider.id,
  })),
);

/** 有申请就只显示状态，没有申请才显示表单（模板里按 application 分支）。 */
const statusText = computed(() =>
  application.value ? MASTER_STATUS_TEXT[application.value.status] : "",
);

/** 状态下面那句解释（告诉用户接下来会怎样）。 */
const statusHint = computed(() => {
  switch (application.value?.status) {
    case "PENDING":
      return "平台正在审核，通过后就可以接单了";
    case "ACTIVE":
      return "已入职，正在跳转到订单页";
    case "ON_LEAVE":
      return "当前休假中，复工后恢复接单";
    case "DISABLED":
      return "已被所属服务商停用，恢复需要联系平台";
    default:
      return "";
  }
});

onMounted(load);

/** 拉我的申请状态；没有申请（404）就加载服务商列表准备填表。 */
async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const result = await api.getMyOnboarding();
    application.value = result;
    if (result.status === "ACTIVE") {
      // 已入职：没什么好申请的了，直接去接单
      await router.replace("/orders");
    }
  } catch (err) {
    if (isStatus(err, 404)) {
      // 没有申请 -> 显示表单
      application.value = null;
      await loadProviders();
    } else {
      error.value = err instanceof Error ? err.message : "申请状态加载失败";
    }
  } finally {
    loading.value = false;
  }
}

/** 拉可申请的服务商；默认选中第一家。 */
async function loadProviders(): Promise<void> {
  try {
    const result = await api.listJoinableProviders();
    providers.value = result.items;
    const first = result.items[0];
    if (first) providerId.value = first.id;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "服务商列表加载失败";
  }
}

/** 提交申请。 */
async function submit(): Promise<void> {
  const name = realName.value.trim();
  if (!name) {
    error.value = "请填写姓名";
    return;
  }
  if (providerId.value === null) {
    error.value = "请选择申请的服务商";
    return;
  }
  submitting.value = true;
  error.value = "";
  try {
    // 提交成功即「待审核」：表单换成状态页
    application.value = await api.createOnboarding({
      real_name: name,
      target_provider_id: providerId.value,
    });
  } catch (err) {
    if (isStatus(err, 409)) {
      // 已有申请 / 已入职：不报错，改成显示已有申请的状态
      await showExisting();
      return;
    }
    error.value = err instanceof Error ? err.message : "提交失败";
  } finally {
    submitting.value = false;
  }
}

/** 409 之后：把已有申请的状态拉出来显示。拉不到就提示刷新。 */
async function showExisting(): Promise<void> {
  try {
    const result = await api.getMyOnboarding();
    application.value = result;
    if (result.status === "ACTIVE") {
      await router.replace("/orders");
    }
  } catch {
    error.value = "已有入驻申请，请刷新查看状态";
  }
}

/** 判断是不是某个状态码的业务错误（ApiError 带 status）。 */
function isStatus(err: unknown, status: number): boolean {
  return err instanceof ApiError && err.status === status;
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">师傅入驻</h2>

    <van-loading v-if="loading" size="24" data-test="loading">加载中</van-loading>

    <!-- 已有申请：只显示状态，没有表单 -->
    <template v-else-if="application">
      <van-cell-group inset data-test="status-card">
        <van-cell title="申请状态" :value="statusText" data-test="status-text" />
        <van-cell title="姓名" :value="application.real_name" />
        <van-cell title="申请服务商" :value="application.provider_name" />
      </van-cell-group>
      <p class="page-label" data-test="status-hint">{{ statusHint }}</p>
    </template>

    <!-- 没有申请：填表 -->
    <div v-else data-test="apply-form">
      <van-cell-group inset>
        <van-field
          v-model="realName"
          label="姓名"
          placeholder="请输入真实姓名"
          data-test="name-field"
        />
      </van-cell-group>

      <div class="page-block">
        <p class="page-label">申请加入的服务商</p>
        <van-dropdown-menu>
          <van-dropdown-item
            v-model="providerId"
            :options="providerOptions"
            data-test="provider-select"
          />
        </van-dropdown-menu>
      </div>

      <p v-if="error" class="page-error" data-test="error">{{ error }}</p>

      <div class="page-footer">
        <van-button
          type="primary"
          block
          :loading="submitting"
          data-test="submit-onboarding"
          @click="submit"
        >
          提交申请
        </van-button>
      </div>
    </div>
  </div>
</template>
