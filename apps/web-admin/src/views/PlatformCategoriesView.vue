<!--
  平台侧品类管理页（PLAT-02）。

  四件事：
  1. 打开页面拉品类树（含子品类与各品类下的服务项，含已停用的）；
  2. 点树上的一个品类 -> 右边列出这个品类下的服务项；
  3. 新建 / 编辑品类（名称、排序、状态）；
  4. 新建 / 编辑服务项（名称、基准价、时长、状态）。

  **改的时候带 expected_status 与 expected_updated_at**：前者是「我以为的
  旧状态」，后者是「我以为的版本号」（这一行最后被改的时间，
  从列表接口原样带回）。服务端发现这一行已经被别人动过就返回 409
  （两个人同时改一个服务项，谁先改谁赢，后改的那个拿到冲突而不是把
  前一个的改动覆盖掉）。

  身份问题：这一页只有平台侧角色能进（路由守卫按角色拦），
  但**操作人身份不是前端传的**——服务端从 token 里取 role 与 user_id
  写审计日志。前端只说「要改哪一个」。
-->
<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import {
  ElButton,
  ElDialog,
  ElForm,
  ElFormItem,
  ElInput,
  ElInputNumber,
  ElMessage,
  ElOption,
  ElSelect,
  ElTable,
  ElTableColumn,
  ElTag,
  ElTree,
  vLoading,
} from "element-plus";
import { ApiError, type Schemas } from "@oto/shared/api";

import { api } from "@/api";

type CategoryNode = Schemas["PlatformCategoryNode"];
type ServiceItem = Schemas["PlatformServiceItem"];
type CatalogStatus = ServiceItem["status"];

/** 目录状态 -> 中文文案与 tag 颜色。 */
const STATUS_TEXT: Record<CatalogStatus, string> = {
  ACTIVE: "启用",
  INACTIVE: "停用",
};

const STATUS_TAG_TYPE: Record<CatalogStatus, "success" | "info"> = {
  ACTIVE: "success",
  INACTIVE: "info",
};

/** el-tree 要的是 {id, label, children}，原始节点挂在 raw 上。 */
interface TreeNode {
  id: number;
  label: string;
  children: TreeNode[];
  raw: CategoryNode;
}

const tree = ref<TreeNode[]>([]);
const loading = ref(false);
const errorText = ref("");
/** 当前选中的品类（没选时为空）。 */
const selected = ref<CategoryNode | null>(null);

const STATUS_OPTIONS: { value: CatalogStatus; label: string }[] = [
  { value: "ACTIVE", label: "启用" },
  { value: "INACTIVE", label: "停用" },
];

function statusText(status: CatalogStatus): string {
  return STATUS_TEXT[status];
}

function statusTagType(status: CatalogStatus) {
  return STATUS_TAG_TYPE[status];
}

function toTreeNodes(nodes: CategoryNode[]): TreeNode[] {
  return nodes.map((node) => ({
    id: node.id,
    label: node.name,
    children: toTreeNodes(node.children),
    raw: node,
  }));
}

/** 所有品类（扁平）——建子品类时选父级用。 */
const flatCategories = computed<CategoryNode[]>(() => {
  const result: CategoryNode[] = [];
  const walk = (nodes: CategoryNode[]): void => {
    for (const node of nodes) {
      result.push(node);
      walk(node.children);
    }
  };
  walk(tree.value.map((node) => node.raw));
  return result;
});

/** 拉品类树。 */
async function load(): Promise<void> {
  loading.value = true;
  errorText.value = "";
  try {
    const nodes = await api.listPlatformCategories();
    tree.value = toTreeNodes(nodes);
    // 重新拉过之后，选中项要跟着更新（不然显示的是旧数据）
    if (selected.value) {
      selected.value =
        flatCategories.value.find((node) => node.id === selected.value?.id) ?? null;
    }
  } catch (err) {
    errorText.value = err instanceof ApiError ? err.detail : "加载失败，请稍后再试";
  } finally {
    loading.value = false;
  }
}

function onNodeClick(data: TreeNode): void {
  selected.value = data.raw;
}

// ---------------------------------------------------------------------
// 品类：新建 / 编辑
// ---------------------------------------------------------------------

const categoryVisible = ref(false);
const categorySaving = ref(false);
const categoryForm = reactive({
  name: "",
  parent_id: undefined as number | undefined,
  sort_order: 0,
  status: "ACTIVE" as CatalogStatus,
});
/** 编辑时记住原状态：提交时当 expected_status 带上（乐观锁）。 */
const categoryOriginalStatus = ref<CatalogStatus>("ACTIVE");
/** 编辑时记住原版本号：提交时当 expected_updated_at 带上（乐观锁）。 */
const categoryOriginalUpdatedAt = ref<string | null>(null);
const editingCategoryId = ref<number | null>(null);

function openCreateCategory(): void {
  editingCategoryId.value = null;
  categoryForm.name = "";
  categoryForm.parent_id = selected.value?.id;
  categoryForm.sort_order = 0;
  categoryForm.status = "ACTIVE";
  categoryOriginalStatus.value = "ACTIVE";
  categoryOriginalUpdatedAt.value = null;
  categoryVisible.value = true;
}

function openEditCategory(): void {
  const node = selected.value;
  if (!node) {
    ElMessage.warning("请先在左边选一个品类");
    return;
  }
  editingCategoryId.value = node.id;
  categoryForm.name = node.name;
  categoryForm.parent_id = node.parent_id ?? undefined;
  categoryForm.sort_order = node.sort_order;
  categoryForm.status = node.status;
  categoryOriginalStatus.value = node.status;
  categoryOriginalUpdatedAt.value = node.updated_at;
  categoryVisible.value = true;
}

async function submitCategory(): Promise<void> {
  if (!categoryForm.name.trim()) {
    ElMessage.warning("请填写品类名称");
    return;
  }
  categorySaving.value = true;
  try {
    if (editingCategoryId.value === null) {
      await api.createPlatformCategory({
        name: categoryForm.name.trim(),
        parent_id: categoryForm.parent_id ?? null,
        sort_order: categoryForm.sort_order,
      });
      ElMessage.success("已创建品类");
    } else {
      await api.updatePlatformCategory(
        { category_id: editingCategoryId.value },
        {
          name: categoryForm.name.trim(),
          sort_order: categoryForm.sort_order,
          status: categoryForm.status,
          expected_status: categoryOriginalStatus.value,
          // 版本号：原样带回，服务端发现这行被改过就返回 409
          expected_updated_at: categoryOriginalUpdatedAt.value,
        },
      );
      ElMessage.success("已保存");
    }
    categoryVisible.value = false;
    await load();
  } catch (err) {
    ElMessage.error(err instanceof ApiError ? err.detail : "保存失败，请稍后再试");
  } finally {
    categorySaving.value = false;
  }
}

// ---------------------------------------------------------------------
// 服务项：新建 / 编辑
// ---------------------------------------------------------------------

const itemVisible = ref(false);
const itemSaving = ref(false);
const itemForm = reactive({
  name: "",
  base_price: 0,
  duration_min: 60,
  status: "ACTIVE" as CatalogStatus,
});
/** 编辑时记住原状态：提交时当 expected_status 带上（乐观锁）。 */
const itemOriginalStatus = ref<CatalogStatus>("ACTIVE");
/** 编辑时记住原版本号：提交时当 expected_updated_at 带上（乐观锁）。 */
const itemOriginalUpdatedAt = ref<string | null>(null);
const editingItemId = ref<number | null>(null);

function openCreateItem(): void {
  if (!selected.value) {
    ElMessage.warning("请先在左边选一个品类");
    return;
  }
  editingItemId.value = null;
  itemForm.name = "";
  itemForm.base_price = 0;
  itemForm.duration_min = 60;
  itemForm.status = "ACTIVE";
  itemOriginalStatus.value = "ACTIVE";
  itemOriginalUpdatedAt.value = null;
  itemVisible.value = true;
}

function openEditItem(row: ServiceItem): void {
  editingItemId.value = row.id;
  itemForm.name = row.name;
  itemForm.base_price = Number(row.base_price);
  itemForm.duration_min = row.duration_min;
  itemForm.status = row.status;
  itemOriginalStatus.value = row.status;
  itemOriginalUpdatedAt.value = row.updated_at;
  itemVisible.value = true;
}

async function submitItem(): Promise<void> {
  const node = selected.value;
  if (!node) {
    ElMessage.warning("请先在左边选一个品类");
    return;
  }
  if (!itemForm.name.trim()) {
    ElMessage.warning("请填写服务项名称");
    return;
  }
  itemSaving.value = true;
  try {
    if (editingItemId.value === null) {
      await api.createPlatformItem({
        category_id: node.id,
        name: itemForm.name.trim(),
        base_price: itemForm.base_price,
        duration_min: itemForm.duration_min,
      });
      ElMessage.success("已创建服务项");
    } else {
      await api.updatePlatformItem(
        { item_id: editingItemId.value },
        {
          name: itemForm.name.trim(),
          base_price: itemForm.base_price,
          duration_min: itemForm.duration_min,
          status: itemForm.status,
          expected_status: itemOriginalStatus.value,
          // 版本号：原样带回，服务端发现这行被改过就返回 409
          expected_updated_at: itemOriginalUpdatedAt.value,
        },
      );
      ElMessage.success("已保存");
    }
    itemVisible.value = false;
    await load();
  } catch (err) {
    ElMessage.error(err instanceof ApiError ? err.detail : "保存失败，请稍后再试");
  } finally {
    itemSaving.value = false;
  }
}

onMounted(() => {
  void load();
});
</script>

<template>
  <div class="page">
    <div class="page-header">
      <h2 class="page-title">品类管理</h2>
      <div class="page-actions">
        <el-button data-test="create-category-btn" type="primary" @click="openCreateCategory">
          新建品类
        </el-button>
        <el-button data-test="edit-category-btn" @click="openEditCategory">
          编辑品类
        </el-button>
        <el-button data-test="create-item-btn" @click="openCreateItem">
          新建服务项
        </el-button>
      </div>
    </div>

    <p v-if="errorText" class="error-text" data-test="error">{{ errorText }}</p>

    <div class="catalog-layout">
      <!-- 左：品类树 -->
      <div class="catalog-tree" data-test="category-tree">
        <el-tree
          v-loading="loading"
          :data="tree"
          :props="{ label: 'label', children: 'children' }"
          node-key="id"
          default-expand-all
          @node-click="onNodeClick"
        />
      </div>

      <!-- 右：选中品类下的服务项 -->
      <div class="catalog-items">
        <p class="catalog-hint">
          {{ selected ? `品类：${selected.name}` : "请在左边选一个品类" }}
        </p>
        <el-table :data="selected?.items ?? []" border stripe>
          <el-table-column prop="name" label="服务项" min-width="160" />
          <el-table-column prop="base_price" label="基准价" width="110" align="right" />
          <el-table-column prop="duration_min" label="时长（分钟）" width="120" />
          <el-table-column label="状态" width="100" align="center">
            <template #default="{ row }">
              <el-tag :type="statusTagType(row.status)">
                {{ statusText(row.status) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="100" align="center">
            <template #default="{ row }">
              <el-button
                type="primary"
                link
                data-test="edit-item-btn"
                @click="openEditItem(row as ServiceItem)"
              >
                编辑
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <!-- 新建 / 编辑品类 -->
    <el-dialog
      v-model="categoryVisible"
      :title="editingCategoryId === null ? '新建品类' : '编辑品类'"
      width="420px"
    >
      <div data-test="category-dialog">
        <el-form label-width="90px" @submit.prevent="submitCategory">
          <el-form-item label="名称">
            <div data-test="category-name-field">
              <el-input
                v-model="categoryForm.name"
                placeholder="品类名称"
                maxlength="64"
              />
            </div>
          </el-form-item>
          <el-form-item v-if="editingCategoryId === null" label="父品类">
            <div data-test="category-parent-field">
              <el-select v-model="categoryForm.parent_id" placeholder="一级品类" clearable>
                <el-option
                  v-for="node in flatCategories"
                  :key="node.id"
                  :label="node.name"
                  :value="node.id"
                />
              </el-select>
            </div>
          </el-form-item>
          <el-form-item label="排序">
            <div data-test="category-sort-field">
              <el-input-number
                v-model="categoryForm.sort_order"
                :min="0"
                :max="9999"
                :step="1"
                style="width: 100%"
              />
            </div>
          </el-form-item>
          <el-form-item v-if="editingCategoryId !== null" label="状态">
            <div data-test="category-status-field">
              <el-select v-model="categoryForm.status">
                <el-option
                  v-for="option in STATUS_OPTIONS"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </el-select>
            </div>
          </el-form-item>
        </el-form>
      </div>

      <template #footer>
        <el-button @click="categoryVisible = false">取消</el-button>
        <el-button
          type="primary"
          data-test="submit-category-btn"
          :loading="categorySaving"
          @click="submitCategory"
        >
          保存
        </el-button>
      </template>
    </el-dialog>

    <!-- 新建 / 编辑服务项 -->
    <el-dialog
      v-model="itemVisible"
      :title="editingItemId === null ? '新建服务项' : '编辑服务项'"
      width="420px"
    >
      <div data-test="item-dialog">
        <el-form label-width="90px" @submit.prevent="submitItem">
          <el-form-item label="名称">
            <div data-test="item-name-field">
              <el-input
                v-model="itemForm.name"
                placeholder="服务项名称"
                maxlength="64"
              />
            </div>
          </el-form-item>
          <el-form-item label="基准价">
            <div data-test="item-price-field">
              <el-input-number
                v-model="itemForm.base_price"
                :min="0"
                :precision="2"
                :step="10"
                style="width: 100%"
              />
            </div>
          </el-form-item>
          <el-form-item label="时长">
            <div data-test="item-duration-field">
              <el-input-number
                v-model="itemForm.duration_min"
                :min="1"
                :max="1440"
                :step="30"
                style="width: 100%"
              />
            </div>
          </el-form-item>
          <el-form-item v-if="editingItemId !== null" label="状态">
            <div data-test="item-status-field">
              <el-select v-model="itemForm.status">
                <el-option
                  v-for="option in STATUS_OPTIONS"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </el-select>
            </div>
          </el-form-item>
        </el-form>
      </div>

      <template #footer>
        <el-button @click="itemVisible = false">取消</el-button>
        <el-button
          type="primary"
          data-test="submit-item-btn"
          :loading="itemSaving"
          @click="submitItem"
        >
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.catalog-layout {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}

.catalog-tree {
  width: 260px;
  min-height: 320px;
  padding: 8px;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  background-color: #fff;
}

.catalog-items {
  flex: 1;
}

.catalog-hint {
  margin: 0 0 8px;
  color: #606266;
}

.page-actions {
  display: flex;
  gap: 8px;
}
</style>
