// Tipos del Laboratorio de modelos (respuestas de /api/v1/ml).

export interface Excluded { name: string; source: string; reason: string }
export interface Feature { name: string; type: 'num' | 'cat'; source: string; description: string }
export interface Source { kind: string; name: string; license: string; url: string; file?: string; bytes?: number; sha256?: string; fetched_at?: string; date?: string; year?: number; model_version?: string; cached?: boolean; entries?: number; last_date_added?: string }
export interface DatasetStats { rows?: number; positives?: number; snapshots?: string[]; by_split?: Record<string, { rows: number; positives: number; snapshots: number; events?: number }>; events?: number; embargo_days?: number; split_snapshots?: Record<string, string[]>; nvd_cves?: number; edb_exploits?: number; error?: string }
export interface Dataset {
  id: string; name: string; description: string; notes: string; tags: string[]; status: 'building' | 'ready' | 'failed'
  params: { start: string; until: string; horizon_days: number; neg_rate: number; seed: number; snapshots: number; split: string; embargo?: boolean }
  sources: Source[]; stats: DatasetStats; created_at: string | null; updated_at: string | null; features?: Feature[]; excluded?: Excluded[]
}
export interface Job { id: string; kind: string; status: 'queued' | 'running' | 'done' | 'failed'; progress: number; message: string; log: { t: string; pct: number; msg: string }[]; target_id: string | null; started_at: string; finished_at: string | null }

export interface Check { key: string; label: string; status: 'ok' | 'warn' | 'info'; detail: string }
export interface NumericRow { name: string; description: string; missing_pct: number; median_pos: number | null; median_neg: number | null; p75_pos: number | null; p75_neg: number | null; auc: number | null; hist: { label: string; neg: number; pos: number }[] }
export interface CategoricalRow { name: string; description: string; cardinality: number; top: { value: string; rows: number; positives: number; prevalence_pct: number | null; small: boolean }[] }
export interface Profile {
  overview: { rows: number; positives: number; negatives_sampled: number; neg_rate: number; universe_estimate: number; prevalence_pct: number | null; snapshots: number; cves: number }
  snapshots: { snapshot: string; split: string; rows: number; positives: number; prevalence_pct: number | null; epss_model: string }[]
  splits: { split: string; label: string; rows: number; positives: number; snapshots: number; from: string; to: string; share_pct: number; prevalence_pct: number | null }[]
  numeric: NumericRow[]; categorical: CategoricalRow[]; checks: Check[]; interpretation: string[]
  how_to_read: { splits: string; numeric: string; categorical: string; checks: string }
}
