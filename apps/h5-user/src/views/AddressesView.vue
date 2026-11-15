<script setup lang="ts">
/**
 * 地址管理页：列表 + 新建 + 编辑 + 删除。
 *
 * 数据全部来自接口：
 * - 列表 GET /api/v1/addresses
 * - 新建 POST /api/v1/addresses
 * - 编辑 PUT  /api/v1/addresses/{id}
 * - 删除 DELETE /api/v1/addresses/{id}（204，无响应体）
 *
 * 地址归属由服务端按 token 决定，页面里不出现 user_id 字段。
 *
 * 保存 / 删除之后都**重新拉一遍列表**，不靠本地数组改：
 * 服务端才是事实来源，本地改数组迟早跟服务端对不上。
 */
import { onMounted, ref } from "vue";

import { api } from "@/api";
import type { components } from "@oto/shared/api";

type AddressResponse = components["schemas"]["AddressResponse"];

const addresses = ref<AddressResponse[]>([]);
const loading = ref(true);
const error = ref("");

/** 表单弹层 */
const showForm = ref(false);
/** 正在编辑的地址 id；null 表示新建 */
const editingId = ref<number | null>(null);
const form = ref({ contact: "", phone: "", region: "", detail: "" });
const saving = ref(false);

/** 删除确认弹层 */
const deleting = ref<AddressResponse | null>(null);

onMounted(load);

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    addresses.value = await api.listAddresses();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "地址加载失败";
  } finally {
    loading.value = false;
  }
}

function openCreate(): void {
  editingId.value = null;
  form.value = { contact: "", phone: "", region: "", detail: "" };
  showForm.value = true;
}

function openEdit(address: AddressResponse): void {
  editingId.value = address.id;
  form.value = {
    contact: address.contact,
    phone: address.phone,
    region: address.region,
    detail: address.detail,
  };
  showForm.value = true;
}

async function save(): Promise<void> {
  const payload = {
    contact: form.value.contact.trim(),
    phone: form.value.phone.trim(),
    region: form.value.region.trim(),
    detail: form.value.detail.trim(),
  };
  if (!payload.contact || !payload.phone || !payload.region || !payload.detail) {
    error.value = "请把地址填完整";
    return;
  }
  saving.value = true;
  error.value = "";
  try {
    if (editingId.value === null) {
      await api.createAddress(payload);
    } else {
      await api.updateAddress({ address_id: editingId.value }, payload);
    }
    showForm.value = false;
    await load();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "保存失败";
  } finally {
    saving.value = false;
  }
}

async function confirmDelete(): Promise<void> {
  const target = deleting.value;
  if (!target) return;
  deleting.value = null;
  error.value = "";
  try {
    await api.deleteAddress({ address_id: target.id });
    await load();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "删除失败";
  }
}
</script>

<template>
  <div class="page">
    <h2 class="page-title">我的地址</h2>

    <van-loading v-if="loading" size="24" data-test="loading">加载中</van-loading>
    <p v-else-if="error" class="page-error" data-test="error">{{ error }}</p>
    <van-empty
      v-else-if="addresses.length === 0"
      image="search"
      description="还没有地址，先添加一个吧"
      data-test="empty"
    />

    <van-cell-group v-else inset>
      <van-cell v-for="address in addresses" :key="address.id" data-test="address-item">
        <template #title>
          <span class="item-name">{{ address.contact }} {{ address.phone }}</span>
        </template>
        <template #label>
          <span class="item-meta">
            {{ address.region }} {{ address.detail }}
          </span>
        </template>
        <template #value>
          <div class="slot-list">
            <van-button
              size="small"
              plain
              data-test="edit-address"
              @click="openEdit(address)"
            >
              编辑
            </van-button>
            <van-button
              size="small"
              plain
              type="danger"
              data-test="delete-address"
              @click="deleting = address"
            >
              删除
            </van-button>
          </div>
        </template>
      </van-cell>
    </van-cell-group>

    <div class="page-footer">
      <van-button type="primary" block data-test="create-address" @click="openCreate">
        新建地址
      </van-button>
    </div>

    <!-- 新建 / 编辑表单 -->
    <van-popup v-model:show="showForm" position="bottom" round>
      <div class="page">
        <h2 class="page-title">{{ editingId === null ? "新建地址" : "编辑地址" }}</h2>
        <van-cell-group inset>
          <van-field
            v-model="form.contact"
            label="联系人"
            placeholder="联系人"
            data-test="form-contact"
          />
          <van-field
            v-model="form.phone"
            type="tel"
            label="电话"
            placeholder="联系电话"
            data-test="form-phone"
          />
          <van-field
            v-model="form.region"
            label="地区"
            placeholder="省市区"
            data-test="form-region"
          />
          <van-field
            v-model="form.detail"
            label="详细地址"
            placeholder="街道、门牌号"
            data-test="form-detail"
          />
        </van-cell-group>
        <div class="page-footer">
          <van-button data-test="cancel-address" @click="showForm = false">取消</van-button>
          <van-button
            type="primary"
            :loading="saving"
            data-test="save-address"
            @click="save"
          >
            保存
          </van-button>
        </div>
      </div>
    </van-popup>

    <!-- 删除确认 -->
    <van-dialog
      :show="deleting !== null"
      title="删除地址"
      @update:show="deleting = null"
    >
      <p class="page-label">确定要删除这条地址吗？</p>
      <template #footer>
        <van-button data-test="cancel-delete" @click="deleting = null">取消</van-button>
        <van-button type="danger" data-test="confirm-delete" @click="confirmDelete">
          删除
        </van-button>
      </template>
    </van-dialog>
  </div>
</template>
