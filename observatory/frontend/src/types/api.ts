export type ApiResponse<T = unknown> = {
  success: boolean;
  data?: T;
  message?: string;
  error?: string;
};

export type AnyRecord = Record<string, any>;

export type DashboardData = {
  started_at?: number;
  tick_counter?: number;
  config?: AnyRecord;
  last_report?: AnyRecord;
  state?: AnyRecord;
  hdb?: AnyRecord;
  action_runtime?: AnyRecord;
  [key: string]: any;
};

export type DatasetRef = {
  source: string;
  rel_path: string;
};

export type DatasetItem = {
  dataset_ref?: DatasetRef;
  ref?: DatasetRef;
  dataset_id?: string;
  title?: string;
  description?: string;
  estimated_ticks?: number;
  effective_text_ticks?: number;
  empty_ticks?: number;
  [key: string]: any;
};

export type ExperimentRunItem = {
  run_id: string;
  status?: string;
  dataset_id?: string;
  tick_done?: number;
  tick_planned?: number;
  source_tick_done?: number;
  synthetic_tick_done?: number;
  [key: string]: any;
};

export type MetricRow = Record<string, any>;
