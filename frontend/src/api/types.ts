export interface Location {
  id: number;
  name: string;
  type: 'store' | 'warehouse';
  address: string | null;
  is_active: boolean;
}

export interface Category {
  id: number;
  name: string;
}

export interface Product {
  id: number;
  sku: string;
  barcode: string | null;
  name: string;
  category_id: number | null;
  category_name: string | null;
  unit: string;
  hsn_code: string | null;
  gst_rate: number;
  cost_price: number;
  selling_price: number;
  is_perishable: boolean;
  shelf_life_days: number | null;
  min_order_qty: number;
  pack_size: number;
  reorder_point: number | null;
  safety_stock: number | null;
  eoq: number | null;
  abc_class: string | null;
  xyz_class: string | null;
  reorder_paused: boolean;
  is_active: boolean;
}

export interface ProductRow extends Product {
  on_hand: number;
  on_order: number;
  available: number;
  stock_status: 'ok' | 'low' | 'out';
}

export interface Supplier {
  id: number;
  name: string;
  contact_name: string | null;
  email: string | null;
  phone: string | null;
  gstin: string | null;
  state: string;
  address: string | null;
  payment_terms_days: number;
  is_active: boolean;
}

export interface SupplierRow extends Supplier {
  score: number | null;
  on_time_pct: number | null;
  products: number;
}

export interface SupplierPrice {
  id: number;
  supplier_id: number;
  product_id: number;
  unit_price: number;
  lead_time_days: number;
  min_order_qty: number;
  valid_till: string | null;
  supplier_name: string | null;
  product_name: string | null;
  product_sku: string | null;
}

export interface Batch {
  id: number;
  product_id: number;
  location_id: number;
  batch_no: string;
  expiry_date: string | null;
  qty_on_hand: number;
  cost_price: number;
  received_at: string;
  markdown_pct: number;
  is_blocked: boolean;
  supplier_id: number | null;
  product_name: string | null;
  product_sku: string | null;
  location_name: string | null;
  days_to_expiry: number | null;
}

export interface Movement {
  id: number;
  product_id: number;
  batch_id: number | null;
  location_id: number;
  type: string;
  qty: number;
  unit_cost: number;
  reference_type: string | null;
  reference_id: number | null;
  note: string | null;
  created_at: string;
  product_name: string | null;
  batch_no: string | null;
  user_name: string | null;
}

export interface Position {
  on_hand: number;
  on_order: number;
  available: number;
}

export interface Lookup {
  product: {
    id: number;
    sku: string;
    name: string;
    barcode: string | null;
    unit: string;
    selling_price: number;
    cost_price: number;
    gst_rate: number;
    is_perishable: boolean;
    shelf_life_days: number | null;
    pack_size: number;
  };
  batch: Batch | null;
  stock: Position;
}

export interface SaleLine {
  id: number;
  product_id: number;
  batch_id: number | null;
  qty: number;
  unit_price: number;
  discount_pct: number;
  gst_rate: number;
  line_total: number;
  product_name: string | null;
}

export interface Sale {
  id: number;
  invoice_no: string;
  location_id: number;
  sold_at: string;
  channel: string;
  customer_name: string | null;
  subtotal: number;
  tax: number;
  total: number;
  lines: SaleLine[];
}

export interface UserRow {
  id: number;
  name: string;
  email: string;
  phone: string | null;
  role: string;
  supplier_id: number | null;
  language: string;
  is_active: boolean;
  totp_enabled: boolean;
  telegram_chat_id: string | null;
  last_login_at: string | null;
  created_at: string;
}
