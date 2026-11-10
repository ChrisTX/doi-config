// SPDX-FileCopyrightText: Christian Pfeiffer
// SPDX-License-Identifier: MIT OR GPL-3.0-only WITH LicenseRef-SourceMod-exception

// The configs of the game modes, in layers, whose settings are undone when the game mode changes, in
// Day of Infamy and Insurgency.
//
// At every map start, the game runs its own config of the map's game mode, cfg/default_server_
// <mode>.cfg (e.g. default_server_stronghold.cfg), and then cfg/server_<mode>.cfg if there's one. The
// plugin takes the game mode from the first, so no config of ours has to name it. Once the map's
// configs ran (OnConfigsExecuted), the game's included, it runs those of the game mode's configs that
// exist, in this order, so that a later one's setting replaces an earlier one's:
//
//     doi-config/basic_mode_<category>.cfg         all game modes of the category
//     doi-config/basic_mode_<category>-<mode>.cfg  the game mode, whatever the playlist
//     doi-config/playlists/<playlist>-<mode>.cfg   the playlist's own settings of the game mode, made
//                                                  by tools/make_mods.py
//     doi-config/mode_<playlist name>.cfg          all game modes of the playlist
//     doi-config/mode_<playlist name>-<mode>.cfg   the game mode in the playlist
//
// <category> is coop, pvp or solo: the game's coop modes are those whose rules derive from
// CINSRulesCoopBase, solo those of CINSRulesSinglePlayerBase (Insurgency's training), the others
// pvp; nwi_mode_category sets it for a game mode the plugin doesn't know. <playlist> is sv_playlist,
// e.g. nwi/coop_commando, <playlist name> its last part, coop_commando; a server without a playlist
// runs the first two.
//
// The configs set their cvars with nwi_mode_cvar "<cvar>" "<value>", which keeps the value the cvar
// had before. When the game mode changes, the cvars set since the last change get those values back
// before the new game mode's configs run, so that a setting of one game mode doesn't stay for the next
// one, which doesn't set it. The values are those of the server's configuration (init-*.cfg) or of
// the game, whatever the cvars had before a game mode's config first set them.
//
// Other plugins get the game mode from the natives and the forward of nwi_mode_config.inc.

#include <sourcemod>
#include <nwi>
#define NWI_MODE_CONFIG_PROVIDER
#include <nwi_mode_config>

#pragma semicolon 1
#pragma newdecls required

// Long enough for any cvar's name and value
#define CVAR_LENGTH 512

public Plugin myinfo =
{
    name        = "NWI mode config",
    author      = "DOI revival project",
    description = "Run the configs of a game mode and undo their settings when it changes",
    version     = "2.0",
    url         = "https://rev-crew.info"
};

// The game modes and their categories, from the games' rules classes (see above). A game mode
// missing here gets nwi_mode_category's category.
static const char g_doiModes[][][] =
{
    {"stronghold", "coop"}, {"entrenchment", "coop"}, {"raid", "coop"}, {"patrol", "coop"},
    {"offensive", "pvp"}, {"invasion", "pvp"}, {"frontline", "pvp"}, {"liberation", "pvp"},
    {"firefight", "pvp"}, {"sabotage", "pvp"}, {"intel", "pvp"}, {"assassination", "pvp"},
    {"sandbox", "pvp"}
};
static const char g_insurgencyModes[][][] =
{
    {"checkpoint", "coop"}, {"hunt", "coop"}, {"outpost", "coop"}, {"survival", "coop"},
    {"conquer", "coop"}, {"training", "solo"},
    {"push", "pvp"}, {"skirmish", "pvp"}, {"firefight", "pvp"}, {"ambush", "pvp"}, {"battle", "pvp"},
    {"elimination", "pvp"}, {"flashpoint", "pvp"}, {"infiltrate", "pvp"}, {"invasion", "pvp"},
    {"occupy", "pvp"}, {"strike", "pvp"}, {"vendetta", "pvp"}
};

NWIGame g_game;
ConVar g_current;
ConVar g_categoryOverride;
ConVar g_playlist;
GlobalForward g_onChanged;
char g_mode[NWI_MODE_LENGTH];
char g_category[NWI_MODE_LENGTH];
// The game mode of the map that's starting, until its configs run
char g_next[NWI_MODE_LENGTH];
// The cvars nwi_mode_cvar set since the game mode changed, in lower case, in the order they were
// first set, with the values they had before
ArrayList g_names;
StringMap g_previous;

public APLRes AskPluginLoad2(Handle myself, bool late, char[] error, int err_max)
{
    CreateNative("NWI_GetGameMode", Native_GetGameMode);
    CreateNative("NWI_GetGameModeCategory", Native_GetGameModeCategory);
    RegPluginLibrary(NWI_MODE_CONFIG_LIBRARY);
    return APLRes_Success;
}

public void OnPluginStart()
{
    g_game = NWI_RequireGame();
    g_names = new ArrayList(ByteCountToCells(CVAR_LENGTH));
    g_previous = new StringMap();
    g_playlist = FindConVar("sv_playlist");
    g_onChanged = new GlobalForward("NWI_OnGameModeChanged", ET_Ignore, Param_String, Param_String,
        Param_String);
    g_current = CreateConVar("nwi_mode_current", "",
        "The current game mode, for people (nwi_mode_config.smx); plugins use nwi_mode_config.inc",
        FCVAR_DONTRECORD);
    g_categoryOverride = CreateConVar("nwi_mode_category", "",
        "The category of the game modes nwi_mode_config.smx doesn't know: coop, pvp or solo");
    RegServerCmd("nwi_mode_cvar", Command_ModeCvar,
        "nwi_mode_cvar <cvar> <value>: set a cvar until the game mode changes");
    AddCommandListener(Listener_Exec, "exec");
}

// The game's config of the game mode, exec "default_server_<mode>.cfg", names the game mode. The
// server runs it, never a player (client 0 or -1, before the first map). Its contents run after this,
// so the game mode's configs wait for OnConfigsExecuted.
public Action Listener_Exec(int client, const char[] command, int argc)
{
    if (client > 0)
        return Plugin_Continue;
    char file[PLATFORM_MAX_PATH];
    GetCmdArg(1, file, sizeof(file));
    static const char prefix[] = "default_server_";
    int end = StrContains(file, ".cfg", false);
    if (strncmp(file, prefix, sizeof(prefix) - 1, false) != 0 || end == -1)
        return Plugin_Continue;
    file[end] = '\0';
    char mode[NWI_MODE_LENGTH];
    strcopy(mode, sizeof(mode), file[sizeof(prefix) - 1]);
    for (int i = 0; mode[i] != '\0'; i++)
        mode[i] = CharToLower(mode[i]);
    strcopy(g_next, sizeof(g_next), mode);
    return Plugin_Continue;
}

public void OnConfigsExecuted()
{
    if (g_next[0] == '\0')
        return;
    StartMode(g_next);
    g_next[0] = '\0';
}

void StartMode(const char[] mode)
{
    char previous[NWI_MODE_LENGTH];
    strcopy(previous, sizeof(previous), g_mode);
    bool changed = !StrEqual(mode, g_mode);
    if (changed)
    {
        RestoreCvars();
        strcopy(g_mode, sizeof(g_mode), mode);
        g_current.SetString(mode);
    }
    if (!Category(mode, g_category, sizeof(g_category)))
        LogError("The category of the game mode %s isn't known: set nwi_mode_category to coop, pvp or solo", mode);

    char playlist[PLATFORM_MAX_PATH] = "";
    if (g_playlist != null)
        g_playlist.GetString(playlist, sizeof(playlist));
    // The playlist's name, its part after the last slash
    int slash = FindCharInString(playlist, '/', true);
    char name[PLATFORM_MAX_PATH];
    strcopy(name, sizeof(name), playlist[slash + 1]);

    char configs[5][PLATFORM_MAX_PATH];
    if (g_category[0] != '\0')
    {
        Format(configs[0], sizeof(configs[]), "doi-config/basic_mode_%s.cfg", g_category);
        Format(configs[1], sizeof(configs[]), "doi-config/basic_mode_%s-%s.cfg", g_category, mode);
    }
    if (playlist[0] != '\0')
    {
        Format(configs[2], sizeof(configs[]), "doi-config/playlists/%s-%s.cfg", playlist, mode);
        Format(configs[3], sizeof(configs[]), "doi-config/mode_%s.cfg", name);
        Format(configs[4], sizeof(configs[]), "doi-config/mode_%s-%s.cfg", name, mode);
    }
    // Appended to the commands waiting, in their order
    for (int i = 0; i < sizeof(configs); i++)
    {
        char path[PLATFORM_MAX_PATH];
        Format(path, sizeof(path), "cfg/%s", configs[i]);
        if (configs[i][0] != '\0' && FileExists(path, true))
            ServerCommand("exec \"%s\"", configs[i]);
    }
    PrintToServer("nwi_mode_config: %s (%s), playlist %s", mode,
        g_category[0] != '\0' ? g_category : "unknown category", playlist[0] != '\0' ? playlist : "none");

    if (changed)
    {
        Call_StartForward(g_onChanged);
        Call_PushString(g_mode);
        Call_PushString(g_category);
        Call_PushString(previous);
        Call_Finish();
    }
}

// The game mode's category from the table of the game, else nwi_mode_category
bool Category(const char[] mode, char[] category, int maxlength)
{
    if (g_game == NWIGame_DoI)
    {
        for (int i = 0; i < sizeof(g_doiModes); i++)
            if (StrEqual(mode, g_doiModes[i][0]))
                return strcopy(category, maxlength, g_doiModes[i][1]) > 0;
    }
    else
    {
        for (int i = 0; i < sizeof(g_insurgencyModes); i++)
            if (StrEqual(mode, g_insurgencyModes[i][0]))
                return strcopy(category, maxlength, g_insurgencyModes[i][1]) > 0;
    }
    g_categoryOverride.GetString(category, maxlength);
    return category[0] != '\0';
}

public Action Command_ModeCvar(int args)
{
    if (args != 2)
    {
        PrintToServer("Usage: nwi_mode_cvar <cvar> <value>");
        return Plugin_Handled;
    }
    char name[CVAR_LENGTH], value[CVAR_LENGTH];
    GetCmdArg(1, name, sizeof(name));
    GetCmdArg(2, value, sizeof(value));
    ConVar cvar = FindConVar(name);
    if (cvar == null)
    {
        LogError("nwi_mode_cvar: there's no cvar %s", name);
        return Plugin_Handled;
    }
    // Cvars' names are case-insensitive
    for (int i = 0; name[i] != '\0'; i++)
        name[i] = CharToLower(name[i]);
    // The value before the first change since the game mode changed, which a map change in the same
    // game mode doesn't replace
    if (!g_previous.ContainsKey(name))
    {
        char previous[CVAR_LENGTH];
        cvar.GetString(previous, sizeof(previous));
        g_previous.SetString(name, previous);
        g_names.PushString(name);
    }
    cvar.SetString(value);
    return Plugin_Handled;
}

// Gives the cvars set since the game mode changed their values back, the last set first
void RestoreCvars()
{
    char name[CVAR_LENGTH], value[CVAR_LENGTH];
    for (int i = g_names.Length - 1; i >= 0; i--)
    {
        g_names.GetString(i, name, sizeof(name));
        g_previous.GetString(name, value, sizeof(value));
        ConVar cvar = FindConVar(name);
        if (cvar != null)
            cvar.SetString(value);
    }
    if (g_names.Length > 0)
        PrintToServer("nwi_mode_config: restored %d cvars of the previous game mode", g_names.Length);
    g_names.Clear();
    g_previous.Clear();
}

public any Native_GetGameMode(Handle plugin, int numParams)
{
    SetNativeString(1, g_mode, GetNativeCell(2));
    return g_mode[0] != '\0';
}

public any Native_GetGameModeCategory(Handle plugin, int numParams)
{
    SetNativeString(1, g_category, GetNativeCell(2));
    return g_category[0] != '\0';
}
