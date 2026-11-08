// SPDX-FileCopyrightText: Christian Pfeiffer
// SPDX-License-Identifier: MIT OR GPL-3.0-only WITH LicenseRef-SourceMod-exception

// Lifts limits of Day of Infamy's cvars that the servers' configuration needs to exceed: the
// upper bounds of the coop lobby size and the round timers, and the cheat flag of the bot and
// voice cvars, so the configs can set them without sv_cheats.

#include <sourcemod>
#include <sdktools>
#include <doi>

public Plugin myinfo =
{
    name    = "DOI CVAR unlocker",
    author    = "DOI revival project",
    description = "Overwrite CVAR limits and remove undesirable cheat flags",
    version   = "1.0",
    url   = "https://rev-crew.info"
}

public OnPluginStart() {
    DOI_RequireGame();
    // The changes are applied again at these events in case the game resets the bounds or flags,
    // e.g. on a map change; the pre hooks apply them before the event reaches other listeners.
    HookEvent("server_spawn", Event_GameStart, EventHookMode_Pre);
    HookEvent("game_init", Event_GameStart, EventHookMode_Pre);
    HookEvent("game_start", Event_GameStart, EventHookMode_Pre);
    HookEvent("game_newmap", Event_GameStart, EventHookMode_Pre);
    AdjustDOICVars();
}

public Event_GameStart(Handle:event, const String:name[], bool:dontBroadcast) {
    AdjustDOICVars();
}

// Sets the upper bound of a cvar, replacing the game's own; a value above it is lowered to it
public SetVarUpperBound(const String:name[], const float fMax) {
    Handle my_cvar = FindConVar(name);
    // A cvar a game update removed would stop the remaining changes with a native error
    if (my_cvar == null) {
        LogError("Can't find the cvar %s", name);
        return;
    }
    SetConVarBounds(my_cvar, ConVarBound_Upper, true, fMax);
    if (GetConVarFloat(my_cvar) > fMax)
        SetConVarFloat(my_cvar, fMax);
}

// Clears a flag (FCVAR_*) of a cvar
public RemoveFlag(const String:name[], const int CVarFlag) {
    Handle my_cvar = FindConVar(name);
    if (my_cvar == null) {
        LogError("Can't find the cvar %s", name);
        return;
    }
    int srda_flags = GetConVarFlags(my_cvar);
    srda_flags &= ~CVarFlag;
    SetConVarFlags(my_cvar, srda_flags);
}

// Lets the cvar be set without sv_cheats
public RemoveCheatFlag(const String:name[]) {
    RemoveFlag(name, FCVAR_CHEAT);
}

// Stops the server announcing changes of the cvar to the players
public RemoveNotifyFlag(const String:name[]) {
    RemoveFlag(name, FCVAR_NOTIFY);
}

public AdjustDOICVars() {
    // The coop lobby, the human players, can take the slots of their team (doi.inc): 16 by the
    // game's rules, with maxplayers 33 (basic_coop.cfg), but fewer with fewer slots. The game's own
    // bound is 25. mp_coop_lobbysize is Insurgency's, which Day of Infamy may not use any more.
    SetVarUpperBound("doi_coop_lobby_size", float(DOI_TeamSlots(DOI_COOP_TEAM_SLOTS)));
    SetVarUpperBound("mp_coop_lobbysize", float(DOI_TeamSlots(DOI_COOP_TEAM_SLOTS)));
    // Allow the round and game phase timers up to ten minutes
    SetVarUpperBound("mp_timer_pregame", 600.0);
    SetVarUpperBound("mp_timer_postgame", 600.0);
    SetVarUpperBound("mp_timer_postround", 600.0);
    SetVarUpperBound("mp_timer_preround", 600.0);
    SetVarUpperBound("mp_timer_preround_first", 600.0);
    SetVarUpperBound("mp_timer_preround_switch", 600.0);
    SetVarUpperBound("mp_timer_taglines", 600.0);
    SetVarUpperBound("mp_timer_voting", 600.0);
    // Bot behaviour, set by doi-config/bot_logic.cfg
    RemoveCheatFlag("doi_bot_aim_aimtracking_base");
    RemoveCheatFlag("doi_bot_awareness_conversation_range");
    RemoveCheatFlag("doi_bot_fov_idle");
    RemoveCheatFlag("doi_bot_newthreat_search_interval");
    RemoveCheatFlag("doi_bot_path_compute_throttle_combat");
    RemoveCheatFlag("doi_bot_path_compute_throttle_idle");
    RemoveCheatFlag("doi_bot_silhouette_discover_timer");
    RemoveCheatFlag("doi_bot_silhouette_scan_frequency");
    RemoveCheatFlag("doi_bot_vis_foliage_threshold");
    // Proximity voice chat ranges, set by doi-config/basic_pvp.cfg
    RemoveCheatFlag("mp_voice_max_distance_friendly");
    RemoveCheatFlag("mp_voice_max_distance_enemy");
    // Not set by any config of this repository, so only by hand
    RemoveCheatFlag("sv_radial_debug_artillery");
}
