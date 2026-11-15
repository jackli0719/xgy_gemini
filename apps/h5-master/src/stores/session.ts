/**
 * 会话 store：只放 token 和 currentUser。
 *
 * 卡片约束：pinia 只放这两样，不引入 vuex。
 *
 * token 与用户信息落在 localStorage —— 刷新页面不用重新登录。
 * 师傅身份本身**不在这里**：后端按 token 里的 user_id 查 master 表，
 * 前端不存 master_id，也不往请求里带（卡片约束 1、2）。
 */
import { defineStore } from "pinia";
import { computed, ref } from "vue";

/** token 在 localStorage 里的键名。 */
const TOKEN_KEY = "oto.master.token";
/** 当前用户信息在 localStorage 里的键名。 */
const USER_KEY = "oto.master.currentUser";

export interface CurrentUser {
  id: number;
  name: string;
  phone?: string;
  /** 角色（后端返回的 user.role）。师傅端应该是 MASTER。 */
  role?: string;
}

/** 读当前用户；localStorage 里的内容坏了就当没有（不因为它白屏）。 */
function readCurrentUser(): CurrentUser | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as CurrentUser;
  } catch {
    return null;
  }
}

export const useSessionStore = defineStore("session", () => {
  const token = ref<string | null>(localStorage.getItem(TOKEN_KEY));
  const currentUser = ref<CurrentUser | null>(readCurrentUser());

  const isLoggedIn = computed(() => Boolean(token.value));

  function setToken(value: string): void {
    token.value = value;
    localStorage.setItem(TOKEN_KEY, value);
  }

  function setCurrentUser(user: CurrentUser): void {
    currentUser.value = user;
    localStorage.setItem(USER_KEY, JSON.stringify(user));
  }

  function clear(): void {
    token.value = null;
    currentUser.value = null;
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
  }

  return { token, currentUser, isLoggedIn, setToken, setCurrentUser, clear };
});
