// SPDX-FileCopyrightText: Christian Pfeiffer
// SPDX-License-Identifier: MIT OR GPL-3.0-only WITH LicenseRef-SourceMod-exception

// The configs of the game modes, in layers, whose settings are undone when the game mode changes.
//
// The game runs cfg/server_<mode>.cfg at every map start, and ours only name the game mode and its
// category, coop or pvp:
//
//     doi_mode "coop" "stronghold"
//
// On that, this runs those of the game mode's configs that exist, in this order, so that a later one's
// setting replaces an earlier one's:
//
//     doi-config/basic_mode_<category>.cfg         all game modes of the category
//     doi-config/basic_mode_<category>-<mode>.cfg  the game mode, whatever the playlist
//     doi-config/playlists/<playlist>-<mode>.cfg   the playlist's own settings of the game mode, made
//                                                  by tools/make_mods.py
//     doi-config/mode_<playlist name>.cfg          all game modes of the playlist
//     doi-config/mode_<playlist name>-<mode>.cfg   the game mode in the playlist
//
// <playlist> is sv_playlist, e.g. nwi/coop_commando, <playlist name> its last part, coop_commando.
//
// The configs set their cvars with doi_mode_cvar "<cvar>" "<value>", which keeps the value the cvar
// had before. When the game mode changes, the cvars set since the last change get those values back
// before the new game mode's configs run, so that a setting of one game mode doesn't stay for the next
// one, which doesn't set it. The values are those of the server's configuration (init-*.cfg) or of
// the game, whatever the cvars had before a game mode's config first set them.
//
// The current game mode is in doi_mode_current, e.g. for doi_difficulty_scaler.sp.

#include <sourcemod>
#include <doi>

#pragma semicolon 1
#pragma newdecls required

// Long enough for any cvar's name and value
#define CVAR_LENGTH 512

public Plugin myinfo =
{
    name        = "DOI mode config",
    author      = "DOI revival project",
    description = "Run the configs of a game mode and undo their settings when it changes",
    version     = "1.0",
    url         = "https://rev-crew.info"
};

ConVar g_current;
ConVar g_playlist;
// The cvars doi_mode_cvar set since the game mode changed, in lower case, in the order they were
// first set, with the values they had before
ArrayList g_names;
StringMap g_previous;

public void OnPluginStart()
{
    DOI_RequireGame();
    g_names = new ArrayList(ByteCountToCells(CVAR_LENGTH));
    g_previous = new StringMap();
    g_playlist = FindConVar("sv_playlist");
    g_current = CreateConVar("doi_mode_current", "",
        "The current game mode, as the last doi_mode named it (doi_mode_config.smx)", FCVAR_DONTRECORD);
    RegServerCmd("doi_mode", Command_Mode,
        "doi_mode <coop|pvp> <mode>: run the configs of a game mode, see doi_mode_config.sp");
    RegServerCmd("doi_mode_cvar", Command_ModeCvar,
        "doi_mode_cvar <cvar> <value>: set a cvar until the game mode changes");
}

public Action Command_Mode(int args)
{
    if (args != 2) {
        PrintToServer("Usage: doi_mode <coop|pvp> <mode>");
        return Plugin_Handled;
    }
    char category[16], mode[32], current[32];
    GetCmdArg(1, category, sizeof(category));
    GetCmdArg(2, mode, sizeof(mode));
    g_current.GetString(current, sizeof(current));
    if (!StrEqual(mode, current, false)) {
        RestoreCvars();
        g_current.SetString(mode);
    }

    char playlist[PLATFORM_MAX_PATH] = "";
    if (g_playlist != null)
        g_playlist.GetString(playlist, sizeof(playlist));
    // The playlist's name, its part after the last slash
    int slash = FindCharInString(playlist, '/', true);
    char name[PLATFORM_MAX_PATH];
    strcopy(name, sizeof(name), playlist[slash + 1]);

    char configs[5][PLATFORM_MAX_PATH];
    Format(configs[0], sizeof(configs[]), "doi-config/basic_mode_%s.cfg", category);
    Format(configs[1], sizeof(configs[]), "doi-config/basic_mode_%s-%s.cfg", category, mode);
    if (playlist[0] != '\0') {
        Format(configs[2], sizeof(configs[]), "doi-config/playlists/%s-%s.cfg", playlist, mode);
        Format(configs[3], sizeof(configs[]), "doi-config/mode_%s.cfg", name);
        Format(configs[4], sizeof(configs[]), "doi-config/mode_%s-%s.cfg", name, mode);
    }
    // InsertServerCommand puts a command before those waiting, so the configs are inserted from the
    // last to the first, to run right after this command in their order
    for (int i = sizeof(configs) - 1; i >= 0; i--) {
        char path[PLATFORM_MAX_PATH];
        Format(path, sizeof(path), "cfg/%s", configs[i]);
        if (configs[i][0] != '\0' && FileExists(path, true))
            InsertServerCommand("exec \"%s\"", configs[i]);
    }
    PrintToServer("doi_mode: %s (%s), playlist %s", mode, category, playlist[0] != '\0' ? playlist : "none");
    return Plugin_Handled;
}

public Action Command_ModeCvar(int args)
{
    if (args != 2) {
        PrintToServer("Usage: doi_mode_cvar <cvar> <value>");
        return Plugin_Handled;
    }
    char name[CVAR_LENGTH], value[CVAR_LENGTH];
    GetCmdArg(1, name, sizeof(name));
    GetCmdArg(2, value, sizeof(value));
    ConVar cvar = FindConVar(name);
    if (cvar == null) {
        LogError("doi_mode_cvar: there's no cvar %s", name);
        return Plugin_Handled;
    }
    // Cvars' names are case-insensitive
    for (int i = 0; name[i] != '\0'; i++)
        name[i] = CharToLower(name[i]);
    // The value before the first change since the game mode changed, which a map change in the same
    // game mode doesn't replace
    if (!g_previous.ContainsKey(name)) {
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
    for (int i = g_names.Length - 1; i >= 0; i--) {
        g_names.GetString(i, name, sizeof(name));
        g_previous.GetString(name, value, sizeof(value));
        ConVar cvar = FindConVar(name);
        if (cvar != null)
            cvar.SetString(value);
    }
    if (g_names.Length > 0)
        PrintToServer("doi_mode: restored %d cvars of the previous game mode", g_names.Length);
    g_names.Clear();
    g_previous.Clear();
}
