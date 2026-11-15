/**
 * 会话 store：只放 token 和 currentUser。
 *
 * 卡片约束：pinia 只放这两样，不引入 vuex。
 *
 * currentUser 里带 `provider_id`：服务商后台要靠它知道
 * 「我属于哪个服务商」（页面上显示、菜单按归属过滤）。
 * 注意这只是**显示**用的——数据隔离由后端按 token 决定，
 * 前端就算把 provider_id 改掉也拿不到别家的数据。
 *
 * 存 localStorage 是为了刷新页面不掉登录态（后台人员经常刷新）。
 */
import { defineStore } from "pinia";
import { computed, ref } from "vue";

/** token 在 localStorage 里的键名。 */
const TOKEN_KEY = "oto.web.token";
/** 当前用户信息在 localStorage 里的键名。 */
const USER_KEY = "oto.web.currentUser";

export interface CurrentUser {
  id: number;
  nickname: string;
  phone?: string;
  /** 用户角色（USER / PROVIDER_ADMIN / PROVIDER_STAFF ...） */
  role: string;
  /** 归属的服务商 ID；服务商侧角色才有值，其余角色为 null */
  provider_id: number | null;
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
  /** 是否服务商侧账号（有归属才能进服务商作用域）。 */
  const isProvider = computed(() => currentUser.value?.provider_id != null);

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

  return {
    token,
    currentUser,
    isLoggedIn,
    isProvider,
    setToken,
    setCurrentUser,
    clear,
  };
});
