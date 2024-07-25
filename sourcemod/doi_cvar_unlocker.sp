#include <sourcemod>
#include <sdktools>

public Plugin myinfo =
{
  name    = "DoI CVAR unlocker",
  author    = "REV-CREW",
  description = "Overwrite CVAR limits and remove undesirable cheat flags",
  version   = "1.0",
  url   = "https://rev-crew.info"
}

public OnPluginStart() {
  HookEvent("server_spawn", Event_GameStart, EventHookMode_Pre);
  HookEvent("game_init", Event_GameStart, EventHookMode_Pre);
  HookEvent("game_start", Event_GameStart, EventHookMode_Pre);
  HookEvent("game_newmap", Event_GameStart, EventHookMode_Pre);
  AdjustDoICVars();
}

public Event_GameStart(Handle:event, const String:name[], bool:dontBroadcast) {
  AdjustDoICVars();
}

public SetVarUpperBound(const String:name[], Float:fMax) {
  Handle my_cvar = FindConVar(name);
  SetConVarBounds(my_cvar, ConVarBound_Upper, true, fMax);
}

public RemoveCheatFlag(const String:name[]) {
  Handle my_cvar = FindConVar(name);
  int srda_flags = GetConVarFlags(my_cvar);
  srda_flags &= ~FCVAR_CHEAT;
  SetConVarFlags(my_cvar, srda_flags);
}

public RemoveNotifyFlag(const String:name[]) {
  Handle my_cvar = FindConVar(name);
  int srda_flags = GetConVarFlags(my_cvar);
  srda_flags &= ~FCVAR_NOTIFY;
  SetConVarFlags(my_cvar, srda_flags);
}

public AdjustDoICVars() {
  SetVarUpperBound("mp_coop_lobbysize", MaxClients - 24.0);
  SetVarUpperBound("mp_timer_pregame", 600.0);
  SetVarUpperBound("mp_timer_postgame", 600.0);
  SetVarUpperBound("mp_timer_postround", 600.0);
  SetVarUpperBound("mp_timer_preround", 600.0);
  SetVarUpperBound("mp_timer_preround_first", 600.0);
  SetVarUpperBound("mp_timer_preround_switch", 600.0);
  SetVarUpperBound("mp_timer_taglines", 600.0);
  SetVarUpperBound("mp_timer_voting", 600.0);
  RemoveCheatFlag("doi_bot_aim_aimtracking_base");
  RemoveCheatFlag("doi_bot_awareness_conversation_range");
  RemoveCheatFlag("doi_bot_fov_idle");
  RemoveCheatFlag("doi_bot_newthreat_search_interval");
  RemoveCheatFlag("doi_bot_path_compute_throttle_combat");
  RemoveCheatFlag("doi_bot_path_compute_throttle_idle");
  RemoveCheatFlag("doi_bot_silhouette_discover_timer");
  RemoveCheatFlag("doi_bot_silhouette_scan_frequency");
  RemoveCheatFlag("doi_bot_vis_foliage_threshold");
  RemoveCheatFlag("mp_voice_max_distance_friendly");
  RemoveCheatFlag("mp_voice_max_distance_enemy");
  RemoveCheatFlag("sv_radial_debug_artillery");
  RemoveNotifyFlag("mp_cp_capture_time");
}
