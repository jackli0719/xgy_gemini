/**
 * 地址占位数据。
 *
 * 后端目前**没有**「我的地址」接口（apps/api/openapi.json 里查无此路径），
 * 所以本卡先写死一个占位地址：卡片允许「本卡先写死一个 address_id 占位」。
 *
 * FE-03 上了地址接口之后，把这个文件换成一次 API 调用即可，
 * 页面（OrderNewView）不用改 —— 它只认 `id` 和 `label` 两个字段。
 */
export interface AddressOption {
  id: number;
  label: string;
}

export const PLACEHOLDER_ADDRESSES: AddressOption[] = [
  { id: 1, label: "默认地址（占位：地址接口待 FE-03）" },
];
