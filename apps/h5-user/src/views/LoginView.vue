<script setup lang="ts">
/**
 * 登录页：手机号 + 验证码。
 *
 * - 验证码是 **MVP 占位**：后端写死 123456（见后端 app.core.config 的
 *   login_sms_code），不接短信网关；
 * - 登录成功后把 token 写进会话 store（localStorage），
 *   再跳回 redirect 参数指向的地方；没有 redirect 就回品类页。
 *
 * redirect 只接受站内路径：以 "//" 开头的是协议相对 URL（能跳到外站），
 * 一律当没有 redirect 处理。
 */
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { api } from "@/api";
import { useSessionStore } from "@/stores/session";
import { firstQuery } from "@/utils/query";

const route = useRoute();
const router = useRouter();
const session = useSessionStore();

const phone = ref("");
const code = ref("");
const submitting = ref(false);
const error = ref("");

/** 登录后要去的路径（只允许站内绝对路径）。 */
function targetPath(): string {
  const target = firstQuery(route.query.redirect);
  if (target && target.startsWith("/") && !target.startsWith("//")) {
    return target;
  }
  return "/catalog";
}

async function submit(): Promise<void> {
  if (!phone.value.trim()) {
    error.value = "请填写手机号";
    return;
  }
  if (!code.value.trim()) {
    error.value = "请填写验证码";
    return;
  }
  submitting.value = true;
  error.value = "";
  try {
    const result = await api.login({
      phone: phone.value.trim(),
      code: code.value.trim(),
    });
    session.setToken(result.access_token);
    session.setCurrentUser({
      id: result.user.id,
      name: result.user.nickname,
      phone: result.user.phone,
    });
    await router.replace(targetPath());
  } catch (err) {
    error.value = err instanceof Error ? err.message : "登录失败";
  } finally {
    submitting.value = false;
  }
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">登录</h2>

    <van-cell-group inset>
      <van-field
        v-model="phone"
        type="tel"
        maxlength="11"
        label="手机号"
        placeholder="请输入手机号"
        data-test="phone-field"
      />
      <van-field
        v-model="code"
        type="digit"
        maxlength="6"
        label="验证码"
        placeholder="请输入验证码"
        data-test="code-field"
      />
    </van-cell-group>

    <p class="page-label">MVP 占位：短信验证码固定为 123456</p>

    <p v-if="error" class="page-error" data-test="error">{{ error }}</p>

    <div class="page-footer">
      <van-button
        type="primary"
        block
        :loading="submitting"
        data-test="submit-login"
        @click="submit"
      >
        登录
      </van-button>
    </div>
  </div>
</template>
