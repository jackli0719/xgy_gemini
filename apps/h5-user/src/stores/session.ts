/**
 * 会话 store：只放 token 和 currentUser。
 *
 * 卡片约束：pinia 只放这两样，不引入 vuex。
 *
 * 登录页属于 FE-03，本卡不写。这里做的是「占位实现」：
 * token 从 localStorage 读（FE-03 之后由登录页写入），
 * 没有 token 时路由守卫会跳到「请先登录」。
 */
import { defineStore } from "pinia";
import { computed, ref } from "vue";

/** token 在 localStorage 里的键名。 */
const TOKEN_KEY = "oto.token";
/** 当前用户信息在 localStorage 里的键名。 */
const USER_KEY = "oto.currentUser";

export interface CurrentUser {
  id: number;
  name: string;
  phone?: string;
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
