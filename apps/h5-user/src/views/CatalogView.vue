<script setup lang="ts">
/**
 * 品类列表页。
 *
 * 数据来自 api.listCategories()（GET /api/v1/catalog），后端返回的是
 * 一级品类 + 递归子品类。点一级品类进二级页；子品类也直接可点。
 */
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { api } from "@/api";
import type { components } from "@oto/shared/api";

type CategoryNode = components["schemas"]["CategoryNode"];

const router = useRouter();

const categories = ref<CategoryNode[]>([]);
const loading = ref(true);
const error = ref("");

onMounted(async () => {
  try {
    categories.value = await api.listCategories();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "品类加载失败";
  } finally {
    loading.value = false;
  }
});

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

    <van-loading v-if="loading" size="24" data-test="loading">加载中</van-loading>
    <p v-else-if="error" class="page-error" data-test="error">{{ error }}</p>
    <van-empty v-else-if="categories.length === 0" description="暂无品类" />
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
