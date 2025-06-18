export interface Song {
  radio_title: string;
  radio_artist: string;
  album_art_url?: string;
  reason?: string;
  year?: number;
  duration_ms?: number;
}

export interface AdminStats {
  total_songs_added: number;
  total_failures: number;
  success_rate: number;
  average_songs_per_day: number;
  most_common_artist: string;
  most_common_failure: string;
  last_check_time: string;
  next_check_time: string;
  average_duration?: number;
  decade_spread?: Record<string, number>;
  newest_song?: Song;
  oldest_song?: Song;
}

export interface ScriptSettings {
  check_interval: string;
  duplicate_check_interval: string;
  max_playlist_size: number;
}

export interface Status {
  current_song: string;
  last_added: string;
  daily_added: Song[];
  last_check_complete_time: string;
  next_check_time: string;
} 