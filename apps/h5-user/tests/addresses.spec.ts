/**
 * 必测 3：地址列表渲染 + 新建后刷新。
 *
 * 钉住两件事：
 * - 列表渲染的是接口返回的地址（不是写死的占位数据）；
 * - 新建成功后**重新拉一遍列表**（不靠本地数组改），
 *   新地址出现在列表里。
 */
import { flushPromises, mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AddressesView from "@/views/AddressesView.vue";

import { mockClient } from "./client-mock";
import { setupApp } from "./helpers";

vi.mock("@oto/shared/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@oto/shared/api")>();
  const { mockClient: client } = await import("./client-mock");
  return { ...actual, createApiClient: () => client };
});

const ADDRESS_A = {
  id: 1,
  contact: "张三",
  phone: "13800000001",
  region: "北京",
  detail: "某街道 1 号",
};

const ADDRESS_B = {
  id: 2,
  contact: "李四",
  phone: "13800000002",
  region: "上海",
  detail: "某路 2 号",
};

const ADDRESS_C = {
  id: 3,
  contact: "王五",
  phone: "13800000003",
  region: "广东 深圳",
  detail: "科技园 5 号楼 301",
};

describe("地址页", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockClient.listAddresses.mockResolvedValue([ADDRESS_A, ADDRESS_B]);
    mockClient.createAddress.mockResolvedValue(ADDRESS_C);
  });

  it("渲染接口返回的地址列表", async () => {
    const { pinia, router } = await setupApp("/addresses");

    const wrapper = mount(AddressesView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(mockClient.listAddresses).toHaveBeenCalledTimes(1);
    const items = wrapper.findAll('[data-test="address-item"]');
    expect(items).toHaveLength(2);
    expect(items[0].text()).toContain("张三");
    expect(items[0].text()).toContain("北京");
    expect(items[1].text()).toContain("李四");
  });

  it("没有地址时显示空状态", async () => {
    mockClient.listAddresses.mockResolvedValue([]);

    const { pinia, router } = await setupApp("/addresses");
    const wrapper = mount(AddressesView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    expect(wrapper.findAll('[data-test="address-item"]')).toHaveLength(0);
    expect(wrapper.find('[data-test="empty"]').exists()).toBe(true);
  });

  it("新建地址后刷新列表，新地址出现在列表里", async () => {
    const { pinia, router } = await setupApp("/addresses");

    const wrapper = mount(AddressesView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    // 新建成功后服务端多了一条：让下一次拉取返回三条
    mockClient.listAddresses.mockResolvedValue([ADDRESS_A, ADDRESS_B, ADDRESS_C]);

    await wrapper.find('[data-test="create-address"]').trigger("click");
    await flushPromises();

    await wrapper.find('[data-test="form-contact"] input').setValue("王五");
    await wrapper.find('[data-test="form-phone"] input').setValue("13800000003");
    await wrapper.find('[data-test="form-region"] input').setValue("广东 深圳");
    await wrapper.find('[data-test="form-detail"] input').setValue("科技园 5 号楼 301");
    await flushPromises();

    await wrapper.find('[data-test="save-address"]').trigger("click");
    await flushPromises();

    expect(mockClient.createAddress).toHaveBeenCalledWith({
      contact: "王五",
      phone: "13800000003",
      region: "广东 深圳",
      detail: "科技园 5 号楼 301",
    });
    // 保存后重新拉了列表（不是本地改数组）
    expect(mockClient.listAddresses).toHaveBeenCalledTimes(2);
    const items = wrapper.findAll('[data-test="address-item"]');
    expect(items).toHaveLength(3);
    expect(items[2].text()).toContain("王五");
  });

  it("编辑地址走 PUT，带上地址 id", async () => {
    mockClient.updateAddress.mockResolvedValue({
      ...ADDRESS_A,
      contact: "张小三",
    });

    const { pinia, router } = await setupApp("/addresses");
    const wrapper = mount(AddressesView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    await wrapper.findAll('[data-test="edit-address"]')[0].trigger("click");
    await flushPromises();

    await wrapper.find('[data-test="form-contact"] input').setValue("张小三");
    await flushPromises();

    await wrapper.find('[data-test="save-address"]').trigger("click");
    await flushPromises();

    expect(mockClient.updateAddress).toHaveBeenCalledWith(
      { address_id: ADDRESS_A.id },
      expect.objectContaining({ contact: "张小三" }),
    );
  });

  it("删除地址走 DELETE，并刷新列表", async () => {
    mockClient.deleteAddress.mockResolvedValue(undefined);

    const { pinia, router } = await setupApp("/addresses");
    const wrapper = mount(AddressesView, { global: { plugins: [pinia, router] } });
    await flushPromises();

    // 删掉 A 之后，服务端只剩 B
    mockClient.listAddresses.mockResolvedValue([ADDRESS_B]);

    await wrapper.findAll('[data-test="delete-address"]')[0].trigger("click");
    await flushPromises();

    await wrapper.find('[data-test="confirm-delete"]').trigger("click");
    await flushPromises();

    expect(mockClient.deleteAddress).toHaveBeenCalledWith({
      address_id: ADDRESS_A.id,
    });
    expect(mockClient.listAddresses).toHaveBeenCalledTimes(2);
    expect(wrapper.findAll('[data-test="address-item"]')).toHaveLength(1);
  });
});
