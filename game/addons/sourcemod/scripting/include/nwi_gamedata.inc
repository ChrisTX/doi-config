// SPDX-FileCopyrightText: Christian Pfeiffer
// SPDX-License-Identifier: MIT OR GPL-3.0-only WITH LicenseRef-SourceMod-exception

// What nwi_gamedata.smx calls and hooks in Day of Infamy and Insurgency, for other plugins: the game's
// functions behind natives and forwards, so that only it has the gamedata (gamedata/nwi.games.txt).
//
// A plugin that can't work without it requires the library: `#include <nwi_gamedata>` does, unless
// REQUIRE_PLUGIN is undefined before it, in which case NWI_IsGamedataLoaded() tells whether it's there.

#if defined _nwi_gamedata_included
 #endinput
#endif
#define _nwi_gamedata_included

#include <regex>

#define NWI_GAMEDATA_LIBRARY "nwi_gamedata"

// The step of the physics simulation in seconds; false if the physics environment isn't there, e.g.
// before the first map
native bool NWI_GetPhysicsTimestep(float &step);

// Sets the step of the physics simulation; the game sets it anew at every map start. False if the
// physics environment isn't there.
native bool NWI_SetPhysicsTimestep(float step);

// Called when the server sends its details to Steam, which answers the server browsers' queries with
// them: its human players, its maximum (sv_visiblemaxplayers if set) and its bots. Changes of the
// counts go to Steam only, not to status or the server's own answers. bots is all the server's bots;
// afterwards, the server subtracts one for each of them (and for SourceTV) before it passes the bots
// on, so the browsers normally see none: what a plugin adds to bots is what they see.
forward void NWI_OnSteamServerDetails(int &humans, int &maximum, int &bots);

// Day of Infamy only: called when the server registers for the game's stats, at every map start,
// which it doesn't with workshop content. workshop: whether it uses the workshop; false registers it
// anyway.
forward void NWI_OnStatsWorkshopCheck(bool &workshop);

// Edits a playlist's data: the file of the playlist (scripts/playlists/<playlist>.playlist) as the
// game read it, with its own keys and its rulesets block, before the game merges the ruleset's block
// into it. playlist is its name in sv_playlist (e.g. nwi/coop_commando), ruleset the one this copy is
// for (default without one): the game keeps a copy of each playlist for each of its rulesets, so an edit
// for one ruleset doesn't reach the others. data is at its root and closed afterwards. Plugin_Changed
// keeps the edits; anything else drops them.
//
// The game makes its playlists at the start and again at every rebuild, so the same edit has to give
// the same data each time.
typedef NWI_PlaylistEditor = function Action (const char[] playlist, const char[] ruleset, KeyValues data);

// Adds an editor, which edits every playlist from then on, rebuilding the playlists unless the server
// is starting. Add it in OnAllPluginsLoaded, when nwi_gamedata is there, and again in OnLibraryAdded
// if nwi_gamedata is loaded anew. A plugin that's unloaded leaves its editors; the playlists keep its
// edits until they're rebuilt. False if the gamedata lacks the playlists' functions.
native bool NWI_AddPlaylistEditor(NWI_PlaylistEditor editor);

// Has the game make its playlists anew from their files, through the editors, e.g. after a change of
// an editor's settings. False if the gamedata lacks the playlists' functions.
native bool NWI_RebuildPlaylists();

// Helpers for editors, at the key the KeyValues is at: delete all of its keys of a name (a playlist
// may have several, like the maps of allowed_maps; the names count regardless of case, as in
// KeyValues), or those whose name matches a pattern; the number they deleted. They go through the
// keys and delete each with DeleteThis, as SourceMod's DeleteKey deletes nothing at the root.
stock int NWI_KvDeleteAll(KeyValues kv, const char[] name)
{
    int deleted = 0;
    char key[256];
    if (!kv.GotoFirstSubKey(false))
        return 0;
    for (;;)
    {
        kv.GetSectionName(key, sizeof(key));
        if (StrEqual(key, name, false))
        {
            deleted++;
            // DeleteThis goes on to the next key: 1 if there's one, else it's back at the parent
            if (kv.DeleteThis() != 1)
                return deleted;
        }
        else if (!kv.GotoNextKey(false))
        {
            kv.GoBack();
            return deleted;
        }
    }
}

stock int NWI_KvDeleteMatching(KeyValues kv, Regex pattern)
{
    int deleted = 0;
    char name[256];
    if (!kv.GotoFirstSubKey(false))
        return 0;
    for (;;)
    {
        kv.GetSectionName(name, sizeof(name));
        if (pattern.Match(name) > 0)
        {
            deleted++;
            // DeleteThis goes on to the next key: 1 if there's one, else it's back at the parent
            if (kv.DeleteThis() != 1)
                return deleted;
        }
        else if (!kv.GotoNextKey(false))
        {
            kv.GoBack();
            return deleted;
        }
    }
}

// Calls a function for each block of the playlist's rulesets (rulesets, <name>), at that block; the
// KeyValues is back at the root afterwards
typedef NWI_KvBlockCallback = function void (KeyValues kv, const char[] name, any data);

stock void NWI_KvForEachRuleset(KeyValues kv, NWI_KvBlockCallback callback, any data = 0)
{
    char name[256];
    kv.Rewind();
    if (!kv.JumpToKey("rulesets"))
        return;
    if (kv.GotoFirstSubKey(true))
    {
        do
        {
            kv.GetSectionName(name, sizeof(name));
            Call_StartFunction(INVALID_HANDLE, callback);
            Call_PushCell(kv);
            Call_PushString(name);
            Call_PushCell(data);
            Call_Finish();
        }
        while (kv.GotoNextKey(true));
    }
    kv.Rewind();
}

stock bool NWI_IsGamedataLoaded()
{
    return LibraryExists(NWI_GAMEDATA_LIBRARY);
}

// nwi_gamedata.smx itself defines NWI_GAMEDATA_PROVIDER, as it provides the library rather than
// depending on it
#if !defined NWI_GAMEDATA_PROVIDER
public SharedPlugin __pl_nwi_gamedata =
{
    name = NWI_GAMEDATA_LIBRARY,
    file = "nwi_gamedata.smx",
#if defined REQUIRE_PLUGIN
    required = 1,
#else
    required = 0,
#endif
};

#if !defined REQUIRE_PLUGIN
public void __pl_nwi_gamedata_SetNTVOptional()
{
    MarkNativeAsOptional("NWI_GetPhysicsTimestep");
    MarkNativeAsOptional("NWI_SetPhysicsTimestep");
    MarkNativeAsOptional("NWI_AddPlaylistEditor");
    MarkNativeAsOptional("NWI_RebuildPlaylists");
}
#endif
#endif
