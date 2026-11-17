<script setup lang="ts">
/**
 * 品类列表页。
 *
 * 数据来自 api.listCategories()（GET /api/v1/catalog），后端返回的是
 * 一级品类 + 递归子品类。点一级品类进二级页；子品类也直接可点。
 *
 * 三种页面状态（UI-01）：
 * - 请求中：显示骨架屏（不是转圈——列表页的转圈太晃）；
 * - 出错：显示错误文案 + 重试按钮，不白屏；
 * - 没数据：显示引导文案 + 按钮，不是一句「暂无品类」就把人堵死。
 */
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { api } from "@/api";
import { errorMessage } from "@/utils/error";
import type { components } from "@oto/shared/api";

type CategoryNode = components["schemas"]["CategoryNode"];

const router = useRouter();

const categories = ref<CategoryNode[]>([]);
const loading = ref(true);
const error = ref("");

onMounted(load);

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    categories.value = await api.listCategories();
  } catch (err) {
    error.value = errorMessage(err, "品类加载失败");
  } finally {
    loading.value = false;
  }
}

/** 子品类名拼一行副标题；没有子品类就是空字符串。 */
function childrenText(category: CategoryNode): string {
  return (category.children ?? []).map((child) => child.name).join(" / ");
}

function openCategory(categoryId: number): void {
  void router.push(`/catalog/${categoryId}`);
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">选择服务品类</h2>

    <div v-if="loading" data-test="skeleton">
      <van-skeleton title :row="4" />
    </div>

    <div v-else-if="error" class="page-block" data-test="error-block">
      <p class="page-error" data-test="error">{{ error }}</p>
      <van-button size="small" plain type="primary" data-test="retry" @click="load">
        重试
      </van-button>
    </div>

    <van-empty v-else-if="categories.length === 0" data-test="empty">
      <template #description>
        <span data-test="empty-text">平台还没有上架服务品类，过段时间再来看看</span>
      </template>
      <van-button size="small" type="primary" data-test="empty-action" @click="load">
        重新加载
      </van-button>
    </van-empty>

    <van-cell-group v-else inset>
      <van-cell
        v-for="category in categories"
        :key="category.id"
        :title="category.name"
        :label="childrenText(category)"
        is-link
        data-test="category-card"
        @click="openCategory(category.id)"
      />
    </van-cell-group>
  </div>
</template>
