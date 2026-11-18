/**
 * 一次性回执（跨页面的「刚才那步做完了」提示）。
 *
 * **为什么不用 pinia**：session store 的约定是只放 token 与 currentUser，
 * 回执不是会话状态——它是一次性的操作结果，用完即扔。
 * 放模块级单例最简单：详情页写一条，只有列表页读一次（读完即清空）。
 *
 * 典型用法：详情页拒单成功后写一条「已拒单」，然后跳回列表；
 * 列表页在 setup 里把这条回执取走，渲染一条提示条。
 *
 * **一次性**：列表页用 takeNotice() 取走（读到即清空），
 * 所以提示只在拒单后跳回列表那一次出现，之后再回列表看不到残留。
 */
import { ref } from "vue";

/** 全应用共享的一条回执（空串 = 没有回执）。 */
const notice = ref("");

/** 写一条回执。 */
export function setNotice(text: string): void {
  notice.value = text;
}

/**
 * 清掉回执。
 *
 * **只给测试用**：回执是模块级单例，用例之间得清干净，
 * 否则上一个用例写的回执会串到下一个用例。
 * 生产代码不用它——生产代码走 takeNotice()，读到即清空。
 */
export function clearNotice(): void {
  notice.value = "";
}

/**
 * 取走一次回执：读到并清空。
 *
 * 消费方在 setup 里调用（不是 onMounted）：setup 早于渲染，
 * 早一点清掉就不会有第二个人读到同一条回执。
 */
export function takeNotice(): string {
  const text = notice.value;
  notice.value = "";
  return text;
}
