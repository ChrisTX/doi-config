// SPDX-FileCopyrightText: Christian Pfeiffer
// SPDX-License-Identifier: MIT OR GPL-3.0-only WITH LicenseRef-SourceMod-exception

// Lifts limits of the game's cvars that the servers' configuration needs to exceed, in Day of Infamy
// and Insurgency: their bounds, and flags like cheat, so the configs can set them without sv_cheats.
// Which cvars, and how, is in configs/nwi_cvar_unlocker.cfg, a section per game; the plugin reads it
// at each map start, and applies it again at the game's events of a new game or map, in case the
// game resets the bounds or flags.

#include <sourcemod>
#include <nwi>

#pragma semicolon 1
#pragma newdecls required

#define CONFIG "configs/nwi_cvar_unlocker.cfg"

public Plugin myinfo =
{
    name        = "NWI cvar unlocker",
    author      = "DOI revival project",
    description = "Overwrite cvar bounds and remove undesirable flags, by config",
    version     = "2.0",
    url         = "https://rev-crew.info"
};

public void OnPluginStart()
{
    NWI_RequireGame();
    // The pre hooks apply the changes before the event reaches other listeners
    HookEvent("server_spawn", Event_GameStart, EventHookMode_Pre);
    HookEventEx("game_init", Event_GameStart, EventHookMode_Pre);
    HookEventEx("game_start", Event_GameStart, EventHookMode_Pre);
    HookEventEx("game_newmap", Event_GameStart, EventHookMode_Pre);
    RegServerCmd("nwi_cvar_unlocker_reload", Command_Reload, "Apply configs/nwi_cvar_unlocker.cfg again");
    Apply();
}

public void OnMapStart()
{
    Apply();
}

public void Event_GameStart(Event event, const char[] name, bool dontBroadcast)
{
    Apply();
}

public Action Command_Reload(int args)
{
    Apply();
    return Plugin_Handled;
}

// Applies the section of the game in the config
void Apply()
{
    char path[PLATFORM_MAX_PATH], game[PLATFORM_MAX_PATH];
    BuildPath(Path_SM, path, sizeof(path), CONFIG);
    KeyValues kv = new KeyValues("nwi_cvar_unlocker");
    if (!kv.ImportFromFile(path))
    {
        LogError("Can't read %s", path);
        delete kv;
        return;
    }
    GetGameFolderName(game, sizeof(game));
    if (kv.JumpToKey(game))
    {
        ApplyBounds(kv);
        ApplyFlags(kv);
    }
    delete kv;
}

void ApplyBounds(KeyValues kv)
{
    if (!kv.JumpToKey("bounds"))
        return;
    char name[256], value[64], parts[4][16];
    if (kv.GotoFirstSubKey(false))
    {
        do
        {
            kv.GetSectionName(name, sizeof(name));
            kv.GetString(NULL_STRING, value, sizeof(value));
            int count = ExplodeString(value, " ", parts, sizeof(parts), sizeof(parts[]));
            ConVar cvar = Find(name);
            if (cvar == null)
                continue;
            if (count >= 1 && !StrEqual(parts[0], "-"))
                SetBound(cvar, ConVarBound_Lower, StringToFloat(parts[0]));
            if (count >= 3 && StrEqual(parts[1], "team_slots"))
                SetBound(cvar, ConVarBound_Upper, float(NWI_TeamSlots(StringToInt(parts[2]))));
            else if (count == 2 && !StrEqual(parts[1], "-"))
                SetBound(cvar, ConVarBound_Upper, StringToFloat(parts[1]));
            else if (count != 2 && count != 3)
                LogError("%s: the bounds of %s aren't \"<min> <max>\": %s", CONFIG, name, value);
        } while (kv.GotoNextKey(false));
        kv.GoBack();
    }
    kv.GoBack();
}

// Sets a bound, and moves the value within it
void SetBound(ConVar cvar, ConVarBounds type, float bound)
{
    cvar.SetBounds(type, true, bound);
    if (type == ConVarBound_Upper ? cvar.FloatValue > bound : cvar.FloatValue < bound)
        cvar.FloatValue = bound;
}

void ApplyFlags(KeyValues kv)
{
    if (!kv.JumpToKey("remove_flags"))
        return;
    char name[256], value[64], flags[4][16];
    if (kv.GotoFirstSubKey(false))
    {
        do
        {
            kv.GetSectionName(name, sizeof(name));
            kv.GetString(NULL_STRING, value, sizeof(value));
            ConVar cvar = Find(name);
            if (cvar == null)
                continue;
            int remove = 0;
            int count = ExplodeString(value, " ", flags, sizeof(flags), sizeof(flags[]));
            for (int i = 0; i < count; i++)
            {
                if (StrEqual(flags[i], "cheat"))
                    remove |= FCVAR_CHEAT;
                else if (StrEqual(flags[i], "notify"))
                    remove |= FCVAR_NOTIFY;
                else if (flags[i][0] != '\0')
                    LogError("%s: unknown flag %s of %s", CONFIG, flags[i], name);
            }
            cvar.Flags &= ~remove;
        } while (kv.GotoNextKey(false));
        kv.GoBack();
    }
    kv.GoBack();
}

// A cvar of the config; one a game update removed is an error, but doesn't stop the others
ConVar Find(const char[] name)
{
    ConVar cvar = FindConVar(name);
    if (cvar == null)
        LogError("%s: there's no cvar %s", CONFIG, name);
    return cvar;
}
