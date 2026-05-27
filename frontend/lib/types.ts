export interface DataPeriod {
  start: string | null
  end: string | null
  is_db_empty: boolean
}

export interface DistrictRef {
  id: string
  name_ru: string
  name_en: string
}

export interface DistrictMetrics {
  district_id: string
  name_ru: string
  total_posts: number
  negative: number
  neutral: number
  positive: number
  activity: number
  negativity_score: number   // 0..1
  neg_share: number
  delta_vs_city: number
}

export interface Comment {
  author: string
  user_id: number
  user_url: string | null
  group: string
  group_url: string | null
  text: string
  sentiment: 'negative' | 'neutral' | 'positive'
  score: number
  created_at: string
  district_id: string | null
  comment_url: string | null
}

export interface SentimentBucket {
  date: string
  negative: number
  neutral: number
  positive: number
}

export interface Topic {
  topic_id: number
  label: string
  keywords: string
  count: number
  neg_share: number
}

export interface Burst {
  date: string
  topic_label: string
  volume: number
  z_score: number
  intensity: 'low' | 'medium' | 'high'
  neg_share: number | null
}

export interface TopUser {
  user_id: number
  name: string
  user_url: string
  comments_in_period: number
  avg_sentiment: number
  districts: string[]
  suspected_bot: boolean
}

export interface RefreshStatus {
  is_running: boolean
  pid: number | null
  started_at: number | null
  last_result: string | null
  log_tail: string | null
}

export interface GroupOut {
  id: number
  name: string
  screen_name: string
  district_id: string | null
  is_citywide: boolean
}

export interface DistrictMetrics {
  district_id: string
  name_ru: string
  total_posts: number
  negative: number
  neutral: number
  positive: number
  activity: number
  negativity_score: number
  neg_share: number
  delta_vs_city: number
  // Новые поля:
  unique_authors: number
  prev_total_posts: number
  prev_unique_authors: number
  prev_neg_share: number
  delta_activity: number
  delta_neg_share: number
}