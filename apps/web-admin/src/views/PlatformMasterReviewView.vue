<!--
  平台侧师傅入驻审核页（FE-06b）。

  列表只显示**待审核**的申请（后端按 `status=PENDING` 过滤）：
  师傅姓名 / 申请的服务商 / 申请时间 / 操作（通过 / 驳回）。

  两个动作打的是**同一个接口** `POST /api/v1/platform/masters/{master_id}/review`，
  区别只在请求体的 `decision`：

  - 通过：`decision=APPROVE`，可选 `target_provider_id` 改判到另一家服务商
    （不选就沿用申请里选的那家）；
  - 驳回：`decision=REJECT` + `reason`（理由写进审计日志，前端强制要填）。

  **操作人身份不传**：服务端按 token 里的 role 与 user_id 写审计日志，
  前端只说「审哪一位师傅」——自报身份等于自己挑身份（R1）。
  同样，请求体里也**没有 provider_id** 这个字段（归属由平台确认，
  不是客户端自报的东西；全仓 openapi 契约测试也禁止该字段名）。
-->
<script setup lang="ts">
import { onMounted, ref } from "vue";
import {
  ElButton,
  ElDialog,
  ElForm,
  ElFormItem,
  ElInput,
  ElMessage,
  ElOption,
  ElPagination,
  ElSelect,
  ElTable,
  ElTableColumn,
  vLoading,
} from "element-plus";
import { ApiError, type Schemas } from "@oto/shared/api";

import { api } from "@/api";
import { formatDateTime } from "@/utils/date";

type OnboardingApplicationItem = Schemas["OnboardingApplicationItem"];
type JoinableProviderItem = Schemas["JoinableProviderItem"];
type ReviewOnboardingRequest = Schemas["ReviewOnboardingRequest"];

/** 待审核的入驻申请。 */
const applications = ref<OnboardingApplicationItem[]>([]);
/** 待审核申请总数（后端分页：默认一页 20 条，超出的在后面的页）。 */
const total = ref(0);
const page = ref(1);
const limit = ref(20);
const loading = ref(false);
const errorText = ref("");

/** 可以改判过去的服务商（只有营业中的那些能收师傅）。 */
const providers = ref<JoinableProviderItem[]>([]);
/** 这份列表拉到没有（拉失败就别拿它做前置判断，交给后端判）。 */
const providersLoaded = ref(false);
/** 列表拉取失败时的提示（页面与通过弹窗里都提示一下）。 */
const providersError = ref("");

// ---------------------------------------------------------------------
// 通过
// ---------------------------------------------------------------------

const approveVisible = ref(false);
const approving = ref(false);
/** 正在审核的那一位。 */
const approveTarget = ref<OnboardingApplicationItem | null>(null);
/**
 * 改判到哪家：null / undefined = 沿用申请里选的那家（不传 target_provider_id）。
 *
 * 判定用「是不是 number」而不是「是不是 null」：el-select 被清空时回填的
 * 可能是 undefined（也可能是空串），只有「是数字」才算真的选了一家。
 */
const approveProviderId = ref<number | null | undefined>(null);

function openApprove(row: OnboardingApplicationItem): void {
  approveTarget.value = row;
  approveProviderId.value = null;
  approveVisible.value = true;
  // 服务商列表重新拉一次：申请待审核期间服务商可能被冻结 / 解冻，
  // 页面开着不动的那份列表就过期了（选中一个已冻结的必然被后端挡回）。
  void loadProviders();
}

/**
 * 申请里那家现在还能不能加入。
 *
 * **不能就得改判**：服务商可以在申请待审核期间被冻结，而后端通过时
 * 要求归属的服务商是营业中的（`status=ACTIVE`）。这时「沿用申请」
 * 必然被后端挡回 404，前端与其等一个看不懂的报错，不如先说清楚。
 *
 * 服务商列表拉失败时不做这个判断（`providersLoaded` 为 false）：
 * 拿不到列表就说「不可加入」是瞎猜，交给后端判。
 */
function needsReassign(target: OnboardingApplicationItem | null): boolean {
  if (!target || !providersLoaded.value) return false;
  return !providers.value.some((provider) => provider.id === target.provider_id);
}

/** 平台一家营业中的服务商都没有：谁都收不了人，「通过」这条路走不通。 */
function noJoinableProvider(): boolean {
  return providersLoaded.value && providers.value.length === 0;
}

/** 下拉的占位文案跟着当前状态走，别写着那个已经被禁止的选项。 */
function approvePlaceholder(): string {
  if (providersError.value) return "无法改判（服务商列表加载失败）";
  if (needsReassign(approveTarget.value)) return "请选择改判到哪一家（必选）";
  return "沿用申请的服务商";
}

async function submitApprove(): Promise<void> {
  const target = approveTarget.value;
  if (!target) return;
  if (needsReassign(target) && typeof approveProviderId.value !== "number") {
    ElMessage.warning("申请的服务商已不可加入，请改判到其他服务商");
    return;
  }
  const body: ReviewOnboardingRequest = { decision: "APPROVE" };
  // 改判才带 target_provider_id：不传 = 沿用申请里选的那家
  if (typeof approveProviderId.value === "number") {
    body.target_provider_id = approveProviderId.value;
  }
  approving.value = true;
  try {
    await api.reviewMasterOnboarding({ master_id: target.id }, body);
    ElMessage.success("已通过，师傅已入职");
    approveVisible.value = false;
    // 表格以服务端为准：审完这一行就不该还在列表里
    await reloadAfterReview();
  } catch (err) {
    ElMessage.error(err instanceof ApiError ? err.detail : "操作失败，请稍后再试");
  } finally {
    approving.value = false;
  }
}

// ---------------------------------------------------------------------
// 驳回
// ---------------------------------------------------------------------

const rejectVisible = ref(false);
const rejecting = ref(false);
const rejectTarget = ref<OnboardingApplicationItem | null>(null);
/** 驳回理由（必填，写进审计日志）。 */
const rejectReason = ref("");

function openReject(row: OnboardingApplicationItem): void {
  rejectTarget.value = row;
  rejectReason.value = "";
  rejectVisible.value = true;
}

async function submitReject(): Promise<void> {
  const target = rejectTarget.value;
  if (!target) return;
  const reason = rejectReason.value.trim();
  if (!reason) {
    ElMessage.warning("请填写驳回理由");
    return;
  }
  rejecting.value = true;
  try {
    await api.reviewMasterOnboarding(
      { master_id: target.id },
      { decision: "REJECT", reason },
    );
    ElMessage.success("已驳回");
    rejectVisible.value = false;
    await reloadAfterReview();
  } catch (err) {
    ElMessage.error(err instanceof ApiError ? err.detail : "操作失败，请稍后再试");
  } finally {
    rejecting.value = false;
  }
}

// ---------------------------------------------------------------------
// 加载
// ---------------------------------------------------------------------

async function load(): Promise<void> {
  loading.value = true;
  errorText.value = "";
  try {
    const result = await api.listPlatformOnboardingApplications({
      status: "PENDING",
      page: page.value,
      limit: limit.value,
    });
    applications.value = result.items;
    total.value = result.total;
  } catch (err) {
    errorText.value = err instanceof ApiError ? err.detail : "加载失败，请稍后再试";
  } finally {
    loading.value = false;
  }
}

/**
 * 审完之后刷新列表。
 *
 * 当前页只剩这一条时，它被审掉这一页就空了——退一页再拉，
 * 别把人停在一个空页上（还得再点一次才看得到剩下的）。
 */
async function reloadAfterReview(): Promise<void> {
  if (applications.value.length <= 1 && page.value > 1) {
    page.value -= 1;
  }
  await load();
}

/** 翻页。 */
function onPageChange(next: number): void {
  page.value = next;
  void load();
}

/** 可改判的服务商：营业中的那些（冻结 / 待审核的收不了人）。 */
async function loadProviders(): Promise<void> {
  try {
    const result = await api.listJoinableProviders();
    providers.value = result.items;
    providersLoaded.value = true;
    providersError.value = "";
  } catch {
    // 拉不到就只剩「沿用申请」这一种选项——不挡页面
    // （也不拿它做「必须改判」的前置判断，见 needsReassign）
    providers.value = [];
    providersLoaded.value = false;
    // 但要说出来：不然管理员分不清「没有别的营业中服务商」与「列表没拉到」
    providersError.value = "可改判的服务商列表加载失败，暂时无法改判";
  }
}

onMounted(() => {
  void load();
  void loadProviders();
});
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2 class="page-title">师傅入驻审核</h2>
    </div>

    <p v-if="errorText" class="error-text" data-test="error">{{ errorText }}</p>
    <p v-if="providersError" class="warn-text" data-test="providers-error">
      {{ providersError }}
    </p>

    <el-table v-loading="loading" :data="applications" border stripe>
      <el-table-column prop="real_name" label="师傅姓名" min-width="140" />
      <el-table-column prop="provider_name" label="申请服务商" min-width="160" />
      <el-table-column label="申请时间" min-width="170">
        <template #default="{ row }">
          {{ formatDateTime(row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column label="操作" width="180" align="center">
        <template #default="{ row }">
          <el-button
            type="primary"
            link
            data-test="approve-btn"
            @click="openApprove(row as OnboardingApplicationItem)"
          >
            通过
          </el-button>
          <el-button
            type="danger"
            link
            data-test="reject-btn"
            @click="openReject(row as OnboardingApplicationItem)"
          >
            驳回
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!--
      翻页：后端一页 20 条（limit 上限 100）。待审核超过一页时，
      后面的申请要翻页才看得见——不然第 21 条以后一直挂着没人审。
    -->
    <el-pagination
      class="pager"
      layout="total, prev, pager, next"
      data-test="pager"
      :total="total"
      :current-page="page"
      :page-size="limit"
      @current-change="onPageChange"
    />

    <!-- 通过（可选改判服务商） -->
    <el-dialog v-model="approveVisible" title="通过入驻申请" width="460px">
      <div data-test="approve-dialog">
        <p class="dialog-hint">
          师傅：{{ approveTarget?.real_name }} · 申请：{{ approveTarget?.provider_name }}
        </p>
        <!--
          申请里的那家被冻结 / 不是营业中时，后端通过不了：
          这里先说清楚「必须改判」，别让管理员点一次只换来一句看不懂的报错。
        -->
        <p
          v-if="needsReassign(approveTarget)"
          class="dialog-warn"
          data-test="reassign-hint"
        >
          申请的服务商已不可加入，请改判到其他服务商
        </p>
        <!--
          下拉列表拉不到时要说清楚：空下拉看起来像「没有别的服务商」，
          实际上只是没拉到——这时候只能沿用申请里那家（成不成功交给后端判）。
        -->
        <p
          v-if="providersError"
          class="dialog-warn"
          data-test="providers-error-hint"
        >
          {{ providersError }}
        </p>
        <!--
          一家营业中的服务商都没有：通过这条路走不通（后端只让挂到
          营业中的服务商名下），别让管理员在这里反复点提交。
        -->
        <p
          v-if="noJoinableProvider()"
          class="dialog-warn"
          data-test="no-provider-hint"
        >
          当前没有营业中的服务商，无法通过；可以驳回这条申请
        </p>
        <el-form label-width="110px" @submit.prevent="submitApprove">
          <el-form-item label="改判服务商">
            <!--
              留空 = 沿用申请里选的那家（不传 target_provider_id）。
              下拉里只列营业中的服务商：冻结 / 待审核的收不了人。
            -->
            <el-select
              v-model="approveProviderId"
              data-test="approve-provider-select"
              :placeholder="approvePlaceholder()"
              clearable
              :value-on-clear="null"
            >
              <el-option
                v-for="provider in providers"
                :key="provider.id"
                :label="provider.name"
                :value="provider.id"
              />
            </el-select>
          </el-form-item>
        </el-form>
      </div>

      <template #footer>
        <el-button @click="approveVisible = false">取消</el-button>
        <el-button
          type="primary"
          data-test="submit-approve-btn"
          :loading="approving"
          @click="submitApprove"
        >
          通过
        </el-button>
      </template>
    </el-dialog>

    <!-- 驳回（必须填理由） -->
    <el-dialog v-model="rejectVisible" title="驳回入驻申请" width="460px">
      <div data-test="reject-dialog">
        <p class="dialog-hint">
          师傅：{{ rejectTarget?.real_name }} · 申请：{{ rejectTarget?.provider_name }}
        </p>
        <el-form label-width="110px" @submit.prevent="submitReject">
          <el-form-item label="驳回理由">
            <div data-test="reject-reason-field">
              <el-input
                v-model="rejectReason"
                type="textarea"
                :rows="3"
                maxlength="500"
                placeholder="驳回理由（会记进审计日志）"
              />
            </div>
          </el-form-item>
        </el-form>
      </div>

      <template #footer>
        <el-button @click="rejectVisible = false">取消</el-button>
        <el-button
          type="danger"
          data-test="submit-reject-btn"
          :loading="rejecting"
          @click="submitReject"
        >
          驳回
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

.dialog-warn {
  margin: 0 0 12px;
  color: #e6a23c;
}

.warn-text {
  color: #e6a23c;
}

.pager {
  margin-top: 12px;
}
</style>
