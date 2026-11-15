<!--
  登录页（服务商后台）。

  **故意做得很薄**：卡片明确要求「不写完整登录页，复用 FE-03 的
  /api/v1/auth/login」。这里只有手机号 + 验证码两个输入框，
  验证码仍是 MVP 占位（后端配置项 login_sms_code）。

  登录成功后：
  - token 写进会话 store（落在 localStorage）；
  - currentUser 一起存（含 provider_id，页面上要显示）；
  - 跳回 redirect 指定的地方，没有 redirect 就回派单页。
-->
<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElButton, ElCard, ElForm, ElFormItem, ElInput } from "element-plus";

import { ApiError } from "@oto/shared/api";

import { api } from "@/api";
import { useSessionStore } from "@/stores/session";

const session = useSessionStore();
const router = useRouter();
const route = useRoute();

const phone = ref("");
const code = ref("");
const errorText = ref("");
const submitting = ref(false);

/**
 * redirect 只允许站内绝对路径。
 *
 * 允许 "//evil.com" 这种协议相对地址的话，登录完会把人送去外站——
 * 这是开放重定向。判断放在前端就够了：后端根本不知道 redirect 是什么。
 */
function targetPath(): string {
  const redirect = route.query.redirect;
  if (typeof redirect !== "string") return "/provider/dispatch";
  if (!redirect.startsWith("/") || redirect.startsWith("//")) {
    return "/provider/dispatch";
  }
  return redirect;
}

async function submit(): Promise<void> {
  errorText.value = "";
  if (!phone.value.trim()) {
    errorText.value = "请填写手机号";
    return;
  }
  if (!code.value.trim()) {
    errorText.value = "请填写验证码";
    return;
  }

  submitting.value = true;
  try {
    const result = await api.login({
      phone: phone.value.trim(),
      code: code.value.trim(),
    });
    session.setToken(result.access_token);
    session.setCurrentUser(result.user);
    await router.replace(targetPath());
  } catch (err) {
    // SDK 抛的是 ApiError（带后端给的 detail）；万一别的异常，
    // 退一步用它的 message，再不行才给通用文案。
    errorText.value =
      err instanceof ApiError
        ? err.detail
        : err instanceof Error
          ? err.message
          : "登录失败，请稍后再试";
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="login-page">
    <el-card class="login-card">
      <template #header>
        <span class="login-title">服务商后台登录</span>
      </template>

      <el-form label-width="80px" @submit.prevent="submit">
        <el-form-item label="手机号">
          <el-input
            v-model="phone"
            data-test="phone-field"
            placeholder="登录用的手机号"
            maxlength="20"
          />
        </el-form-item>

        <el-form-item label="验证码">
          <el-input
            v-model="code"
            data-test="code-field"
            placeholder="短信验证码"
            maxlength="32"
          />
        </el-form-item>

        <p v-if="errorText" class="error-text" data-test="error">
          {{ errorText }}
        </p>

        <el-button
          type="primary"
          data-test="submit-login"
          :loading="submitting"
          @click="submit"
        >
          登录
        </el-button>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.login-page {
  display: flex;
  justify-content: center;
  padding-top: 60px;
}

.login-card {
  width: 360px;
}

.login-title {
  font-weight: 600;
}
</style>
