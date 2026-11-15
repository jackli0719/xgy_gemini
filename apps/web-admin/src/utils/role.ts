/**
 * 角色相关的常量与判断。
 *
 * **单独一个模块**，因为同一份事实被三处用到：会话 store（菜单按角色过滤）、
 * 路由守卫（页面按角色拦截）、页面标题（登录页 / 顶栏按角色显示）。
 * 三处各写一份角色列表，迟早漂移——漂了的后果是「菜单显示了但进不去」
 * 或者「进得去但菜单不显示」。
 *
 * **前端判角色只是体验**：真正的边界在后端（服务端按 token 里的 role 判，
 * 角色不对一律 403）。这里漏了也只是多点一下、多一个报错。
 */

/** 平台管理员。 */
export const PLATFORM_ADMIN = "PLATFORM_ADMIN";
/** 平台运营（能看订单总览、管目录，但管不了服务商入驻）。 */
export const PLATFORM_OPS = "PLATFORM_OPS";

/** 服务商侧角色（派单 / 师傅管理）。 */
export const PROVIDER_ROLES = ["PROVIDER_ADMIN", "PROVIDER_STAFF"] as const;

/** 平台侧角色（订单总览 / 品类管理）。 */
export const PLATFORM_ROLES = [PLATFORM_ADMIN, PLATFORM_OPS] as const;

/** 是不是平台侧角色。 */
export function isPlatformRole(role: string | undefined | null): boolean {
  return PLATFORM_ROLES.includes(role as (typeof PLATFORM_ROLES)[number]);
}

/** 是不是服务商侧角色。 */
export function isProviderRole(role: string | undefined | null): boolean {
  return PROVIDER_ROLES.includes(role as (typeof PROVIDER_ROLES)[number]);
}

/**
 * 角色 -> 后台名称。
 *
 * 平台侧账号进的是「平台管理后台」，服务商侧进的是「服务商后台」——
 * 两个后台的菜单与数据都不一样，标题写死一个名字会让人以为自己
 * 看错了地方（PLAT-01 遗留：平台管理员登录后标题还写着「服务商后台」）。
 */
export function appTitleForRole(role: string | undefined | null): string {
  return isPlatformRole(role) ? "平台管理后台" : "服务商后台";
}

/**
 * 角色 -> 登录后该去的首页。
 *
 * 「/」这条路由的 redirect 用它（见 router/index.ts）：
 * 平台账号回平台页，服务商账号回派单页，认不出来的一律去登录页
 * （宁可重新登录，也别落到一个跟角色不搭的页面上）。
 */
export function homePathForRole(role: string | undefined | null): string {
  if (role === PLATFORM_ADMIN) return "/platform/providers";
  if (role === PLATFORM_OPS) return "/platform/orders";
  if (isProviderRole(role)) return "/provider/dispatch";
  return "/login";
}
