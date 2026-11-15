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

// 导入时改名：store 里同名的 computed（isProviderRole）会遮住工具函数，
// 直接 import 同名会让 computed 里拿到的是 ref 而不是函数。
import {
  isPlatformOpsRole as roleIsPlatformOps,
  isProviderRole as roleIsProvider,
} from "@/utils/role";

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
  /**
   * 是否平台管理员。
   *
   * 只用于**显示**（菜单按角色过滤）：真正的边界在后端，
   * 服务商侧接口对平台账号一律 403。
   */
  const isPlatformAdmin = computed(() => currentUser.value?.role === "PLATFORM_ADMIN");
  /**
   * 是否平台侧「运营」角色（平台管理员 / 平台运营）。
   *
   * 这两种角色能进运营页面（订单总览 / 品类管理）；
   * 服务商侧页面（派单 / 师傅管理）对它们一律 403。
   *
   * **不含财务**：运营页面的后端接口只放 PLATFORM_ADMIN / PLATFORM_OPS，
   * 财务进运营页面只会拿到 403，所以运营菜单不归它。
   */
  const isPlatformStaff = computed(() => roleIsPlatformOps(currentUser.value?.role));
  /**
   * 是否平台财务。
   *
   * 菜单按它过滤：财务只看得到「结算确认」。
   *
   * **它也是唯一能点「确认结算」的角色**（列表管理员也能看，
   * 但确认是钱相关的写动作，后端只放财务）。
   */
  const isPlatformFinance = computed(() => currentUser.value?.role === "PLATFORM_FINANCE");
  /**
   * 是否服务商侧角色（服务商管理员 / 员工）。
   *
   * 菜单按它过滤：平台账号看不到服务商菜单（PLAT-02 修的 UX 遗留）。
   */
  const isProviderRole = computed(() => roleIsProvider(currentUser.value?.role));

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
    isPlatformAdmin,
    isPlatformStaff,
    isPlatformFinance,
    isProviderRole,
    setToken,
    setCurrentUser,
    clear,
  };
});
